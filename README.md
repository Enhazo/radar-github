# Radar GitHub 📡

Projeto pessoal de portfólio, fora das matérias escolares: um painel para explorar repositórios open source e acompanhar a evolução de métricas públicas. Pesquise por linguagem, tema ou organização; adicione projetos ao radar; atualize amostras, compare mudanças de estrelas e exporte CSV.

## Por que este projeto

A API REST pública do GitHub oferece os números atuais, mas não expõe diretamente um histórico completo de estrelas por repositório; este app coleta suas próprias amostras a partir do momento do monitoramento. Esse histórico local começa ao adicionar ou atualizar um projeto; não é uma série retroativa. Isso demonstra integração, persistência e análise temporal.

## O que demonstra

- Integração com a API REST do GitHub, paginação limitada e tratamento de 404/limites.
- API própria com FastAPI, validação e OpenAPI.
- Modelagem relacional de repositórios e snapshots históricos com SQLAlchemy.
- Atualização idempotente, exportação CSV compatível com planilhas e interface responsiva.
- Token opcional via ambiente, nunca armazenado no banco nem no repositório.

## Executar

Requer Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Abra <http://localhost:8000>; documentação em <http://localhost:8000/docs>. O banco local SQLite `radar.db` é criado automaticamente.

A API não precisa de token para dados públicos. Para ampliar o limite de requisições, defina `GITHUB_TOKEN` no ambiente com um token de **somente leitura de dados públicos**. Não cole tokens no código ou em commits. Sem token, a API pública limita requisições por IP (documentação atual: 60 requisições por hora para chamadas não autenticadas); os limites podem mudar.

## PostgreSQL no Docker Compose

```bash
POSTGRES_PASSWORD='senha-local-forte' docker compose up --build
```

Abra <http://localhost:8002>. Para uma cota maior, defina `GITHUB_TOKEN` no ambiente do Compose. Docker Compose não foi executado no ambiente de autoria.

## Testes

```bash
pytest -q
```

As chamadas externas são simuladas nos testes, sem token nem acesso à rede. A coleta real requer internet. Instalação de runtime: `python -m pip install -r requirements.txt`.

## API

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/search?q=...` | Busca repositórios públicos |
| POST | `/api/repos` | Consulta e começa a monitorar `owner/name` |
| GET | `/api/repos` | Lista projetos e amostras locais |
| POST | `/api/repos/{id}/refresh` | Coleta uma nova amostra |
| DELETE | `/api/repos/{id}` | Remove projeto e histórico local |
| GET | `/api/export.csv` | Exporta métricas atuais |

## Limitações e privacidade

A coleta de histórico é manual (ao adicionar/atualizar), não um serviço agendado 24/7; métricas indicam contagens públicas, não qualidade ou popularidade absoluta. Use de forma respeitosa aos limites da API. Nenhuma conta GitHub é conectada e nenhuma credencial é exigida. Os repositórios monitorados ficam no banco local, compartilhado pela instância. Esta versão é uma demonstração local; antes de abrir uma hospedagem pública, implemente autenticação, limites de uso e proteção adequada para escrita/exclusão de dados.

## Licença

MIT. Nomes, marcas e conteúdo de terceiros permanecem sob os termos de seus respectivos titulares.
