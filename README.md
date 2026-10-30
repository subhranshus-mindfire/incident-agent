# Incident Investigation Agent

An AI-powered system designed to automatically investigate production incidents, identify root causes, and recommend corrective actions with Human-in-the-Loop (HITL) approval.

## 🚀 Overview

The **Incident Investigation Agent** integrates with application logs (Grafana Loki), system metrics (Prometheus), deployment history, and runbooks (Qdrant) to gather and correlate evidence during an incident. Using **LangGraph and LLM-powered reasoning**, it analyzes collected evidence, identifies probable causes, and generates evidence-backed investigation findings.

### Core Capabilities
- **Incident Detection & Simulation:** Create and investigate simulated production incidents across services.
- **Log Analysis:** Retrieve and analyze application logs using Grafana Loki.
- **Metrics Analysis:** Examine CPU, memory, latency, error rates, and system metrics using Prometheus.
- **Deployment Analysis:** Correlate incidents with recent deployments and configuration changes.
- **Knowledge Retrieval:** Retrieve relevant runbooks and historical incident reports using Qdrant vector search.
- **Root Cause Analysis (RCA):** Generate and rank possible root causes based on collected evidence.
- **Remediation Recommendations:** Suggest actionable steps with blast radius/impact evaluation.
- **Human Approval (HITL):** Require engineer approval before executing any remediation action.
- **Automated Verification:** Monitor system health after remediation to verify recovery.
- **RCA Reporting:** Generate structured post-incident reports containing timelines, evidence, root cause, and verification results.

---

## 🛠️ Technology Stack

- **Backend:** Python 3.11+, FastAPI
- **Agent Orchestration:** LangGraph, LangChain
- **LLM Integration:** Gemini / OpenAI / Anthropic
- **Databases:** PostgreSQL (Relational metadata & audit logs), Redis (Session & state cache), Qdrant (Vector database for runbooks)
- **Observability:** Prometheus (Metrics), Grafana Loki (Logs), Grafana (Visualization), Promtail
- **Frontend:** React, TypeScript
- **Infrastructure:** Docker and Docker Compose

---

## 📁 Repository Structure

```text
Incident-Agent/
├── .github/              # GitHub Actions CI/CD workflows
├── app/                  # Core FastAPI backend & Agent application
│   ├── agents/           # LangGraph state machine, nodes, and workflows
│   ├── config/           # Application configuration, DB/Redis/Qdrant clients
│   ├── constants/        # Enums, constants, and status definitions
│   ├── exceptions/       # Custom exceptions & global exception handlers
│   ├── health.py         # Service health check endpoints
│   ├── llms/             # LLM factory and provider integrations
│   ├── main.py           # FastAPI application factory
│   ├── models/           # SQLAlchemy ORM database models
│   ├── prompts/          # System prompts and RCA templates
│   ├── repository/       # Database access layers (CRUD operations)
│   ├── routes/           # API endpoints (Incidents, Runbooks, Remediations)
│   ├── schemas/          # Pydantic schemas and state definitions
│   ├── services/         # Telemetry, Qdrant, and incident services
│   ├── starter.py        # Application startup & lifecycle management
│   ├── tools/            # LangGraph tool bindings (PromQL, LogQL, Vector search)
│   ├── utils/            # Helper utilities and logging formatters
│   └── workers/          # Background tasks and execution adapters
├── frontend/             # React web console
├── simulation/           # Buggy target microservice for incident simulation
├── observability/        # Prometheus, Loki, Promtail, and Grafana configs
├── tests/                # Test suite
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── requirements.txt
```
