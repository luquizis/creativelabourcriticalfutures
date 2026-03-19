"""
CLCF Deep Scraper v2 — Ontologia Rica
=======================================
Raspa TODO o conteúdo do site e usa Claude API para extrair
entidades ontológicas ricas de cada página.

Dependências:
  pip install requests beautifulsoup4 lxml anthropic

Uso:
  # Com análise por IA (recomendado):
  ANTHROPIC_API_KEY=sua_chave python scraper_profundo.py

  # Sem IA (só extração por palavras-chave):
  python scraper_profundo.py
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
import os
from collections import defaultdict

BASE_URL = "https://creativelabourcriticalfutures.ca"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
DELAY = 1.5  # segundos entre requisições

# Verifica se Claude API está disponível
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
USA_IA = bool(ANTHROPIC_KEY)

if USA_IA:
    try:
        import anthropic
        cliente_ia = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        print("✓ Claude API disponível — extração ontológica enriquecida")
    except ImportError:
        USA_IA = False
        print("! anthropic não instalado — usando extração por palavras-chave")
else:
    print("! ANTHROPIC_API_KEY não encontrada — usando extração por palavras-chave")


# ─────────────────────────────────────────────
# PALAVRAS-CHAVE TEMÁTICAS (fallback sem IA)
# ─────────────────────────────────────────────

TEMAS_DICT = {
    "Inteligência Artificial": ["artificial intelligence", "AI", "machine learning", "algorithm", "generative AI", "large language model", "ChatGPT"],
    "Trabalho Criativo": ["creative labour", "creative work", "creative workers", "creative industries", "cultural production"],
    "Trabalho Digital": ["digital labour", "platform labour", "gig economy", "gig work", "platform work", "crowdwork"],
    "Raça e Racismo": ["race", "racism", "racialized", "anti-racism", "Black", "BIPOC", "white supremacy"],
    "Povos Indígenas": ["Indigenous", "decolonial", "settler colonial", "First Nations", "Métis", "Inuit"],
    "Gênero e Feminismo": ["gender", "feminist", "feminism", "women", "sexism", "patriarchy"],
    "Queer": ["queer", "LGBTQ", "trans", "non-binary", "sexuality"],
    "Colonialismo": ["colonialism", "colonial", "postcolonial", "imperialism", "empire"],
    "Música": ["music", "musician", "sound", "audio", "sonic", "composer", "recording"],
    "Fotografia": ["photography", "photographer", "photo", "image", "visual art"],
    "Cinema e Vídeo": ["film", "cinema", "video", "documentary", "screen", "streaming"],
    "Artes Visuais": ["visual art", "artist", "gallery", "exhibition", "painting", "sculpture"],
    "Mídia Digital": ["digital media", "social media", "platform", "online", "internet"],
    "Política Cultural": ["cultural policy", "arts policy", "funding", "grant", "public policy"],
    "Arquivos": ["archive", "archival", "counterarchive", "memory", "preservation"],
    "Research-Creation": ["research-creation", "arts-based research", "practice-based", "creative research"],
    "Métodos": ["methodology", "ethnography", "walking methods", "qualitative", "quantitative"],
    "Direitos Trabalhistas": ["labour rights", "worker rights", "union", "organizing", "collective bargaining"],
    "Ética": ["ethics", "ethical", "responsibility", "accountability", "critical"],
    "Geopolítica": ["geopolitics", "global south", "diaspora", "transnational", "international"],
    "Deficiência": ["disability", "accessibility", "ableism", "crip"],
    "Economia": ["economy", "economic", "capitalism", "neoliberal", "financialization"],
    "Tecnologia": ["technology", "tech", "digital", "software", "hardware", "infrastructure"],
    "Educação": ["education", "pedagogy", "teaching", "university", "curriculum"],
    "Meio Ambiente": ["climate", "environment", "sustainability", "ecology", "green"],
}

METODOS = ["ethnography", "interview", "survey", "case study", "discourse analysis",
           "content analysis", "walking methods", "arts-based research", "research-creation",
           "participatory", "autoethnography", "archival research", "mixed methods"]

DISCIPLINAS = ["media studies", "communication", "sociology", "anthropology", "cultural studies",
               "art history", "musicology", "film studies", "labour studies", "feminist studies",
               "political economy", "information studies", "science and technology studies"]


# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def buscar(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(DELAY)
        return BeautifulSoup(r.text, "lxml")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return None
        print(f"  ✗ HTTP {e.response.status_code}: {url}")
        return None
    except Exception as e:
        print(f"  ✗ {url}: {e}")
        return None


def extrair_conteudo_principal(soup: BeautifulSoup) -> str:
    """Extrai o texto do conteúdo principal, removendo nav/footer."""
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    content = (
        soup.find("div", class_=lambda c: c and "entry-content" in c) or
        soup.find("div", class_=lambda c: c and "post-content" in c) or
        soup.find("article") or
        soup.find("main") or
        soup.find("div", class_=lambda c: c and "content" in c)
    )
    if content:
        return " ".join(content.get_text(separator=" ").split())
    return " ".join(soup.get_text(separator=" ").split())


def extrair_links_externos(soup: BeautifulSoup) -> list[str]:
    """Coleta links externos (fora do domínio base)."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and BASE_URL not in href:
            links.append(href)
    return list(set(links))


def extrair_temas_keywords(texto: str) -> dict:
    """Extração de temas, métodos e disciplinas por palavras-chave."""
    texto_lower = texto.lower()
    temas = [tema for tema, palavras in TEMAS_DICT.items()
             if any(p.lower() in texto_lower for p in palavras)]
    metodos_enc = [m for m in METODOS if m.lower() in texto_lower]
    disc_enc = [d for d in DISCIPLINAS if d.lower() in texto_lower]
    return {"temas": temas, "metodos": metodos_enc, "disciplinas": disc_enc}


def analisar_com_ia(texto: str, contexto: str = "perfil") -> dict:
    """Usa Claude para extrair entidades ontológicas do texto."""
    if not USA_IA or not texto.strip():
        return extrair_temas_keywords(texto)

    prompt = f"""Analise este texto de {contexto} de um pesquisador/conteúdo do projeto Creative Labour and Critical Futures (CLCF), uma iniciativa acadêmica canadense sobre trabalho criativo e futuros críticos na era da IA.

Extraia e retorne APENAS um objeto JSON válido (sem markdown, sem explicações) com:
{{
  "temas": ["lista de temas de pesquisa identificados, em português, específicos e significativos"],
  "metodos": ["métodos de pesquisa usados ou mencionados"],
  "disciplinas": ["disciplinas acadêmicas relacionadas"],
  "palavras_chave": ["10-15 palavras-chave mais relevantes do texto"],
  "projetos": ["nomes de projetos de pesquisa mencionados"],
  "instituicoes": ["instituições parceiras ou mencionadas"],
  "publicacoes": ["títulos de publicações mencionadas se houver"],
  "colaboradores": ["nomes de outras pessoas mencionadas como colaboradores"],
  "resumo": "resumo de 2 frases do que trata este conteúdo"
}}

Texto:
{texto[:4000]}"""

    try:
        resposta = cliente_ia.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        conteudo = resposta.content[0].text.strip()
        # Remove possíveis blocos de código markdown
        conteudo = re.sub(r"```json\s*|\s*```", "", conteudo).strip()
        return json.loads(conteudo)
    except Exception as e:
        print(f"    ! IA falhou, usando palavras-chave: {e}")
        return extrair_temas_keywords(texto)


# ─────────────────────────────────────────────
# COLETA: PESSOAS (PERFIL COMPLETO)
# ─────────────────────────────────────────────

def coletar_perfil_completo(url: str, nome: str, cargo: str, grupo: str) -> dict:
    """Coleta bio completa + todos os posts vinculados ao pesquisador."""
    soup = buscar(url)
    if not soup:
        return {}

    # Bio completa
    texto = extrair_conteudo_principal(soup)
    links_externos = extrair_links_externos(soup)

    # Posts vinculados ao pesquisador (com paginação)
    posts_urls = []
    pagina = 1
    while True:
        url_pag = url if pagina == 1 else f"{url.rstrip('/')}/page/{pagina}/"
        soup_pag = buscar(url_pag) if pagina > 1 else soup
        if not soup_pag:
            break
        artigos = soup_pag.find_all("article")
        if not artigos and pagina > 1:
            break
        for art in artigos:
            a = art.find("a", href=True)
            if a and a["href"] not in posts_urls:
                posts_urls.append(a["href"])
        if not soup_pag.find("a", class_=lambda c: c and "next" in c):
            break
        pagina += 1

    # Análise ontológica da bio
    print(f"    → Analisando bio de {nome}...")
    analise = analisar_com_ia(texto, contexto="perfil de pesquisador")

    slug = url.rstrip("/").split("/")[-1]
    return {
        "id": slug,
        "nome": nome,
        "cargo": cargo,
        "grupo": grupo,
        "url": url,
        "bio_completa": texto[:6000],
        "links_externos": links_externos,
        "posts_urls": posts_urls,
        "temas": analise.get("temas", []),
        "metodos": analise.get("metodos", []),
        "disciplinas": analise.get("disciplinas", []),
        "palavras_chave": analise.get("palavras_chave", []),
        "projetos": analise.get("projetos", []),
        "instituicoes": analise.get("instituicoes", []),
        "publicacoes": analise.get("publicacoes", []),
        "colaboradores_mencionados": analise.get("colaboradores", []),
        "resumo": analise.get("resumo", ""),
        "posts_completos": [],   # preenchido depois
    }


def coletar_todas_pessoas() -> list[dict]:
    print("\n[1/5] Coletando perfis completos dos pesquisadores...")
    pessoas = []

    soup_lista = buscar(f"{BASE_URL}/people/")
    if not soup_lista:
        return pessoas

    # Mapeia nome, cargo, grupo e URL de cada pesquisador
    membros = []
    grupo_atual = "CLCF Researcher"
    for el in soup_lista.find_all(["h2", "li"]):
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

    print(f"  → {len(membros)} pesquisadores encontrados")

    for m in membros:
        print(f"  ✓ {m['nome']}")
        perfil = coletar_perfil_completo(m["url"], m["nome"], m["cargo"], m["grupo"])
        if perfil:
            pessoas.append(perfil)

    return pessoas


# ─────────────────────────────────────────────
# COLETA: CONTEÚDO COMPLETO (POSTS/PAGES)
# ─────────────────────────────────────────────

def coletar_post_completo(url: str, tipo: str) -> dict | None:
    """Coleta e analisa um post/página individual completamente."""
    soup = buscar(url)
    if not soup:
        return None

    titulo_el = soup.find("h1") or soup.find("h2", class_=lambda c: c and "title" in c)
    titulo = titulo_el.get_text(strip=True) if titulo_el else "Sem título"

    data_el = soup.find("time")
    data = data_el.get("datetime", data_el.get_text(strip=True))[:10] if data_el else ""

    texto = extrair_conteudo_principal(soup)
    links_externos = extrair_links_externos(soup)

    # Tags/categorias
    tags = [t.get_text(strip=True) for t in
            soup.find_all(class_=lambda c: c and ("tag" in c or "cat-links" in c))
            if t.get_text(strip=True)]

    # Análise ontológica
    analise = analisar_com_ia(texto, contexto=f"{tipo}")

    return {
        "id": url.rstrip("/").split("/")[-1],
        "titulo": titulo,
        "tipo": tipo,
        "data": data,
        "url": url,
        "texto_completo": texto[:8000],
        "links_externos": links_externos,
        "tags": tags,
        "temas": analise.get("temas", []),
        "metodos": analise.get("metodos", []),
        "disciplinas": analise.get("disciplinas", []),
        "palavras_chave": analise.get("palavras_chave", []),
        "projetos": analise.get("projetos", []),
        "instituicoes": analise.get("instituicoes", []),
        "colaboradores": analise.get("colaboradores", []),
        "resumo": analise.get("resumo", ""),
        "autores_detectados": [],  # preenchido na construção da ontologia
    }


def coletar_secao_completa(nome: str, url_base: str, tipo: str,
                            urls_ja_coletadas: set) -> list[dict]:
    """Coleta todos os posts de uma seção com paginação."""
    print(f"\n[...] Coletando {nome}...")
    itens = []
    pagina = 1
    urls_secao = []

    # Coleta todas as URLs da seção
    while True:
        url = url_base if pagina == 1 else f"{url_base}page/{pagina}/"
        soup = buscar(url)
        if not soup:
            break
        artigos = soup.find_all("article")
        if not artigos:
            break
        for art in artigos:
            a = art.find("a", href=True)
            if a and a["href"] not in urls_ja_coletadas and a["href"] not in urls_secao:
                urls_secao.append(a["href"])
        if not soup.find("a", class_=lambda c: c and "next" in c):
            break
        pagina += 1

    print(f"  → {len(urls_secao)} itens encontrados")

    for url in urls_secao:
        item = coletar_post_completo(url, tipo)
        if item:
            itens.append(item)
            urls_ja_coletadas.add(url)
            print(f"    ✓ {item['titulo'][:60]}")

    return itens


# ─────────────────────────────────────────────
# CONSTRUÇÃO DA ONTOLOGIA RICA
# ─────────────────────────────────────────────

def construir_ontologia_rica(pessoas: list, conteudos: list) -> dict:
    print("\n[5/5] Construindo ontologia e mapeando conexões...")

    # Índice de pessoas por nome e slug
    indice_por_slug = {p["id"]: p for p in pessoas}
    indice_por_nome = {}
    for p in pessoas:
        partes = p["nome"].lower().split()
        # Índice por sobrenome e por nome completo
        for i in range(len(partes)):
            chave = " ".join(partes[i:])
            if len(chave) > 3:
                indice_por_nome[chave] = p["id"]

    # Associa posts aos seus autores por URL (posts_urls nos perfis)
    url_para_autores = defaultdict(set)
    for p in pessoas:
        for purl in p.get("posts_urls", []):
            url_para_autores[purl].add(p["id"])

    # Enriquece conteúdos com autores detectados
    for item in conteudos:
        # Autores por URL vinculada ao perfil
        autores = set(url_para_autores.get(item["url"], set()))
        # Autores por menção de nome no texto
        texto_lower = item["texto_completo"].lower()
        for nome_chave, pid in indice_por_nome.items():
            if nome_chave in texto_lower:
                autores.add(pid)
        # Autores mencionados pela IA
        for colab in item.get("colaboradores", []):
            colab_lower = colab.lower()
            for nome_chave, pid in indice_por_nome.items():
                if nome_chave in colab_lower:
                    autores.add(pid)
        item["autores_detectados"] = list(autores)

    # Agrega posts por pesquisador
    posts_por_pessoa = defaultdict(list)
    for item in conteudos:
        for aid in item["autores_detectados"]:
            posts_por_pessoa[aid].append(item["id"])

    for p in pessoas:
        p["posts_ids"] = list(set(posts_por_pessoa.get(p["id"], [])))

    # ── NÓS ──────────────────────────────────

    # Agrega todas as entidades temáticas
    freq_temas = defaultdict(int)
    freq_metodos = defaultdict(int)
    freq_disciplinas = defaultdict(int)
    freq_projetos = defaultdict(int)
    freq_instituicoes = defaultdict(int)

    for p in pessoas:
        for t in p.get("temas", []): freq_temas[t] += 2  # peso maior para pessoa
        for m in p.get("metodos", []): freq_metodos[m] += 2
        for d in p.get("disciplinas", []): freq_disciplinas[d] += 2
        for pr in p.get("projetos", []): freq_projetos[pr] += 3
        for inst in p.get("instituicoes", []): freq_instituicoes[inst] += 1

    for item in conteudos:
        for t in item.get("temas", []): freq_temas[t] += 1
        for m in item.get("metodos", []): freq_metodos[m] += 1
        for d in item.get("disciplinas", []): freq_disciplinas[d] += 1
        for pr in item.get("projetos", []): freq_projetos[pr] += 2
        for inst in item.get("instituicoes", []): freq_instituicoes[inst] += 1

    nos = []
    arestas = []
    arestas_vistas = set()

    def add_aresta(source, target, tipo, **kwargs):
        chave = (tipo, tuple(sorted([str(source), str(target)])))
        if chave not in arestas_vistas:
            arestas_vistas.add(chave)
            arestas.append({"source": source, "target": target, "tipo": tipo, **kwargs})
            return True
        else:
            for e in arestas:
                if e["tipo"] == tipo and set([e["source"], e["target"]]) == {source, target}:
                    e["peso"] = e.get("peso", 1) + 1
            return False

    # Nós: pesquisadores
    for p in pessoas:
        nos.append({
            "id": p["id"], "label": p["nome"], "tipo": "pessoa",
            "cargo": p["cargo"], "grupo": p["grupo"],
            "temas": p.get("temas", []),
            "metodos": p.get("metodos", []),
            "disciplinas": p.get("disciplinas", []),
            "projetos": p.get("projetos", []),
            "palavras_chave": p.get("palavras_chave", []),
            "resumo": p.get("resumo", ""),
            "url": p["url"],
            "n_posts": len(p.get("posts_ids", [])),
            "bio_resumo": p.get("bio_completa", "")[:500],
        })

    # Nós: temas (freq >= 2)
    for tema, freq in freq_temas.items():
        if freq >= 2:
            tid = f"tema_{re.sub(r'[^a-z0-9]', '_', tema.lower())}"
            nos.append({"id": tid, "label": tema, "tipo": "tema", "freq": freq})

    # Nós: projetos relevantes (freq >= 2)
    for proj, freq in freq_projetos.items():
        if freq >= 2 and len(proj) > 3:
            pid = f"proj_{re.sub(r'[^a-z0-9]', '_', proj.lower())[:30]}"
            nos.append({"id": pid, "label": proj, "tipo": "projeto", "freq": freq})

    # Nós: métodos relevantes
    for met, freq in freq_metodos.items():
        if freq >= 2:
            mid = f"met_{re.sub(r'[^a-z0-9]', '_', met.lower())}"
            nos.append({"id": mid, "label": met, "tipo": "metodo", "freq": freq})

    nos_ids = {n["id"] for n in nos}

    # ── ARESTAS ───────────────────────────────

    # Pessoa ↔ tema
    for p in pessoas:
        for tema in p.get("temas", []):
            tid = f"tema_{re.sub(r'[^a-z0-9]', '_', tema.lower())}"
            if tid in nos_ids:
                add_aresta(p["id"], tid, "pessoa_tema", peso=2)

    # Pessoa ↔ método
    for p in pessoas:
        for met in p.get("metodos", []):
            mid = f"met_{re.sub(r'[^a-z0-9]', '_', met.lower())}"
            if mid in nos_ids:
                add_aresta(p["id"], mid, "pessoa_metodo", peso=1)

    # Pessoa ↔ projeto
    for p in pessoas:
        for proj in p.get("projetos", []):
            pid2 = f"proj_{re.sub(r'[^a-z0-9]', '_', proj.lower())[:30]}"
            if pid2 in nos_ids:
                add_aresta(p["id"], pid2, "pessoa_projeto", peso=3)

    # Pessoa ↔ pessoa (temas em comum)
    for i, p1 in enumerate(pessoas):
        for p2 in pessoas[i+1:]:
            t_comuns = set(p1.get("temas", [])) & set(p2.get("temas", []))
            m_comuns = set(p1.get("metodos", [])) & set(p2.get("metodos", []))
            d_comuns = set(p1.get("disciplinas", [])) & set(p2.get("disciplinas", []))
            proj_comuns = set(p1.get("projetos", [])) & set(p2.get("projetos", []))
            peso = len(t_comuns) + len(m_comuns)*2 + len(proj_comuns)*4
            if peso > 0:
                add_aresta(p1["id"], p2["id"], "colaboracao",
                           temas=list(t_comuns),
                           metodos=list(m_comuns),
                           projetos=list(proj_comuns),
                           peso=peso)

    # Pessoa ↔ pessoa (co-aparição em posts)
    for item in conteudos:
        autores = item["autores_detectados"]
        for i, a1 in enumerate(autores):
            for a2 in autores[i+1:]:
                add_aresta(a1, a2, "coautoria", post=item["id"], peso=2)

    # ── TIMELINE ─────────────────────────────
    timeline = sorted(
        [{"id": c["id"], "titulo": c["titulo"], "data": c["data"],
          "tipo": c["tipo"], "temas": c.get("temas", [])[:5],
          "resumo": c.get("resumo", ""), "url": c["url"],
          "autores": c["autores_detectados"]}
         for c in conteudos if c["data"]],
        key=lambda x: x["data"]
    )

    # ── NUVEM DE TEMAS ────────────────────────
    todas_kw = defaultdict(int)
    for p in pessoas:
        for kw in p.get("palavras_chave", []):
            todas_kw[kw.lower()] += 2
    for item in conteudos:
        for kw in item.get("palavras_chave", []):
            todas_kw[kw.lower()] += 1

    nuvem = [{"texto": k, "freq": v}
             for k, v in sorted(todas_kw.items(), key=lambda x: -x[1])
             if len(k) > 2][:80]

    # ── CLUSTERS TEMÁTICOS ───────────────────
    # Agrupa pesquisadores por tema principal
    clusters = defaultdict(list)
    for p in pessoas:
        for tema in p.get("temas", [])[:3]:
            clusters[tema].append(p["id"])

    return {
        "meta": {
            "titulo": "Creative Labour and Critical Futures — Ontologia",
            "url": BASE_URL,
            "n_pessoas": len(pessoas),
            "n_conteudos": len(conteudos),
            "n_nos": len(nos),
            "n_arestas": len(arestas),
            "analise_ia": USA_IA,
        },
        "nos": nos,
        "arestas": arestas,
        "timeline": timeline,
        "nuvem_temas": nuvem,
        "clusters_tematicos": dict(clusters),
        "pessoas": [
            {k: v for k, v in p.items() if k != "bio_completa"}
            for p in pessoas
        ],
        "conteudos": [
            {k: v for k, v in c.items() if k != "texto_completo"}
            for c in conteudos
        ],
    }


# ─────────────────────────────────────────────
# EXECUÇÃO PRINCIPAL
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  CLCF Deep Scraper v2")
    print(f"  Modo: {'IA (Claude API)' if USA_IA else 'Palavras-chave'}")
    print("=" * 55)

    # 1. Pesquisadores (perfis completos)
    pessoas = coletar_todas_pessoas()

    # URLs já coletadas via perfis de pessoas (evita duplicatas)
    urls_coletadas = set()
    for p in pessoas:
        urls_coletadas.update(p.get("posts_urls", []))

    # 2. Seções de conteúdo
    blog     = coletar_secao_completa("Blog",
                   f"{BASE_URL}/category/blog/", "Blog Post", urls_coletadas)
    projects = coletar_secao_completa("Projects",
                   f"{BASE_URL}/category/projects/", "Project", urls_coletadas)
    speakers = coletar_secao_completa("Speaker Series",
                   f"{BASE_URL}/category/speaker-series/", "Speaker Series", urls_coletadas)
    recursos = coletar_secao_completa("Resources",
                   f"{BASE_URL}/category/resources/", "Resource", urls_coletadas)

    # 3. Posts vinculados aos pesquisadores (que não apareceram nas seções)
    print("\n[4/5] Coletando posts individuais vinculados a pesquisadores...")
    posts_pesquisadores = []
    for p in pessoas:
        for purl in p.get("posts_urls", []):
            if purl not in urls_coletadas:
                item = coletar_post_completo(purl, "Blog Post")
                if item:
                    posts_pesquisadores.append(item)
                    urls_coletadas.add(purl)
                    print(f"    ✓ {item['titulo'][:60]}")

    todos_conteudos = blog + projects + speakers + recursos + posts_pesquisadores

    # 4. Ontologia
    ontologia = construir_ontologia_rica(pessoas, todos_conteudos)

    # 5. Salva
    with open("clcf_ontologia.json", "w", encoding="utf-8") as f:
        json.dump(ontologia, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print("  Resumo final")
    print("=" * 55)
    m = ontologia["meta"]
    print(f"  Pesquisadores : {m['n_pessoas']}")
    print(f"  Conteúdos     : {m['n_conteudos']}")
    print(f"  Nós no grafo  : {m['n_nos']}")
    print(f"  Conexões      : {m['n_arestas']}")
    print(f"  Análise IA    : {'Sim' if m['analise_ia'] else 'Não'}")
    print("\n  ✓ clcf_ontologia.json gerado!")
    print("=" * 55)
