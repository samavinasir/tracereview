<div align="center">

<!-- BREADCRUMB / BRAND HEADER -->
<p align="center">
  <img src="https://raw.githubusercontent.com/samavinasir/tracereview/main/assets/banner.png" alt="TraceReview Banner" width="100%" style="border-radius: 12px; margin-bottom: 20px;" />
</p>

# 🔬 TraceReview
### *Autonomous Multi-Agent Engine for Literature Synthesis & Citation Tracing*

<p align="center">
  <a href="#-quick-start"><b>Quick Start</b></a> •
  <a href="#-architecture--agent-flow"><b>Architecture</b></a> •
  <a href="#-features"><b>Features</b></a> •
  <a href="#-tech-stack"><b>Tech Stack</b></a> •
  <a href="#-api-overview"><b>API Spec</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/React-18.0+-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React"/>
  <img src="https://img.shields.io/badge/LangGraph-Agentic-000000?style=for-the-badge&logo=langchain&logoColor=white" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/PostgreSQL-15.0+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
</p>

</div>

---

## 💡 The Idea

Synthesizing scientific literature manually takes hours of fragmented searching and paper evaluation. **TraceReview** automates this end-to-end using autonomous LLM graph agents. It searches across repository databases, performs relevance scoring, critiques sources, and builds transparent, cited reports with verifiable provenance.

---

## ✨ Features

<table width="100%">
  <tr>
    <td width="50%" valign="top">
      <h3>🤖 Multi-Agent Orchestration</h3>
      <p>Powered by <code>LangGraph</code> stateful graphs. Agents dynamically refine queries, cross-reference literature, and critique summaries before final output generation.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🔍 Transparent Citation Tracing</h3>
      <p>Tracks every synthesized statement directly back to its source paper metadata, preventing hallucinated citations and providing verifiable auditing.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>⚡ Asynchronous Execution</h3>
      <p>Built with <code>FastAPI</code> background tasks to handle long-running literature extractions, query streaming, and background database sync smoothly.</p>
    </td>
    <td width="50%" valign="top">
      <h3>🗄️ Relational Persistence</h3>
      <p>Uses <code>PostgreSQL</code> with <code>SQLAlchemy</code> ORM for storing active review sessions, source logs, agent states, and exported review summaries.</p>
    </td>
  </tr>
</table>

---

## 📐 Architecture & Agent Flow

```
┌─────────────────┐       ┌────────────────────┐       ┌──────────────────────┐
│  User Input     │ ───► │  FastAPI Backend   │ ───► │  LangGraph Agent     │
│  (React UI)     │       │  (Orchestrator)    │       │  State Engine        │
└─────────────────┘       └────────────────────┘       └──────────┬───────────┘
                                                                 │
                                                                 ▼
┌─────────────────┐       ┌────────────────────┐       ┌──────────────────────┐
│ Final Synthesis │ ◄───  │ PostgreSQL DB      │ ◄───  │ Source Retrieval &   │
│ & Visual Report │       │ (Session Logging)  │       │ Relevance Critique   │
└─────────────────┘       └────────────────────┘       └──────────────────────┘
```

---

## 🛠️ Tech Stack

<div align="center">

| Core Component | Technology | Description |
| :--- | :--- | :--- |
| **Frontend** | `React 18`, `TypeScript`, `Tailwind CSS` | Sleek dashboard with active agent execution states |
| **Backend API** | `FastAPI`, `Uvicorn`, `Pydantic` | Async REST endpoints & session execution pipeline |
| **Agent Framework**| `LangGraph`, `LangChain` | Stateful, multi-agent cyclical workflow routing |
| **Database** | `PostgreSQL`, `SQLAlchemy` | Structured persistence for sessions, traces, & papers |

</div>

---

## 🚀 Quick Start with Docker

The fastest way to get TraceReview running locally is via Docker Compose:

```bash
# Clone the repository
git clone https://github.com/samavinasir/tracereview.git
cd tracereview

# Build and start services
docker-compose up --build
```

The app will be accessible at:
* **Frontend UI:** `http://localhost:3000`
* **API Documentation:** `http://localhost:8000/docs`

---

## 💻 Local Development Setup

<details>
<summary><b>1. Backend Setup (FastAPI & LangGraph)</b></summary>

```bash
cd backend

# Virtual Environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set Environment Variables
cp .env.example .env

# Run API Server
uvicorn main:app --reload --port 8000
```
</details>

<details>
<summary><b>2. Frontend Setup (React & Vite)</b></summary>

```bash
cd frontend

# Install & Run
npm install
npm run dev
```
</details>

---

## 🔑 Environment Configuration

Create a `.env` file in the root directory:

```env
# Database Configuration
DATABASE_URL=postgresql://postgres:password@localhost:5432/tracereview

# LLM & Agent Provider Credentials
OPENAI_API_KEY=your_openai_api_key_here
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=tracereview
```

---

## 📌 API Endpoint Overview

| Method | Endpoint | Description |
| :---: | :--- | :--- |
| `POST` | `/api/v1/review/start` | Initiates a new multi-agent literature review session |
| `GET` | `/api/v1/review/{session_id}` | Fetches real-time status and agent execution logs |
| `GET` | `/api/v1/review/{session_id}/report` | Retrieves the finalized synthesized report & citations |

---

<div align="center">

Made with ❤️ by [Samavi Nasir](https://github.com/samavinasir)

</div>
