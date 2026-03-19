"""
CLCF Deep Scraper + Ontologia
==============================
Raspa TODO o site e gera clcf_ontologia.json pronto para o dashboard.

Dependências:
  pip install requests beautifulsoup4 lxml

Uso:
  python scraper_profundo.py
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import re
from collections import defaultdict

BASE_URL = "https://creativelabourcriticalfutures.ca"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Palavras-chave temáticas para extração automática
TEMAS_GLOBAIS = [
    "artificial intelligence", "AI", "machine learning", "automation",
    "creative labour", "creative work", "creative workers", "creative industries",
    "digital labour", "platform labour", "gig economy", "gig work",
    "race", "racism", "racialized", "anti-racism", "Black", "Indigenous",
    "gender", "feminist", "queer", "LGBTQ", "women",
    "colonialism", "decolonial", "colonial", "postcolonial",
    "music", "photography", "film", "visual art", "media",
    "platform", "social media", "algorithm", "data",
    "labour rights", "worker rights", "union", "organizing",
    "ethics", "critical theory", "research-creation",
    "geopolitics", "global south", "diaspora",
    "disability", "accessibility", "care work",
]

# Tipos de trabalho para categorização
TIPOS_TRABALHO = {
    "blog": "Blog Post",
    "projects": "Project",
    "speaker-series": "Speaker Series",
    "resources": "Resource",
    "people": "Person Profile",
}


# ─────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────

def buscar(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        time.sleep(1.2)  # respeita o servidor
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"  ✗ {url} → {e}")
        return None


def extrair_texto_limpo(soup: BeautifulSoup) -> str:
    """Remove scripts, styles e retorna só o texto visível."""
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def extrair_temas(texto: str) -> list[str]:
    """Detecta temas presentes no texto."""
    texto_lower = texto.lower()
    return sorted({
        tema for tema in TEMAS_GLOBAIS
        if tema.lower() in texto_lower
    })


def detectar_tipo(url: str) -> str:
    for chave, tipo in TIPOS_TRABALHO.items():
        if f"/{chave}/" in url or f"/category/{chave}" in url:
            return tipo
    return "Page"


def coletar_links_paginados(url_base: str) -> list[str]:
    """Coleta todos os links de posts/items navegando pela paginação."""
    links = []
    pagina = 1
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
            if a and BASE_URL in a["href"] and a["href"] not in links:
                links.append(a["href"])
        if not soup.find("a", class_=lambda c: c and "next" in c):
            break
        pagina += 1
    return links


# ─────────────────────────────────────────────
# COLETA: PESSOAS
# ─────────────────────────────────────────────

def coletar_pessoas() -> list[dict]:
    print("\n[1/5] Coletando perfis de pesquisadores...")
    pessoas = []

    soup_lista = buscar(f"{BASE_URL}/people/")
    if not soup_lista:
        return pessoas

    # Coleta todos os links de perfis individuais
    links_perfis = []
    for a in soup_lista.find_all("a", href=True):
        href = a["href"]
        if "/people/" in href and href != f"{BASE_URL}/people/" and href not in links_perfis:
            if href.startswith(BASE_URL):
                links_perfis.append(href)

    # Detecta papel (Operations Team vs Researcher)
    grupos = {}
    secoes = soup_lista.find_all("h2")
    for secao in secoes:
        papel = secao.get_text(strip=True)
        bloco = secao.find_next("ul")
        if bloco:
            for a in bloco.find_all("a", href=True):
                grupos[a["href"]] = papel

    print(f"  → {len(links_perfis)} perfis encontrados")

    for url in links_perfis:
        soup = buscar(url)
        if not soup:
            continue

        # Nome e cargo
        nome_el = soup.find("h1") or soup.find("h2")
        nome = nome_el.get_text(strip=True) if nome_el else url.split("/")[-2].replace("-", " ").title()

        cargo_el = soup.find(class_=lambda c: c and ("title" in c or "role" in c or "position" in c))
        cargo = cargo_el.get_text(strip=True) if cargo_el else ""

        # Bio completa — pega o conteúdo principal
        content = soup.find("div", class_=lambda c: c and ("entry" in c or "content" in c or "post" in c))
        if not content:
            content = soup.find("main") or soup.find("article")
        bio = content.get_text(separator=" ", strip=True) if content else ""
        bio = " ".join(bio.split())[:3000]  # limita a 3000 chars

        # Temas identificados na bio
        temas = extrair_temas(bio)

        # Posts associados a essa pessoa (menção do nome em outros conteúdos)
        slug = url.rstrip("/").split("/")[-1]

        pessoas.append({
            "id": slug,
            "nome": nome,
            "cargo": cargo,
            "grupo": grupos.get(url, "CLCF Researcher"),
            "url": url,
            "bio": bio,
            "temas": temas,
            "posts_autor": [],       # preenchido depois
            "coautores": [],         # preenchido depois
        })
        print(f"    ✓ {nome}")

    return pessoas


# ─────────────────────────────────────────────
# COLETA: CONTEÚDO (BLOG, PROJECTS, SPEAKER, RESOURCES)
# ─────────────────────────────────────────────

def coletar_secao(nome: str, url_categoria: str, tipo: str) -> list[dict]:
    print(f"\n[...] Coletando {nome}...")
    itens = []
    links = coletar_links_paginados(url_categoria)
    print(f"  → {len(links)} itens encontrados")

    for url in links:
        soup = buscar(url)
        if not soup:
            continue

        # Título
        titulo_el = soup.find("h1") or soup.find("h2", class_=lambda c: c and "title" in c)
        titulo = titulo_el.get_text(strip=True) if titulo_el else "Sem título"

        # Data
        data_el = soup.find("time") or soup.find(class_=lambda c: c and "date" in c)
        data = data_el.get_text(strip=True) if data_el else ""
        if data_el and data_el.get("datetime"):
            data = data_el["datetime"][:10]

        # Conteúdo completo
        content = soup.find("div", class_=lambda c: c and ("entry-content" in c or "post-content" in c))
        if not content:
            content = soup.find("article") or soup.find("main")
        texto = content.get_text(separator=" ", strip=True) if content else ""
        texto = " ".join(texto.split())

        # Autores mencionados (nomes dos pesquisadores no texto)
        autores_mencionados = []

        # Categorias/tags
        tags_els = soup.find_all(class_=lambda c: c and ("tag" in c or "cat-links" in c))
        tags = [t.get_text(strip=True) for t in tags_els if t.get_text(strip=True)]

        # Temas
        temas = extrair_temas(texto)

        itens.append({
            "id": url.rstrip("/").split("/")[-1],
            "titulo": titulo,
            "tipo": tipo,
            "data": data,
            "url": url,
            "texto": texto[:5000],
            "temas": temas,
            "tags": tags,
            "autores": autores_mencionados,
        })
        print(f"    ✓ {titulo[:60]}")

    return itens


# ─────────────────────────────────────────────
# CONSTRUÇÃO DA ONTOLOGIA
# ─────────────────────────────────────────────

def construir_ontologia(pessoas: list, conteudos: list) -> dict:
    print("\n[5/5] Construindo ontologia e conexões...")

    # Índice de pessoas por nome (para detectar menções)
    indice_nomes = {}
    for p in pessoas:
        partes = p["nome"].lower().split()
        for i in range(len(partes)):
            chave = " ".join(partes[i:])
            if len(chave) > 3:
                indice_nomes[chave] = p["id"]
        indice_nomes[p["id"]] = p["id"]

    # Associa conteúdos a pesquisadores (por menção de nome)
    autor_para_posts = defaultdict(list)
    for item in conteudos:
        texto_lower = item["texto"].lower()
        autores_encontrados = set()
        for nome_chave, pid in indice_nomes.items():
            if nome_chave in texto_lower:
                autores_encontrados.add(pid)
                autor_para_posts[pid].append(item["id"])
        item["autores"] = list(autores_encontrados)

    # Atualiza posts_autor nas pessoas
    for p in pessoas:
        p["posts_autor"] = list(set(autor_para_posts.get(p["id"], [])))

    # Conexões entre pesquisadores (temas em comum + co-aparição em posts)
    nos = []
    arestas = []
    arestas_vistas = set()

    # Agrupa temas para calcular frequência global
    freq_temas = defaultdict(int)
    for p in pessoas:
        for t in p["temas"]:
            freq_temas[t] += 1
    for item in conteudos:
        for t in item["temas"]:
            freq_temas[t] += 1

    # Nós: pesquisadores
    for p in pessoas:
        nos.append({
            "id": p["id"],
            "label": p["nome"],
            "tipo": "pessoa",
            "cargo": p["cargo"],
            "grupo": p["grupo"],
            "temas": p["temas"],
            "url": p["url"],
            "n_posts": len(p["posts_autor"]),
            "bio_resumo": p["bio"][:400],
        })

    # Nós: temas mais relevantes
    temas_relevantes = [t for t, f in freq_temas.items() if f >= 2]
    for tema in temas_relevantes:
        nos.append({
            "id": f"tema_{tema.replace(' ', '_')}",
            "label": tema,
            "tipo": "tema",
            "freq": freq_temas[tema],
        })

    # Arestas: pessoa ↔ tema
    for p in pessoas:
        for tema in p["temas"]:
            if tema in temas_relevantes:
                tid = f"tema_{tema.replace(' ', '_')}"
                arestas.append({
                    "source": p["id"],
                    "target": tid,
                    "tipo": "tema_comum",
                    "peso": 1,
                })

    # Arestas: pessoa ↔ pessoa (temas em comum)
    for i, p1 in enumerate(pessoas):
        for p2 in pessoas[i+1:]:
            temas_comuns = set(p1["temas"]) & set(p2["temas"])
            if temas_comuns:
                chave = tuple(sorted([p1["id"], p2["id"]]))
                if chave not in arestas_vistas:
                    arestas_vistas.add(chave)
                    arestas.append({
                        "source": p1["id"],
                        "target": p2["id"],
                        "tipo": "temas_comuns",
                        "temas": list(temas_comuns),
                        "peso": len(temas_comuns),
                    })

    # Arestas: pessoa ↔ pessoa (co-aparição em posts)
    post_para_autores = defaultdict(list)
    for item in conteudos:
        for autor_id in item["autores"]:
            post_para_autores[item["id"]].append(autor_id)

    for post_id, autores in post_para_autores.items():
        for i, a1 in enumerate(autores):
            for a2 in autores[i+1:]:
                chave = ("coautoria", tuple(sorted([a1, a2])))
                if chave not in arestas_vistas:
                    arestas_vistas.add(chave)
                    arestas.append({
                        "source": a1,
                        "target": a2,
                        "tipo": "coautoria",
                        "posts": [post_id],
                        "peso": 2,
                    })
                else:
                    # incrementa peso se já existe
                    for e in arestas:
                        if e.get("tipo") == "coautoria" and set([e["source"], e["target"]]) == {a1, a2}:
                            e["peso"] += 1
                            e["posts"].append(post_id)

    # Timeline
    timeline = sorted(
        [{"id": c["id"], "titulo": c["titulo"], "data": c["data"],
          "tipo": c["tipo"], "temas": c["temas"], "url": c["url"]}
         for c in conteudos if c["data"]],
        key=lambda x: x["data"]
    )

    # Frequência de temas para nuvem
    nuvem = [{"texto": t, "freq": f} for t, f in
             sorted(freq_temas.items(), key=lambda x: -x[1])[:60]]

    ontologia = {
        "meta": {
            "titulo": "Creative Labour and Critical Futures — Ontologia",
            "url": BASE_URL,
            "n_pessoas": len(pessoas),
            "n_conteudos": len(conteudos),
            "n_temas": len(freq_temas),
            "n_conexoes": len(arestas),
        },
        "nos": nos,
        "arestas": arestas,
        "conteudos": [
            {k: v for k, v in c.items() if k != "texto"}  # remove texto longo do grafo
            for c in conteudos
        ],
        "timeline": timeline,
        "nuvem_temas": nuvem,
        "pessoas": pessoas,
    }

    return ontologia


# ─────────────────────────────────────────────
# EXECUÇÃO PRINCIPAL
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  CLCF Deep Scraper + Ontologia")
    print("=" * 55)

    # 1. Pessoas
    pessoas = coletar_pessoas()

    # 2. Conteúdos
    blog     = coletar_secao("Blog",          f"{BASE_URL}/category/blog/",          "Blog Post")
    projects = coletar_secao("Projects",      f"{BASE_URL}/category/projects/",      "Project")
    speakers = coletar_secao("Speaker Series",f"{BASE_URL}/category/speaker-series/","Speaker Series")
    recursos = coletar_secao("Resources",     f"{BASE_URL}/category/resources/",     "Resource")

    todos_conteudos = blog + projects + speakers + recursos

    # 3. Ontologia
    ontologia = construir_ontologia(pessoas, todos_conteudos)

    # 4. Salva JSON
    with open("clcf_ontologia.json", "w", encoding="utf-8") as f:
        json.dump(ontologia, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print("  Resumo")
    print("=" * 55)
    m = ontologia["meta"]
    print(f"  Pesquisadores : {m['n_pessoas']}")
    print(f"  Conteúdos     : {m['n_conteudos']}")
    print(f"  Temas únicos  : {m['n_temas']}")
    print(f"  Conexões      : {m['n_conexoes']}")
    print("\n  ✓ clcf_ontologia.json gerado!")
    print("=" * 55)
