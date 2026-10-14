<div align="center">

<img src="assets/tracereview-hero.svg" alt="TraceReview: literature review you can trace" width="100%" />

<br />
<br />

<img src="https://img.shields.io/badge/Status-Active%20Development-20b8aa?style=flat-square" alt="Active development" />
<img src="https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white" alt="React 19" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
<img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />

<br />
<br />

**Discover scientific papers. Inspect source-matched excerpts.**
<br />
**Keep the research workflow auditable.**

<br />

[![Features](https://img.shields.io/badge/Features-172b45?style=flat-square)](#features)
[![Workflow](https://img.shields.io/badge/Workflow-172b45?style=flat-square)](#workflow)
[![Tech stack](https://img.shields.io/badge/Tech%20stack-172b45?style=flat-square)](#tech-stack)
[![Quick start](https://img.shields.io/badge/Quick%20start-20b8aa?style=flat-square)](#quick-start)

</div>

<br />

## Why TraceReview?

> AI-generated literature summaries are useful, but researchers need to inspect the sources behind them.

TraceReview combines **literature discovery**, **AI-assisted reading**, **source-matched excerpts**, and **workflow auditing** in one application, so every claim can be followed back to the paper it came from.

<br />

## Features

<table>
<tr>
<td width="50%" valign="top">

#### 🔎&nbsp; Literature discovery

Search scientific literature across configured providers and deduplicate records.

</td>
<td width="50%" valign="top">

#### 🧠&nbsp; AI-assisted reading

Generate concise study summaries and neutral relevance notes.

</td>
</tr>
<tr>
<td width="50%" valign="top">

#### 🔗&nbsp; Traceable excerpts

Check proposed quotations against source text and fall back to verbatim abstract sentences when needed.

</td>
<td width="50%" valign="top">

#### 📋&nbsp; Auditable workflows

Inspect retrieval, selection, caching, validation, and model-fallback events.

</td>
</tr>
</table>

<br />

## Workflow

From question to report in four steps. Everything inside the highlighted band is written to the audit trail.

```mermaid
flowchart LR
    Q([Research<br/>question]) --> S

    subgraph AUDIT["Audit trail: every step is logged"]
        direction LR
        S[1 · Search] --> R[2 · Rank] --> D[3 · Digest] --> V[4 · Verify]
    end

    V --> O([Paper cards<br/>& report])

    classDef io fill:#172b45,color:#ffffff,stroke:#20b8aa,stroke-width:2px
    classDef step fill:#ffffff,color:#172b45,stroke:#20b8aa,stroke-width:2px
    classDef out fill:#d5f7ef,color:#123d3a,stroke:#20b8aa,stroke-width:2px
    class Q io
    class S,R,D,V step
    class O out
    style AUDIT fill:#e6edf5,color:#24394b,stroke:#8ba2bd,stroke-dasharray:5 5
```

<table>
<tr>
<td width="25%" valign="top">

**1 · Search**

Query configured providers and collect candidate papers.

</td>
<td width="25%" valign="top">

**2 · Rank**

Deduplicate records, then rank them (lexical and deterministic).

</td>
<td width="25%" valign="top">

**3 · Digest**

Generate concise summaries and neutral relevance notes.

</td>
<td width="25%" valign="top">

**4 · Verify**

Check quotes against source text; fall back to verbatim abstract sentences.

</td>
</tr>
</table>

<sub>The audit trail covers retrieval, selection, caching, validation, and model-fallback events.</sub>

<br />

## Tech stack

<table>
<tr>
<td width="33%" valign="top">

**🖥️&nbsp; Frontend**

React · TypeScript · Vite

</td>
<td width="33%" valign="top">

**⚙️&nbsp; Backend**

Python · FastAPI · Pydantic

</td>
<td width="33%" valign="top">

**🤖&nbsp; AI workflow**

LangGraph · LangChain · Groq

</td>
</tr>
<tr>
<td width="33%" valign="top">

**🗄️&nbsp; Database**

PostgreSQL · SQLAlchemy · pgvector

</td>
<td width="33%" valign="top">

**🐳&nbsp; Deployment**

Docker Compose · optional Caddy

</td>
<td width="33%" valign="top">

**✅&nbsp; Quality**

Ruff · mypy · pytest · GitHub Actions

</td>
</tr>
</table>

<br />

## Quick start

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

| Service | URL |
|:--|:--|
| 🌐&nbsp; Web app | http://localhost:5173 |
| 📖&nbsp; API docs | http://localhost:8000/docs |
| 💚&nbsp; Health check | http://localhost:8000/health |

<br />

## Important notes

> [!WARNING]
> TraceReview is under active development. Please keep these limitations in mind:
>
> - Ranking is currently deterministic and lexical; embedding-based ranking is not implemented.
> - Excerpt matching checks wording, not scientific truth.
> - Research runs cannot resume after an API restart.

<br />

---

<div align="center">

**Discover carefully. Read critically. Trace every excerpt.**

<sub>Built for researchers who want more transparent literature workflows.</sub>

</div>
