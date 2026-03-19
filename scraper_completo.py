"""
CLCF Scraper Completo — Site + Google Scholar + Claude API
===========================================================
Combina 3 fontes para cada pesquisador:
  1. Site CLCF        → bio, cargo, posts, projetos
  2. Google Scholar   → publicações, citações, co-autores, áreas
  3. Claude API       → análise ontológica profunda

Dependências:
  pip install requests beautifulsoup4 lxml anthropic scholarly

Uso:
  ANTHROPIC_API_KEY=sua_chave python scraper_completo.py

  Sem IA (só palavras-chave):
  python scraper_completo.py
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from collections import defaultdict

# ── Scholarly (Google Scholar) ────────────────
try:
    from scholarly import scholarly, ProxyGenerator
    SCHOLARLY_OK = True
except ImportError:
    SCHOLARLY_OK = False
    print("! scholarly não instalado: pip install scholarly")

# ── Claude API ────────────────────────────────
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
USA_IA = bool(ANTHROPIC_KEY)
if USA_IA:
    try:
        import anthropic
        cliente_ia = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        print("✓ Claude API disponível")
    except ImportError:
        USA_IA = False

BASE_URL = "https://creativelabourcriticalfutures.ca"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Delay entre requisições ao site CLCF
DELAY_SITE = 1.5
# Delay entre requisições ao Scholar (importante para não ser bloqueado)
DELAY_SCHOLAR = 8.0


# ─────────────────────────────────────────────
# UTILITÁRIOS — SITE
# ─────────────────────────────────────────────

def buscar(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(DELAY_SITE)
        return BeautifulSoup(r.text, "lxml")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None
        print(f"  ✗ HTTP {e.response.status_code}: {url}")
        return None
    except Exception as e:
        print(f"  ✗ {url}: {e}")
        return None


def extrair_texto(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    content = (
        soup.find("div", class_=lambda c: c and "entry-content" in c) or
        soup.find("article") or soup.find("main")
    )
    src = content if content else soup
    return " ".join(src.get_text(separator=" ").split())


def extrair_links_externos(soup: BeautifulSoup) -> list[str]:
    return list({
        a["href"] for a in soup.find_all("a", href=True)
        if a["href"].startswith("http") and BASE_URL not in a["href"]
    })


# ─────────────────────────────────────────────
# UTILITÁRIOS — GOOGLE SCHOLAR
# ─────────────────────────────────────────────

def buscar_perfil_scholar(nome: str) -> dict:
    """
    Busca o perfil do pesquisador no Google Scholar pelo nome.
    Retorna publicações, co-autores, citações e áreas de interesse.
    """
    if not SCHOLARLY_OK:
        return {}

    print(f"    → Scholar: buscando '{nome}'...")
    time.sleep(DELAY_SCHOLAR)

    try:
        # Busca pelo nome
        resultados = scholarly.search_author(nome)
        autor = next(resultados, None)
        if not autor:
            print(f"    ! Não encontrado no Scholar: {nome}")
            return {}

        # Verifica se o resultado é plausível (nome parecido)
        nome_scholar = autor.get("name", "").lower()
        nome_partes = nome.lower().split()
        if not any(p in nome_scholar for p in nome_partes if len(p) > 3):
            print(f"    ! Scholar retornou '{autor.get('name')}' — pode não ser a pessoa certa")

        # Carrega perfil completo com publicações
        time.sleep(DELAY_SCHOLAR)
        autor_completo = scholarly.fill(autor, sections=["basics", "indices", "publications"])

        # Extrai publicações
        publicacoes = []
        for pub in autor_completo.get("publications", [])[:50]:  # limita a 50
            bib = pub.get("bib", {})
            publicacoes.append({
                "titulo": bib.get("title", ""),
                "ano": bib.get("pub_year", ""),
                "venue": bib.get("venue", ""),
                "citacoes": pub.get("num_citations", 0),
                "autores": bib.get("author", ""),
            })
            time.sleep(0.5)

        # Co-autores do Scholar
        coautores_scholar = [
            c.get("name", "") for c in autor_completo.get("coauthors", [])
        ]

        return {
            "scholar_id": autor_completo.get("scholar_id", ""),
            "scholar_url": f"https://scholar.google.com/citations?user={autor_completo.get('scholar_id', '')}",
            "areas_scholar": autor_completo.get("interests", []),
            "citacoes_total": autor_completo.get("citedby", 0),
            "h_index": autor_completo.get("hindex", 0),
            "i10_index": autor_completo.get("i10index", 0),
            "instituicao_scholar": autor_completo.get("affiliation", ""),
            "publicacoes": publicacoes,
            "coautores_scholar": coautores_scholar,
            "n_publicacoes": len(publicacoes),
        }

    except StopIteration:
        print(f"    ! Nenhum resultado Scholar para: {nome}")
        return {}
    except Exception as e:
        print(f"    ! Erro Scholar ({nome}): {e}")
        return {}


def extrair_coautores_das_publicacoes(publicacoes: list) -> list[str]:
    """Extrai todos os nomes de co-autores das publicações."""
    coautores = set()
    for pub in publicacoes:
        autores_str = pub.get("autores", "")
        if autores_str:
            # Formato Scholar: "A Autor, B Autor, C Autor"
            for a in autores_str.split(","):
                nome = a.strip()
                if nome and len(nome) > 3:
                    coautores.add(nome)
    return list(coautores)


# ─────────────────────────────────────────────
# UTILITÁRIOS — CLAUDE API
# ─────────────────────────────────────────────

def analisar_com_ia(texto_bio: str, publicacoes: list, areas_scholar: list) -> dict:
    """
    Usa Claude para extrair ontologia rica combinando bio + publicações + áreas Scholar.
    """
    if not USA_IA:
        return extrair_palavras_chave(texto_bio)

    # Resume as publicações para o prompt
    pubs_resumo = "\n".join([
        f"- {p['ano']} | {p['titulo']} | {p['venue']} | {p['citacoes']} citações"
        for p in sorted(publicacoes, key=lambda x: x.get("citacoes", 0), reverse=True)[:20]
    ]) if publicacoes else "Nenhuma publicação encontrada"

    areas_str = ", ".join(areas_scholar) if areas_scholar else "Não disponível"

    prompt = f"""Você é um especialista em ontologias acadêmicas. Analise o perfil deste pesquisador do projeto Creative Labour and Critical Futures (CLCF) — uma iniciativa canadense sobre trabalho criativo, IA e futuros críticos.

BIOGRAFIA:
{texto_bio[:3000]}

ÁREAS DE INTERESSE (Google Scholar):
{areas_str}

PUBLICAÇÕES MAIS CITADAS:
{pubs_resumo}

Retorne APENAS um objeto JSON válido (sem markdown) com:
{{
  "temas_principais": ["3-6 temas centrais da pesquisa desta pessoa, em português, específicos"],
  "temas_secundarios": ["temas relacionados mas não centrais"],
  "metodos": ["métodos de pesquisa usados"],
  "disciplinas": ["disciplinas acadêmicas"],
  "palavras_chave": ["15 palavras-chave mais relevantes"],
  "projetos_ativos": ["projetos de pesquisa ativos mencionados"],
  "instituicoes_parceiras": ["instituições com que colabora"],
  "geografias": ["regiões/países foco da pesquisa"],
  "objetos_estudo": ["objetos empíricos de estudo (ex: entregadores, plataformas digitais, etc)"],
  "contribuicao_clcf": "1 frase sobre como esta pessoa contribui especificamente para o CLCF",
  "resumo": "resumo de 3 frases sobre quem é e o que faz"
}}"""

    try:
        resposta = cliente_ia.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        conteudo = resposta.content[0].text.strip()
        conteudo = re.sub(r"```json\s*|\s*```", "", conteudo).strip()
        return json.loads(conteudo)
    except Exception as e:
        print(f"    ! IA falhou: {e}")
        return extrair_palavras_chave(texto_bio)


def analisar_publicacoes_com_ia(publicacoes: list, nome_pesquisador: str) -> dict:
    """Analisa o conjunto de publicações para extrair padrões temáticos."""
    if not USA_IA or not publicacoes:
        return {}

    titulos = "\n".join([
        f"- ({p['ano']}) {p['titulo']}"
        for p in sorted(publicacoes, key=lambda x: x.get("ano", "0"), reverse=True)[:30]
    ])

    prompt = f"""Analise esta lista de publicações de {nome_pesquisador} e retorne APENAS um JSON válido:
{{
  "evolucao_tematica": "como os temas evoluíram ao longo do tempo em 2 frases",
  "temas_recorrentes": ["temas que aparecem repetidamente nos títulos"],
  "periodos": {{
    "antes_2018": ["temas predominantes antes de 2018"],
    "2018_2022": ["temas de 2018 a 2022"],
    "pos_2022": ["temas após 2022"]
  }},
  "tipos_producao": ["artigos", "livros", "capítulos", "relatórios", etc]
}}

Publicações:
{titulos}"""

    try:
        resposta = cliente_ia.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        conteudo = re.sub(r"```json\s*|\s*```", "", resposta.content[0].text.strip())
        return json.loads(conteudo)
    except Exception:
        return {}


def extrair_palavras_chave(texto: str) -> dict:
    """Fallback sem IA — extração por palavras-chave."""
    TEMAS = {
        "Trabalho Digital": ["digital labour", "platform labour", "gig economy"],
        "Inteligência Artificial": ["artificial intelligence", "AI", "machine learning"],
        "Trabalho Criativo": ["creative labour", "creative work", "cultural production"],
        "Raça": ["race", "racism", "racialized", "Black", "BIPOC"],
        "Gênero": ["gender", "feminist", "women", "queer"],
        "Colonialismo": ["colonial", "decolonial", "Indigenous"],
        "Plataformas": ["platform", "algorithm", "datafication"],
        "Política Cultural": ["cultural policy", "arts funding", "public policy"],
        "Arquivos": ["archive", "archival", "memory"],
        "Música": ["music", "sonic", "sound"],
        "Fotografia": ["photography", "visual art"],
        "Mídia": ["media", "communication", "broadcasting"],
    }
    t = texto.lower()
    temas = [k for k, vs in TEMAS.items() if any(v in t for v in vs)]
    return {
        "temas_principais": temas[:5],
        "temas_secundarios": temas[5:],
        "metodos": [],
        "disciplinas": [],
        "palavras_chave": [],
        "projetos_ativos": [],
        "instituicoes_parceiras": [],
        "geografias": [],
        "objetos_estudo": [],
        "contribuicao_clcf": "",
        "resumo": "",
    }


# ─────────────────────────────────────────────
# COLETA: SITE CLCF
# ─────────────────────────────────────────────

def coletar_lista_pessoas() -> list[dict]:
    """Coleta nome, cargo, grupo e URL de cada pesquisador."""
    soup = buscar(f"{BASE_URL}/people/")
    if not soup:
        return []

    membros = []
    grupo_atual = "CLCF Researcher"

    for el in soup.find_all(["h2", "li"]):
        if el.name == "h2":
            grupo_atual = el.get_text(strip=True)
        elif el.name == "li":
            a = el.find("a", href=True)
            nome_el = el.find(["h5", "h4", "h3"])
            cargo_el = el.find("p")
            if a and "/people/" in a["href"] and a["href"] != f"{BASE_URL}/people/":
                nome = nome_el.get_text(strip=True) if nome_el else a.get_text(strip=True)
                cargo = cargo_el.get_text(strip=True) if cargo_el else ""
                if nome and not any(m["url"] == a["href"] for m in membros):
                    membros.append({
                        "url": a["href"], "nome": nome,
                        "cargo": cargo, "grupo": grupo_atual
                    })
    return membros


def coletar_bio_e_posts(url: str) -> dict:
    """Coleta bio completa e URLs de todos os posts do pesquisador."""
    soup = buscar(url)
    if not soup:
        return {"bio": "", "links_externos": [], "posts_urls": []}

    bio = extrair_texto(soup)
    links_externos = extrair_links_externos(soup)

    # Coleta posts com paginação
    posts_urls = []
    pagina = 1
    soup_atual = soup
    while True:
        for art in soup_atual.find_all("article"):
            a = art.find("a", href=True)
            if a and a["href"] not in posts_urls:
                posts_urls.append(a["href"])
        if not soup_atual.find("a", class_=lambda c: c and "next" in c):
            break
        pagina += 1
        url_pag = f"{url.rstrip('/')}/page/{pagina}/"
        soup_atual = buscar(url_pag)
        if not soup_atual:
            break

    return {"bio": bio[:6000], "links_externos": links_externos, "posts_urls": posts_urls}


def coletar_post(url: str, tipo: str) -> dict | None:
    """Coleta e analisa um post/página individualmente."""
    soup = buscar(url)
    if not soup:
        return None

    titulo_el = soup.find("h1") or soup.find("h2", class_=lambda c: c and "title" in c)
    titulo = titulo_el.get_text(strip=True) if titulo_el else "Sem título"

    data_el = soup.find("time")
    data = (data_el.get("datetime", data_el.get_text())[:10]
            if data_el else "")

    texto = extrair_texto(soup)
    analise = extrair_palavras_chave(texto)  # posts usam palavras-chave (economiza IA)

    return {
        "id": url.rstrip("/").split("/")[-1],
        "titulo": titulo, "tipo": tipo,
        "data": data, "url": url,
        "texto": texto[:5000],
        "temas": analise.get("temas_principais", []),
        "autores_detectados": [],
    }


def coletar_secao(nome: str, url_base: str, tipo: str, urls_vistas: set) -> list[dict]:
    print(f"\n  Coletando {nome}...")
    itens = []
    pagina = 1
    while True:
        url = url_base if pagina == 1 else f"{url_base}page/{pagina}/"
        soup = buscar(url)
        if not soup:
            break
        arts = soup.find_all("article")
        if not arts:
            break
        for art in arts:
            a = art.find("a", href=True)
            if a and a["href"] not in urls_vistas:
                item = coletar_post(a["href"], tipo)
                if item:
                    itens.append(item)
                    urls_vistas.add(a["href"])
                    print(f"    ✓ {item['titulo'][:60]}")
        if not soup.find("a", class_=lambda c: c and "next" in c):
            break
        pagina += 1
    return itens


# ─────────────────────────────────────────────
# PIPELINE PRINCIPAL POR PESQUISADOR
# ─────────────────────────────────────────────

def processar_pesquisador(info: dict) -> dict:
    nome = info["nome"]
    print(f"\n  ── {nome} ──")

    # 1. Bio e posts do site CLCF
    dados_site = coletar_bio_e_posts(info["url"])

    # 2. Google Scholar
    dados_scholar = buscar_perfil_scholar(nome) if SCHOLARLY_OK else {}

    # 3. Análise de publicações ao longo do tempo
    analise_pubs = {}
    if dados_scholar.get("publicacoes"):
        print(f"    → Analisando {len(dados_scholar['publicacoes'])} publicações...")
        analise_pubs = analisar_publicacoes_com_ia(
            dados_scholar["publicacoes"], nome
        )

    # 4. Análise ontológica completa com IA
    print(f"    → Análise ontológica...")
    analise = analisar_com_ia(
        dados_site["bio"],
        dados_scholar.get("publicacoes", []),
        dados_scholar.get("areas_scholar", [])
    )

    # 5. Todos os co-autores (Scholar + mencionados na bio)
    coautores = list(set(
        dados_scholar.get("coautores_scholar", []) +
        extrair_coautores_das_publicacoes(dados_scholar.get("publicacoes", []))
    ))

    slug = info["url"].rstrip("/").split("/")[-1]
    return {
        "id": slug,
        "nome": nome,
        "cargo": info["cargo"],
        "grupo": info["grupo"],
        "url": info["url"],

        # Site CLCF
        "bio": dados_site["bio"],
        "links_externos": dados_site["links_externos"],
        "posts_urls": dados_site["posts_urls"],

        # Google Scholar
        "scholar_id": dados_scholar.get("scholar_id", ""),
        "scholar_url": dados_scholar.get("scholar_url", ""),
        "areas_scholar": dados_scholar.get("areas_scholar", []),
        "citacoes_total": dados_scholar.get("citacoes_total", 0),
        "h_index": dados_scholar.get("h_index", 0),
        "i10_index": dados_scholar.get("i10_index", 0),
        "n_publicacoes": dados_scholar.get("n_publicacoes", 0),
        "publicacoes": dados_scholar.get("publicacoes", []),
        "coautores": coautores,
        "analise_publicacoes": analise_pubs,

        # Ontologia (Claude API)
        "temas_principais": analise.get("temas_principais", []),
        "temas_secundarios": analise.get("temas_secundarios", []),
        "metodos": analise.get("metodos", []),
        "disciplinas": analise.get("disciplinas", []),
        "palavras_chave": analise.get("palavras_chave", []),
        "projetos_ativos": analise.get("projetos_ativos", []),
        "instituicoes_parceiras": analise.get("instituicoes_parceiras", []),
        "geografias": analise.get("geografias", []),
        "objetos_estudo": analise.get("objetos_estudo", []),
        "contribuicao_clcf": analise.get("contribuicao_clcf", ""),
        "resumo": analise.get("resumo", ""),

        # Preenchido depois
        "posts_ids": [],
    }


# ─────────────────────────────────────────────
# CONSTRUÇÃO DA ONTOLOGIA
# ─────────────────────────────────────────────

def construir_ontologia(pessoas: list, conteudos: list) -> dict:
    print("\n[Construindo ontologia...]")

    # Índice por nome para detectar menções
    indice_nomes = {}
    for p in pessoas:
        for parte in p["nome"].lower().split():
            if len(parte) > 3:
                indice_nomes[parte] = p["id"]
        indice_nomes[p["id"]] = p["id"]

    # Índice por co-autores (nomes do Scholar → id CLCF)
    indice_coautores = {}
    for p in pessoas:
        for coautor in p.get("coautores", []):
            for parte in coautor.lower().split():
                if len(parte) > 3:
                    if parte not in indice_coautores:
                        indice_coautores[parte] = []
                    indice_coautores[parte].append(p["id"])

    # Detecta autores em cada post
    url_para_autores = defaultdict(set)
    for p in pessoas:
        for purl in p.get("posts_urls", []):
            url_para_autores[purl].add(p["id"])

    for item in conteudos:
        autores = set(url_para_autores.get(item["url"], set()))
        txt = item.get("texto", "").lower()
        for parte, pid in indice_nomes.items():
            if parte in txt:
                autores.add(pid)
        item["autores_detectados"] = list(autores)
        for aid in autores:
            p = next((x for x in pessoas if x["id"] == aid), None)
            if p:
                p["posts_ids"].append(item["id"])

    # Frequências
    freq_temas = defaultdict(int)
    freq_metodos = defaultdict(int)
    freq_geografias = defaultdict(int)
    freq_objetos = defaultdict(int)

    for p in pessoas:
        for t in p.get("temas_principais", []): freq_temas[t] += 3
        for t in p.get("temas_secundarios", []): freq_temas[t] += 1
        for m in p.get("metodos", []): freq_metodos[m] += 1
        for g in p.get("geografias", []): freq_geografias[g] += 1
        for o in p.get("objetos_estudo", []): freq_objetos[o] += 1

    for item in conteudos:
        for t in item.get("temas", []): freq_temas[t] += 1

    # ── NÓS ──────────────────────────────────
    nos = []

    for p in pessoas:
        nos.append({
            "id": p["id"],
            "label": p["nome"],
            "tipo": "pessoa",
            "cargo": p["cargo"],
            "grupo": p["grupo"],
            "temas": p.get("temas_principais", []),
            "metodos": p.get("metodos", []),
            "disciplinas": p.get("disciplinas", []),
            "geografias": p.get("geografias", []),
            "objetos_estudo": p.get("objetos_estudo", []),
            "palavras_chave": p.get("palavras_chave", []),
            "resumo": p.get("resumo", ""),
            "contribuicao_clcf": p.get("contribuicao_clcf", ""),
            "citacoes_total": p.get("citacoes_total", 0),
            "h_index": p.get("h_index", 0),
            "n_publicacoes": p.get("n_publicacoes", 0),
            "n_posts": len(set(p.get("posts_ids", []))),
            "scholar_url": p.get("scholar_url", ""),
            "url": p["url"],
            "bio_resumo": p.get("bio", "")[:400],
        })

    for tema, freq in freq_temas.items():
        if freq >= 2:
            nos.append({
                "id": f"tema_{re.sub(r'[^a-z0-9]', '_', tema.lower())}",
                "label": tema, "tipo": "tema", "freq": freq
            })

    for met, freq in freq_metodos.items():
        if freq >= 2:
            nos.append({
                "id": f"met_{re.sub(r'[^a-z0-9]', '_', met.lower())}",
                "label": met, "tipo": "metodo", "freq": freq
            })

    for obj, freq in freq_objetos.items():
        if freq >= 2:
            nos.append({
                "id": f"obj_{re.sub(r'[^a-z0-9]', '_', obj.lower()[:30])}",
                "label": obj, "tipo": "objeto_estudo", "freq": freq
            })

    nos_ids = {n["id"] for n in nos}

    # ── ARESTAS ───────────────────────────────
    arestas = []
    vistas = set()

    def add(src, tgt, tipo, **kw):
        chave = (tipo, tuple(sorted([str(src), str(tgt)])))
        if chave not in vistas:
            vistas.add(chave)
            arestas.append({"source": src, "target": tgt, "tipo": tipo, **kw})
        else:
            for e in arestas:
                if e["tipo"] == tipo and {e["source"], e["target"]} == {src, tgt}:
                    e["peso"] = e.get("peso", 1) + 1

    # Pessoa ↔ tema
    for p in pessoas:
        for t in p.get("temas_principais", []):
            tid = f"tema_{re.sub(r'[^a-z0-9]', '_', t.lower())}"
            if tid in nos_ids:
                add(p["id"], tid, "pessoa_tema", peso=3)
        for t in p.get("temas_secundarios", []):
            tid = f"tema_{re.sub(r'[^a-z0-9]', '_', t.lower())}"
            if tid in nos_ids:
                add(p["id"], tid, "pessoa_tema", peso=1)

    # Pessoa ↔ método
    for p in pessoas:
        for m in p.get("metodos", []):
            mid = f"met_{re.sub(r'[^a-z0-9]', '_', m.lower())}"
            if mid in nos_ids:
                add(p["id"], mid, "pessoa_metodo", peso=1)

    # Pessoa ↔ objeto de estudo
    for p in pessoas:
        for o in p.get("objetos_estudo", []):
            oid = f"obj_{re.sub(r'[^a-z0-9]', '_', o.lower()[:30])}"
            if oid in nos_ids:
                add(p["id"], oid, "pessoa_objeto", peso=2)

    # Pessoa ↔ pessoa (temas em comum — ponderado)
    for i, p1 in enumerate(pessoas):
        for p2 in pessoas[i+1:]:
            t1 = set(p1.get("temas_principais", []))
            t2 = set(p2.get("temas_principais", []))
            t1s = set(p1.get("temas_secundarios", []))
            t2s = set(p2.get("temas_secundarios", []))
            m1 = set(p1.get("metodos", []))
            m2 = set(p2.get("metodos", []))
            o1 = set(p1.get("objetos_estudo", []))
            o2 = set(p2.get("objetos_estudo", []))
            g1 = set(p1.get("geografias", []))
            g2 = set(p2.get("geografias", []))

            peso = (
                len(t1 & t2) * 4 +       # temas principais em comum
                len((t1 & t2s) | (t1s & t2)) * 2 +  # 1 principal + 1 sec
                len(m1 & m2) * 3 +        # métodos em comum
                len(o1 & o2) * 3 +        # objetos de estudo em comum
                len(g1 & g2) * 2          # geografias em comum
            )

            if peso > 0:
                add(p1["id"], p2["id"], "afinidade_tematica",
                    temas_comuns=list(t1 & t2),
                    metodos_comuns=list(m1 & m2),
                    objetos_comuns=list(o1 & o2),
                    geografias_comuns=list(g1 & g2),
                    peso=peso)

    # Pessoa ↔ pessoa (co-autoria via Scholar)
    nomes_para_id = {p["nome"].lower(): p["id"] for p in pessoas}
    for p in pessoas:
        for coautor in p.get("coautores", []):
            coautor_lower = coautor.lower()
            # Verifica se o co-autor é outro membro do CLCF
            for nome_clcf, pid_clcf in nomes_para_id.items():
                partes_clcf = nome_clcf.split()
                if any(parte in coautor_lower for parte in partes_clcf if len(parte) > 3):
                    if pid_clcf != p["id"]:
                        add(p["id"], pid_clcf, "coautoria_scholar", peso=5)

    # Pessoa ↔ pessoa (co-aparição em posts)
    for item in conteudos:
        ats = item["autores_detectados"]
        for i, a1 in enumerate(ats):
            for a2 in ats[i+1:]:
                add(a1, a2, "coautoria_post", post=item["id"], peso=2)

    # Timeline
    timeline = sorted([
        {"id": c["id"], "titulo": c["titulo"], "data": c["data"],
         "tipo": c["tipo"], "temas": c.get("temas", [])[:4],
         "url": c["url"], "autores": c["autores_detectados"]}
        for c in conteudos if c.get("data")
    ], key=lambda x: x["data"])

    # Nuvem de palavras-chave
    freq_kw = defaultdict(int)
    for p in pessoas:
        for kw in p.get("palavras_chave", []):
            freq_kw[kw.lower()] += 2
    for p in pessoas:
        for t in p.get("temas_principais", []):
            freq_kw[t.lower()] += 3
    nuvem = [{"texto": k, "freq": v}
             for k, v in sorted(freq_kw.items(), key=lambda x: -x[1])
             if len(k) > 2][:80]

    # Tabela de publicações consolidada
    todas_pubs = []
    for p in pessoas:
        for pub in p.get("publicacoes", []):
            todas_pubs.append({
                "pesquisador_id": p["id"],
                "pesquisador_nome": p["nome"],
                **pub
            })
    todas_pubs.sort(key=lambda x: str(x.get("ano", "")), reverse=True)

    return {
        "meta": {
            "titulo": "CLCF — Ontologia Completa",
            "n_pessoas": len(pessoas),
            "n_conteudos": len(conteudos),
            "n_nos": len(nos),
            "n_arestas": len(arestas),
            "n_publicacoes": len(todas_pubs),
            "analise_ia": USA_IA,
            "scholar": SCHOLARLY_OK,
        },
        "nos": nos,
        "arestas": arestas,
        "timeline": timeline,
        "nuvem_temas": nuvem,
        "publicacoes": todas_pubs[:200],
        "pessoas": [{k: v for k, v in p.items()
                     if k not in ["bio", "publicacoes"]}
                    for p in pessoas],
        "conteudos": [{k: v for k, v in c.items() if k != "texto"}
                      for c in conteudos],
    }


# ─────────────────────────────────────────────
# EXECUÇÃO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  CLCF Scraper Completo")
    print(f"  Scholar : {'✓' if SCHOLARLY_OK else '✗'}")
    print(f"  IA      : {'✓' if USA_IA else '✗'}")
    print("=" * 55)

    # 1. Lista de pesquisadores
    print("\n[1] Coletando lista de pesquisadores...")
    lista = coletar_lista_pessoas()
    print(f"  → {len(lista)} pesquisadores")

    # 2. Perfil completo de cada um
    print("\n[2] Processando perfis (site + Scholar + IA)...")
    pessoas = []
    for info in lista:
        p = processar_pesquisador(info)
        pessoas.append(p)
        # Salva checkpoint a cada pesquisador (caso o script seja interrompido)
        with open("clcf_checkpoint.json", "w", encoding="utf-8") as f:
            json.dump(pessoas, f, ensure_ascii=False, indent=2)

    # 3. Conteúdos do site
    urls_vistas = set()
    for p in pessoas:
        urls_vistas.update(p.get("posts_urls", []))

    print("\n[3] Coletando conteúdos do site...")
    conteudos = []
    conteudos += coletar_secao("Blog", f"{BASE_URL}/category/blog/", "Blog Post", urls_vistas)
    conteudos += coletar_secao("Projects", f"{BASE_URL}/category/projects/", "Project", urls_vistas)
    conteudos += coletar_secao("Speaker Series", f"{BASE_URL}/category/speaker-series/", "Speaker Series", urls_vistas)
    conteudos += coletar_secao("Resources", f"{BASE_URL}/category/resources/", "Resource", urls_vistas)

    # 4. Ontologia
    print("\n[4] Construindo ontologia...")
    ontologia = construir_ontologia(pessoas, conteudos)

    # 5. Salva
    with open("clcf_ontologia.json", "w", encoding="utf-8") as f:
        json.dump(ontologia, f, ensure_ascii=False, indent=2)

    m = ontologia["meta"]
    print("\n" + "=" * 55)
    print(f"  Pesquisadores : {m['n_pessoas']}")
    print(f"  Publicações   : {m['n_publicacoes']}")
    print(f"  Conteúdos     : {m['n_conteudos']}")
    print(f"  Nós no grafo  : {m['n_nos']}")
    print(f"  Conexões      : {m['n_arestas']}")
    print("\n  ✓ clcf_ontologia.json gerado!")
    print("=" * 55)
