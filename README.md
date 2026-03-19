# CLCF — Constelação de Pesquisa v2

Ontologia interativa do site [Creative Labour and Critical Futures](https://creativelabourcriticalfutures.ca).

## Arquivos

| Arquivo | Função |
|---|---|
| `scraper_profundo.py` | Raspa todo o site e gera `clcf_ontologia.json` |
| `dashboard.html` | Dashboard interativo (grafo, timeline, nuvem) |
| `.github/workflows/ontologia.yml` | Roda o scraper e publica no GitHub Pages |

## Como usar com IA (recomendado)

1. Gere uma chave em [console.anthropic.com](https://console.anthropic.com)
2. No repositório: **Settings → Secrets → New repository secret**
   - Nome: `ANTHROPIC_API_KEY`
   - Valor: sua chave
3. Ative o GitHub Pages: **Settings → Pages → Source → GitHub Actions**
4. Rode: **Actions → CLCF Ontologia → Run workflow**

## Sem IA

Funciona também sem a chave — usa extração por palavras-chave.
