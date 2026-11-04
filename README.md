# Incident Investigation & Root Cause Analysis Agent

An autonomous AI-powered incident investigation and remediation agent built with **LangGraph**, **FastAPI**, **Qdrant vector memory**, **PostgreSQL durable checkpoints**, **Prometheus**, **Grafana Loki**, and **Streamlit**.

---

## 🚀 Key Highlights & Capabilities

- **100% Real-Time Telemetry & Zero Static Mocks:** Integrates with live microservices, Prometheus metric scrapers, Loki log push streams, and Qdrant semantic vector memory.
- **Stateful LangGraph Workflow:** 16-field typed state machine implementing alert ingestion, parallel diagnostic retrieval, evidence correlation, RCA hypothesis formulation, blast radius assessment, and postmortem generation.
- **Human-in-the-Loop (HITL) Approval Interrupt:** Enforces mandatory human approval for high-risk actions (`ROLLBACK_DEPLOYMENT`, `TERMINATE_DB_TRANSACTIONS`) via LangGraph interrupts and PostgreSQL checkpoints.
- **Evidence Sufficiency & Diagnostics Loops:** Conditional edge routes back into diagnostic loops if evidence is insufficient or when the human operator requests additional diagnostics.
- **Live Target Microservice (`payment-api`):** Fully instrumented live service with Prometheus `/metrics`, `/pay`, dynamic versioning, chaos fault injection endpoints, and live remediation hooks.
- **Streamlit Human Approval & Investigation Console:** Web console for live incident triggering, telemetry inspection, one-click HITL approval, and postmortem downloads.

---

## 🛠️ Technology Stack

- **Backend Framework:** Python 3.12, FastAPI, Uvicorn, Pydantic v2
- **Agent Orchestration:** LangGraph, LangChain Core
- **Database & Checkpointing:** PostgreSQL (Asyncpg / SQLAlchemy 2.0) with LangGraph durable checkpointer, Redis
- **Vector Memory:** Qdrant (`historical_incidents` and `runbooks` collections with cosine similarity)
- **Telemetry & Observability:** Prometheus (PromQL metrics), Grafana Loki (LogQL logs)
- **Investigation UI:** Streamlit (`ui/app.py`) on port `8501`
- **Simulation Testbed:** Live `payment-api` on port `8080` with chaos fault injection
- **Containerization:** Docker & Docker Compose

---

## 📖 Architecture & State Schema

- **[Detailed Graph Architecture & State Schema](docs/architecture.md):** Complete Mermaid flowchart diagram of graph nodes, feedback loops, conditional edges, and the 16-field `InvestigationState` schema.
- **[Sample Root Cause Analysis (RCA) Postmortem Report](docs/sample_rca_report.md):** Production-grade incident postmortem with timeline, correlated evidence, root cause, and remediation verification.

---

## ⚡ Quickstart Guide

### 1. Start the Complete Stack
Start all services (Postgres, Redis, Qdrant, Prometheus, Loki, FastAPI Agent, Payment API, and Streamlit UI):

```bash
docker compose up -d
```

### 2. Access Web Interfaces & Endpoints
| Service | Endpoint | Purpose |
| :--- | :--- | :--- |
| **Streamlit Investigation Console** | `http://localhost:8501` | Interactive investigation trigger, telemetry inspector & HITL approval |
| **FastAPI Agent Backend API** | `http://localhost:8000/docs` | OpenAPI documentation & agent endpoints |
| **Payment API (Target Microservice)**| `http://localhost:8080/health` | Live microservice with chaos & remediation hooks |
| **Prometheus Dashboard** | `http://localhost:9090` | Scrapes `payment-api` metrics every 5 seconds |
| **Grafana Loki** | `http://localhost:3100` | Log ingestion stream |
| **Qdrant Vector Engine** | `http://localhost:6333/dashboard` | Historical incident & runbook vector collections |

---

## 🧪 Chaos Injection & Investigation Workflow

You can run an end-to-end incident investigation with one-click commands:

### Step 1: Inject Production Failure Mode
```bash
# Injects database pool deadlock and generates failed payment traffic:
make chaos-deadlock

# Or inject bad deployment v2.3.1 regression:
make chaos-bad-deploy
```

### Step 2: Trigger AI Agent Investigation
Open the Streamlit UI at `http://localhost:8501` or run via `curl`:
```bash
curl -X POST http://localhost:8000/api/v1/investigations/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "service": "payment-api",
    "symptoms": "Our payment API is returning HTTP 500 errors. Database connection pool timeout reported.",
    "severity": "critical"
  }'
```

### Step 3: Human-in-the-Loop Review & Approval
Review the evidence and approve the remediation in the Streamlit UI or via API:
```bash
curl -X POST http://localhost:8000/api/v1/investigations/<incident_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"reason": "Approved by on-call engineer"}'
```

The agent will execute the live remediation on `payment-api`, verify recovery, index the incident into Qdrant vector memory, and generate a structured RCA report.

---

## 🔐 Sign-in, Models and Data

**Accounts.** The console and the API need a signed-in user. Create an account with
`make create-user NAME=<username>` and type the password at the prompt. Every investigation records who opened it, and every approval, rejection or diagnostics request records who made it. The approval card shows *Created by*, and the outcome shows *Approved by*.

**Chat models.** The chat agent's model is chosen with `LLM_PROVIDER`: `ollama` (local, default in `.env.example`), `groq` or `gemini`. Each uses its own model setting (`OLLAMA_MODEL`, `GROQ_MODEL`, `GEMINI_MODEL`) and key where needed.

**Search embeddings.** Runbooks and incidents are embedded with `BAAI/bge-small-en-v1.5` (384 dimensions) through fastembed. After changing `EMBEDDING_MODEL`, run `make reindex`.

**Sample data.** `data/samples/` holds the synthetic records: historical incidents (indexed into Qdrant on start), application logs, deployments, system metrics (CSV) and service dependencies.

**Parallel diagnostics.** Telemetry gathering and Qdrant retrieval run at the same time, and the investigation waits for both before correlating evidence.

## 🧪 Running Automated Tests

Run the full automated test suite (50 tests covering state machine, HITL approval, Qdrant vector search, Prometheus/Loki telemetry, simulation, and UI):

```bash
docker compose run --rm test
```
