<div align="center">

<img src="assets/tracereview-hero.svg" alt="TraceReview: literature review you can trace" width="100%" />

<br />
<br />

<img src="https://img.shields.io/badge/Status-Active%20Development-20b8aa?style=flat-square" alt="Active development" />
<img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
<img src="https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white" alt="React 19" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
<img src="https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph" />
<img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
<!-- Add once a LICENSE file exists (adjust the license name):
<img src="https://img.shields.io/badge/License-MIT-20b8aa?style=flat-square" alt="License" />
-->
<!-- CI badge: confirm the workflow filename in .github/workflows/ first
<a href="https://github.com/samavinasir/tracereview/actions"><img src="https://github.com/samavinasir/tracereview/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
-->

<br />
<br />

**Discover scientific papers. Inspect source-matched excerpts.**
<br />
**Keep the research 
 auditable.**

<br />

[![Features](https://img.shields.io/badge/Features-172b45?style=for-the-badge)](#features)
[![Workflow](https://img.shields.io/badge/Workflow-172b45?style=for-the-badge)](#workflow)
[![Quick start](https://img.shields.io/badge/Quick%20start-172b45?style=for-the-badge)](#quick-start)
[![Configuration](https://img.shields.io/badge/Configuration-172b45?style=for-the-badge)](#configuration)
[![Roadmap](https://img.shields.io/badge/Roadmap-172b45?style=for-the-badge)](#roadmap)

</div>

<br />

<a name="why"></a>
<img src="assets/banners/01-why-tracereview.svg" alt="01 / Overview" width="100%" />

> AI-generated literature summaries are useful, but researchers need to inspect the sources behind them.

TraceReview combines **literature discovery**, **AI-assisted reading**, **source-matched excerpts**, and **workflow auditing** in one application, so every claim can be followed back to the paper it came from.

<br />

<!--
## Screenshots

Add a real UI screenshot or short GIF here: a search, a paper card, and the audit trail.
This is the single biggest credibility boost for the page.

<div align="center">
<img src="assets/screenshot-search.png" alt="Search and paper cards" width="49%" />
<img src="assets/screenshot-audit.png" alt="Audit trail view" width="49%" />
</div>

<br />
-->

<a name="features"></a>
<img src="assets/features.svg" alt="02 / Features" width="100%" />

<br />

<a name="workflow"></a>
<img src="assets/workflow.svg" alt="03 / Workflow" width="100%" />

<br />

<a name="tech-stack"></a>
<img src="assets/banners/04-tech-stack.svg" alt="04 / Tech stack" width="100%" />

<a name="tech-stack"></a>
<img src="assets/tech-stack.svg" alt="04 / Tech stack" width="100%" />

<br />

<a name="quick-start"></a>
<img src="assets/banners/05-quick-start.svg" alt="05 / Quick start" width="100%" />

**Prerequisites:** [Docker](https://docs.docker.com/get-docker/) with Docker Compose, and a [Groq API key](https://console.groq.com/).

**1. Clone the repository**

```bash
git clone https://github.com/samavinasir/tracereview.git
cd tracereview
```

**2. Configure the environment**

Copy `.env.example` to `.env`, then set `GROQ_API_KEY` and your database password.

```bash
cp .env.example .env
```

**3. Start everything**

```bash
docker compose up --build -d
```

**4. Open the app**

- 🌐&nbsp; **Web app:** http://localhost:5173
- 📖&nbsp; **API docs:** http://localhost:8000/docs
- 💚&nbsp; **Health check:** http://localhost:8000/health

<br />

<a name="configuration"></a>
<img src="assets/banners/06-configuration.svg" alt="06 / Configuration" width="100%" />

Settings live in `.env` (start from `.env.example`).

| Variable | Required | Purpose |
|:--|:--:|:--|
| `GROQ_API_KEY` | Yes | API key for the Groq-hosted models used for summaries and excerpt selection. |
| *Database password* | Yes | Password for the PostgreSQL container. <!-- replace with the exact variable name from .env.example --> |

<br />

<a name="development"></a>
<img src="assets/banners/07-development.svg" alt="07 / Development" width="100%" />

```bash
# Lint and format check
ruff check .

# Type checking
mypy src

# Tests
pytest
```

<!-- Add the frontend commands too, e.g. cd frontend && npm install && npm run dev -->

For production, use `docker-compose.prod.yml` (with the optional Caddy reverse proxy).

<br />

<a name="important-notes"></a>
<img src="assets/banners/08-important-notes.svg" alt="08 / Important notes" width="100%" />

> [!WARNING]
> TraceReview is under active development. Please keep these limitations in mind:
>
> - Ranking is currently deterministic and lexical; embedding-based ranking is not implemented.
> - Excerpt matching checks wording, not scientific truth.
> - Research runs cannot resume after an API restart.

<br />

<a name="roadmap"></a>
<img src="assets/banners/09-what-s-next.svg" alt="09 / Roadmap" width="100%" />

- [ ] Embedding-based ranking (pgvector is already part of the stack)
- [ ] Resumable research runs that survive an API restart
- [ ] Exportable reports (Markdown / PDF)
- [ ] Additional literature providers

<br />

<a name="license"></a>
<img src="assets/banners/10-license.svg" alt="10 / License" width="100%" />

<!-- Add a LICENSE file first (MIT or Apache-2.0 are common), then state it here. -->
See [LICENSE](LICENSE) for details.

<br />

---

<div align="center">

**Discover carefully. Read critically. Trace every excerpt.**

<sub>Built for researchers who want more transparent literature workflows.</sub>

</div>