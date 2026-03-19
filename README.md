# CLCF — Ontologia Completa (Site + Scholar + IA)

Combina 3 fontes para cada pesquisador:
- **Site CLCF** — bio, cargo, posts, projetos
- **Google Scholar** — publicações, citações, co-autores, áreas
- **Claude API** — análise ontológica profunda

## Configurar segredos (Settings → Secrets → Actions)

| Nome | Valor |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API Claude (sk-ant-...) |

## Rodar

Actions → CLCF Ontologia → Run workflow

⚠️ O scraper pode demorar 30–90 minutos por causa dos delays do Scholar.
