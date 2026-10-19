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
- Ranks records by overlap with the words in the research question, and records why an item was selected or excluded.
- Offers discipline and review-goal options, year/source/full-text filters, and a paper-first screening view with saved include/exclude decisions and reviewer notes.
- Shows source-linked evidence excerpts alongside the paper and exports a Markdown digest.
- Separates the spacious new-search home, research Results workspace, and live Run details page. Results is the default view for completed runs, Papers contains the detailed paper list, and run progress, search plan, and audit details have their own page. Export remains available from the research workspace.

AI summaries and retrieval notes are reading aids and may miss nuance. Read the linked paper and decide what the findings mean.

## Tech stack

| Area | Technology |
| --- | --- |
| Web app | Django 5, server-rendered HTML templates, CSS, browser JavaScript |
| Existing API compatibility | FastAPI, Pydantic Settings, Uvicorn |
| Workflow | LangGraph; LangChain's Groq integration for model access |
| Language models | Groq GPT-OSS by default; optional OpenRouter free-router fallback |
| Research sources | PubMed/NCBI, Europe PMC, OpenAlex, Semantic Scholar, Crossref; UniProt adapter available |
| Database | PostgreSQL 16, SQLAlchemy asyncio, asyncpg |
| CI | GitHub Actions for lint, typing, and tests |

The current ranking is deterministic lexical ranking.

## Run locally

1. Copy `.env.example` to `.env`.
2. Set a local `DATABASE_URL`, `DJANGO_SECRET_KEY`, and `USER_KEYS_ENCRYPTION_KEY`. Users add their own provider keys after creating an account.
3. Install PostgreSQL 16 and create a database that matches `DATABASE_URL`.
4. Start the Django app as described under [Local development](#local-development).
5. Open the search home at [http://127.0.0.1:8000](http://127.0.0.1:8000). Each research run opens a dedicated Results page; use Run details for its live plan and audit trace. The health check is [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health); legacy FastAPI API documentation remains at `/docs` when running that compatibility server.

## Configuration

Application configuration is read from environment variables (normally in `.env`). `.env` is excluded from Git. Django users manage provider keys in their account settings; keys are encrypted at rest and are never written into research-run records. See `.env.example` for all settings, including:

- `GROQ_MODEL`, `GROQ_REASONING_EFFORT`, and `GROQ_TPM_BUDGET` for model behavior.
- `USER_KEYS_ENCRYPTION_KEY` to encrypt provider API keys saved by individual accounts. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep this value private and stable: changing it makes existing saved keys unreadable.
- The legacy FastAPI compatibility server can still use `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `NCBI_API_KEY`, `CONTACT_EMAIL`, and `SEMANTIC_SCHOLAR_API_KEY` from its environment; the Django interface uses the signed-in user's saved keys instead.
- `MAX_RECORDS_PER_RESEARCH_RUN`, `MAX_PAPERS_PER_REVIEW`, `MIN_ABSTRACT_CHARS`, and `PAPER_DIGEST_BATCH_SIZE` for retrieval and review limits.
- `DATABASE_URL` for local PostgreSQL access.
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, and `DJANGO_ALLOWED_HOSTS` for Django. Set a private random secret and `DJANGO_DEBUG=false` in production.

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

Install PostgreSQL 16, then create a database and user that match `DATABASE_URL` in `.env`:

```powershell
psql -U postgres -c "CREATE USER research WITH PASSWORD 'change_me_url_encode_if_needed';"
psql -U postgres -c "CREATE DATABASE research OWNER research;"
```

Backend setup (PowerShell, from the repository root):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python manage.py migrate
python manage.py createsuperuser
```

Create an account from the home page, then open **API keys** and save a Groq key (required to run research). OpenRouter, NCBI, and Semantic Scholar keys are optional. Each user's runs are private to that account.

Run the Django ASGI web app (the persistent ASGI loop keeps background research tasks running):

```powershell
uvicorn tracereview_web.asgi:application --app-dir src --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the TraceReview interface or [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin) for Django admin. Django serves the HTML, CSS, and browser JavaScript from one origin; no separate Vite server is needed.

Existing SQLAlchemy tables and research history are retained. The Django admin initially exposes existing research runs as read-only records. The old FastAPI server remains available for compatibility while clients transition. For production, run `python manage.py collectstatic --noinput` during deployment; WhiteNoise serves the collected files.

The Django interface uses the built-in templates, CSS, and browser JavaScript; it does not require a separate frontend dev server.

## Production notes

Rate limiting is per client IP. Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` so uvicorn reads the real client address from `X-Forwarded-For`. If you expose the API directly, leave that unset or the header could be spoofed.

Research runs execute inside the API process. If the API restarts mid-run, the run cannot continue, so on startup any run still marked `queued` or `running` is marked `failed` with an explanatory message, and you can simply start it again.

Background research work and rate limits are process-local, so use a durable job queue and a shared limiter before scaling to multiple web replicas. Back up PostgreSQL before upgrades and migrations. Django admin uses the PostgreSQL connection defined by `DATABASE_URL` and needs the standard `python manage.py migrate` setup for Django's own auth and session tables.

For a Vercel deployment, set `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`, `CORS_ORIGINS` (also used as trusted CSRF origins), and one stable `USER_KEYS_ENCRYPTION_KEY`. Do not add provider API keys as shared Vercel variables for the Django interface; each signed-in user saves their own keys under API keys. Vercel functions have a maximum execution duration, so move the current in-process `asyncio.create_task` workflow to a durable queue and worker before relying on long research runs in production.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
