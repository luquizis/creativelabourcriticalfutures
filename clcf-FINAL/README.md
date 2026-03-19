# CLCF — Constelação de Pesquisa

Ontologia interativa do site [Creative Labour and Critical Futures](https://creativelabourcriticalfutures.ca).

## Arquivos

| Arquivo | Função |
|---|---|
| `scraper_profundo.py` | Raspa todo o site e gera `clcf_ontologia.json` |
| `dashboard.html` | Dashboard interativo (grafo, timeline, nuvem) |
| `.github/workflows/ontologia.yml` | Roda o scraper e publica no GitHub Pages |

## Como usar

1. Ative o GitHub Pages: **Settings → Pages → Source → GitHub Actions**
2. Vá em **Actions → CLCF Ontologia → Run workflow**
3. Acesse: `https://SEU_USUARIO.github.io/NOME_DO_REPOSITORIO`
