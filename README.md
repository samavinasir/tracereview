# TraceReview

**Literature review you can trace**

TraceReview helps researchers find a focused set of papers and read what each source says. Enter a research question to retrieve and rank records, then review paper cards with bibliographic details, a short AI-generated study summary, checked verbatim excerpts, and the abstract's final sentence copied from the source record. TraceReview does not decide whether a paper's conclusions are true and does not produce scientific verdicts.

## Features

- Searches PubMed and Europe PMC by default, with optional OpenAlex, Semantic Scholar, and Crossref adapters. Crossref is available but is not used by default.
- Deduplicates records using PMID, DOI, or normalized title, keeps the record with the more complete abstract, and retains alternate provider links.
- Filters theses and dissertations and short abstracts before ranking. The default run cap is 10 unique records and the UI shows up to 10 paper cards.
- Produces a concise reading aid for each selected record: what the study did, a neutral retrieval note, up to two source-matched key-finding excerpts, and the abstract's final sentence copied in code.
- Cleans HTML/XML markup before displaying source text and validating quotes. If model-proposed quotes do not match, it selects relevant abstract sentences verbatim.
- Caches successful paper digests in PostgreSQL so repeated questions can reuse work when the paper text, question, and prompt version match.
- Shows selection, provider, cache, quote-validation, and model-fallback events in an inspectable audit trail.
- Labels records whose named organism differs from the organism found in the research question or plan.

AI summaries and retrieval notes are reading aids and may miss nuance. Read the linked paper and decide what the findings mean.

## Tech stack

| Area | Technology |
| --- | --- |
| Frontend | React 19, TypeScript, Vite 6, Lucide React |
| API | Python 3.11+, FastAPI, Pydantic Settings, Uvicorn |
| Workflow | LangGraph; LangChain's Groq integration for model access |
| Language models | Groq GPT-OSS by default; optional OpenRouter free-router fallback |
| Research sources | PubMed/NCBI, Europe PMC, OpenAlex, Semantic Scholar, Crossref; UniProt adapter available |
| Database | PostgreSQL 16 with pgvector, SQLAlchemy asyncio, asyncpg |
| Containers and proxy | Docker Compose; optional Caddy HTTPS deployment |
| CI | GitHub Actions for lint, typing, tests, and image build |

The current ranking is deterministic lexical ranking. pgvector is installed and the schema can store embeddings, but the current workflow does not download or use an embedding model.

## Run locally with Docker

1. Copy `.env.example` to `.env`.
2. Set `GROQ_API_KEY` and a database password. Keep `POSTGRES_PASSWORD`, `DATABASE_URL`, and `DATABASE_URL_DOCKER` in sync; the Docker URL uses `db` as its host. `OPENROUTER_API_KEY` is optional. NCBI, contact-email, and Semantic Scholar credentials are also optional.
3. Build and start the app:

   ```powershell
   docker compose up --build -d
   ```

4. Open the UI at [http://localhost:5173](http://localhost:5173). The API health check is [http://localhost:8000/health](http://localhost:8000/health), and interactive API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).

To see service state and logs:

```powershell
docker compose ps
docker compose logs -f api frontend
```

The database is stored in the `research_pgdata` Docker volume. `docker compose down` preserves it; avoid `docker compose down -v` unless you intend to delete local database data.

## Configuration

Configuration is read from environment variables (normally in `.env`). `.env` is excluded from Git and the Docker build context. See `.env.example` for all available settings, including:

- `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_REASONING_EFFORT`, and `GROQ_TPM_BUDGET` for Groq.
- `OPENROUTER_API_KEY` and `OPENROUTER_FALLBACK_MODEL` for one independent digest fallback attempt.
- `NCBI_API_KEY`, `CONTACT_EMAIL`, and `SEMANTIC_SCHOLAR_API_KEY` for optional source-provider access.
- `MAX_RECORDS_PER_RESEARCH_RUN`, `MAX_PAPERS_PER_REVIEW`, `MIN_ABSTRACT_CHARS`, and `PAPER_DIGEST_BATCH_SIZE` for retrieval and review limits.
- `DATABASE_URL`, `DATABASE_URL_DOCKER`, and `POSTGRES_PASSWORD` for database access.

Never commit `.env` or put provider credentials in screenshots, logs, or public issues. URL-encode special characters in passwords embedded in database URLs.

## Research workflow

A run plans search queries, retrieves and deduplicates source records, selects a small paper set, digests selected papers in batches, and builds a compact list of authors' abstract conclusions. It can expand retrieval once when too few cards are available, but it does not broaden the search just because a model failed to summarize records. Successful summaries are cached; failed summaries remain visibly unreviewed and do not become scientific findings. Runs are marked complete when at least one paper card is ready and failed when there are no cards to show.

Search requests use bounded concurrency; PubMed calls are paced separately. Groq digest calls use a process-local concurrency limit and token budget. Long provider cooldowns are not retried in a loop. If configured, OpenRouter is tried once as a fallback. If both providers fail, the run records the issue and continues to its final report with whatever cards are available.

Retrieved titles, abstracts, and other provider fields are untrusted source data. They are displayed as text and are not treated as instructions.

## API overview

- `GET /health` — API health.
- `POST /research` — start a run; returns a run ID immediately.
- `GET /research/{id}` and `GET /research/{id}/status` — run status and progress.
- `GET /research/{id}/plan` — objective and search plan.
- `GET /research/{id}/sources` — retrieved records and attached paper summaries.
- `GET /research/{id}/report` — report JSON; use `?format=markdown` for a Markdown download.
- `GET /research/{id}/audit` — structured workflow events and provider/model diagnostics.

Legacy evidence and claims endpoints remain for compatibility with older stored runs. New research runs use paper cards and do not generate or verify claims.

## Local development

Backend setup and checks (PowerShell, from the repository root):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ruff check src tests
mypy src
pytest -q
```

Run the API in one terminal:

```powershell
uvicorn auditable_research.api:app --app-dir src --reload
```

Run the frontend in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

The frontend dev server runs at [http://localhost:5173](http://localhost:5173). Set `VITE_API_BASE_URL` if the API is hosted at a different address.

## Production deployment

`docker-compose.prod.yml` adds Caddy as an HTTPS reverse proxy. It expects a Linux VM with Docker Compose v2.24 or newer, DNS records for the UI and API domains pointing to the VM, and inbound TCP ports 80 and 443 open. Configure `UI_DOMAIN`, `API_DOMAIN`, strong database credentials, and model credentials in the VM's `.env`, then run:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The initial deployment targets one API container. Background research work and rate limits are process-local, so use a durable job queue and a shared limiter before scaling to multiple API replicas. Back up the PostgreSQL volume before upgrades and migrations.

## License

No license has been selected yet. Add a `LICENSE` file before describing this repository as open source or allowing reuse by others.
