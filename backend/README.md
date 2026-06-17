# Contract Intelligence Engine

> **Autonomous legal-risk analyst for early-stage SaaS contracts — built without a lawyer in the loop.**

[![Eval CI](https://github.com/yourusername/contract-intelligence-engine/actions/workflows/evals.yml/badge.svg)](https://github.com/yourusername/contract-intelligence-engine/actions)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-purple.svg)](https://langchain-ai.github.io/langgraph)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Problem This Solves

Early-stage B2B startups sign dozens of vendor, partnership, and customer contracts monthly. Non-legal founders rubber-stamp these because they can't afford legal review at $400/hr per document.

The real operational pain: a bad indemnification clause, an uncapped liability provision, or a missing IP-assignment clause can sink a $2M seed-stage company.

**I built this after living this exact problem at Synlitics** — watching our team sign SaaS vendor agreements without understanding that "mutual indemnification" in one clause and "unlimited liability" in the next were a $500K exposure. This project is what I wished existed then.

---

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         FastAPI (port 8000)              │
                    │  POST /contracts  →  SSE /stream         │
                    └──────────────┬──────────────────────────┘
                                   │  AsyncPostgresSaver
                                   │  (durable checkpointing)
                    ┌──────────────▼──────────────────────────┐
                    │        LangGraph StateGraph              │
                    │                                          │
                    │  ┌─────────────────────────────────┐    │
                    │  │  Node 1: Clause Extractor        │    │
                    │  │  PydanticAI → ContractAnalysis   │    │
                    │  │  Retry on ValidationError (×3)   │    │
                    │  └──────────────┬──────────────────┘    │
                    │                 │                         │
                    │  ┌──────────────▼──────────────────┐    │
                    │  │  Node 2: Precedent Retriever     │    │
                    │  │  MCP Client ──► FastMCP Server   │    │
                    │  │           ──► pgvector cosine     │    │
                    │  └──────────────┬──────────────────┘    │
                    │                 │                         │
                    │  ┌──────────────▼──────────────────┐    │
                    │  │  Node 3: Risk Scorer             │    │
                    │  │  PydanticAI → RiskReport         │    │
                    │  └──────────────┬──────────────────┘    │
                    │                 │                         │
                    │       ┌─────────▼──────────┐            │
                    │       │  Conditional Router │            │
                    │       └──┬───────────────┬─┘            │
                    │    < 40  │               │  ≥ 40         │
                    │  ┌───────▼──┐    ┌───────▼───────────┐  │
                    │  │Auto-     │    │Escalate           │  │
                    │  │Approve   │    │interrupt_before ⏸ │  │
                    │  └──────────┘    └───────────────────┘  │
                    └─────────────────────────────────────────┘
                                                │
                    ┌───────────────────────────▼─────────┐
                    │     FastMCP Server (port 8001)        │
                    │  search_precedent_clauses()           │
                    │    → pgvector cosine similarity       │
                    │    → 500+ CUAD clause embeddings      │
                    │  get_jurisdiction_rules()             │
                    │    → regulatory flag lookup           │
                    └──────────────────────────────────────┘
```

---

## Engineering Highlights

### 1. Durable LangGraph Checkpointing
Every node's output is persisted to PostgreSQL via `AsyncPostgresSaver` before the next node runs. Server crashes mid-analysis? The graph resumes from the last completed node on restart.

```python
# graph.py
return builder.compile(
    checkpointer=AsyncPostgresSaver.from_conn_string(DATABASE_URL),
    interrupt_before=["escalate"],  # Human-in-the-loop
)
```

### 2. Retry-on-ValidationError Loop
PydanticAI agents must produce strictly-typed `ContractAnalysis` models. If the LLM output fails Pydantic validation, the node retries with an increasingly specific prompt — up to 3 times — logging each failure to Logfire.

```python
# nodes/clause_extractor.py
for attempt in range(MAX_RETRIES):
    try:
        result = await clause_agent.run(prompt + RETRY_HINTS[attempt])
        return {"analysis": result.data.model_dump()}
    except ValidationError as exc:
        logfire.warning("validation_error_retry", attempt=attempt, errors=exc.errors())
```

### 3. Decoupled MCP Architecture
The precedent retrieval tool logic lives in a completely separate process (`mcp_server/server.py`) that the LangGraph node connects to as an MCP client over Streamable HTTP. The server can be scaled, versioned, or replaced independently.

```python
# The LangGraph node is just a client — no SQL, no pgvector here:
async with streamablehttp_client("http://mcp_server:8001/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("search_precedent_clauses", {"clause_text": text})
```

### 4. Human-in-the-Loop via `interrupt_before`
Contracts scoring ≥ 40 pause the graph before the `escalate` node. The dashboard shows a review banner. Reviewers call `POST /contracts/{id}/resume` which restarts the graph from the PostgreSQL checkpoint.

### 5. Logfire Distributed Tracing
Every contract analysis produces one distributed trace:

```
FastAPI POST /contracts [312ms]
  └─ LangGraph run [287ms]
       ├─ clause_extraction [89ms]  ← tokens_in=4821 tokens_out=847
       │    └─ ValidationError retry [attempt=1]
       ├─ precedent_retrieval [54ms]
       │    ├─ mcp_get_jurisdiction_rules [12ms] ← similarity=0.87
       │    └─ mcp_search_precedent_clauses [38ms]
       └─ risk_scoring [144ms]      ← risk_score=73 factors=4
```

### 6. Rust Clause Deduplicator
`tools/clause_hasher.rs` generates deterministic SHA-256 content-addressable hashes for clause text (with whitespace normalisation) before each pgvector insert — preventing duplicate embeddings and keeping the IVFFlat index compact.

```bash
echo "This Agreement shall not limit liability in any way." | ./tools/clause_hasher
# → a3f7c891b2d44e8f...
```

```rust
// Normalise before hashing: collapse whitespace for stability
let normalised: String = input.trim().split_whitespace().collect::<Vec<&str>>().join(" ");
hasher.update(normalised.as_bytes());
```

---

## Automated Evaluations

The `evals/` directory contains a dataset of **30 manually-labelled contracts** with ground-truth risk scores.

### Deterministic Evaluator
Rule-based assertions that catch calibration regressions:
```python
# Contracts with uncapped liability MUST score > 70
assert report.risk_score > 70, f"FAIL: uncapped liability scored {report.risk_score}"
```

### LLM-as-Judge (Gemini 2.0 Flash)
Grades each risk report on:
- **`clause_coverage`** — fraction of risky clauses correctly identified
- **`hallucination_rate`** — fraction of cited clauses not in the contract text
- **`severity_calibration`** — whether severity labels match actual risk level

### CI Gate
```yaml
# .github/workflows/evals.yml
- name: Enforce hallucination rate gate
  run: |
    python -c "
    r = json.load(open('evals/results.json'))
    assert r['hallucination_rate'] < 0.05, f'BLOCKING: {r[\"hallucination_rate\"]:.1%} exceeds 5%'
    "
```
**Merges to `main` are blocked** if hallucination rate exceeds 5%.

---

## Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.2 + AsyncPostgresSaver |
| AI Agents | PydanticAI + Gemini 2.0 Flash (free tier) |
| MCP | FastMCP 2.x (Streamable HTTP) + MCP SDK client |
| Vector Search | pgvector (IVFFlat, 768-dim, cosine similarity) |
| Embeddings | Google text-embedding-004 (768-dim) |
| Seed Data | CUAD dataset (510 contracts, 41 clause types) |
| Observability | Logfire (FastAPI + PydanticAI + asyncpg instrumented) |
| Frontend | Next.js 14 App Router + SSE streaming |
| Deduplication | Rust (SHA-256, whitespace-normalised) |
| Database | PostgreSQL 16 + pgvector |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- `GEMINI_API_KEY` (free at [aistudio.google.com](https://aistudio.google.com/apikey))

### 1. Configure environment
```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set GEMINI_API_KEY
```

### 2. Start all services
```bash
docker-compose up -d
# Starts: PostgreSQL+pgvector, FastMCP server, FastAPI, Next.js
```

### 3. Seed the CUAD clause database
```bash
# Install seed dependencies
pip install -e "backend[seed]"
# Download CUAD + embed + insert (takes ~10 min on free tier)
python seed_clauses.py
```

### 4. Open the dashboard
```
http://localhost:3000
```

Upload any contract PDF or paste text → live analysis starts immediately.

---

## Running Evals

```bash
# Install eval dependencies
pip install -e "backend[evals]"

# Run against live API (30 contracts)
python evals/run_evals.py

# Faster: evaluate 10 contracts only
python evals/run_evals.py --sample 10

# Skip LLM judge (deterministic only, instant)
python evals/run_evals.py --skip-llm-judge

# View results
cat evals/results.json
```

---

## Building the Rust Hasher

```bash
cd tools
# Install Rust: https://rustup.rs
cargo build --release
cargo test
# Binary at: tools/target/release/clause_hasher

# Test
echo "Liability is uncapped and unlimited" | ./target/release/clause_hasher
```

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app + SSE
│   │   ├── graph/                # LangGraph StateGraph
│   │   │   ├── graph.py          # compile() with interrupt_before
│   │   │   ├── nodes/
│   │   │   │   ├── clause_extractor.py  # PydanticAI + retry
│   │   │   │   ├── precedent_retriever.py # MCP client
│   │   │   │   └── risk_scorer.py       # PydanticAI
│   │   │   └── router.py         # Conditional routing
│   │   ├── models/               # Pydantic v2 schemas
│   │   │   ├── contract.py       # ContractAnalysis
│   │   │   └── risk.py           # RiskReport, RiskFactor
│   │   ├── db/
│   │   │   ├── postgres.py       # AsyncPostgresSaver + schema
│   │   │   └── embeddings.py     # text-embedding-004 helpers
│   │   └── observability.py      # Logfire setup
│   └── mcp_server/
│       └── server.py             # FastMCP standalone server
├── frontend/                     # Next.js 14 dashboard
│   ├── app/
│   │   ├── page.tsx              # Upload + hero
│   │   └── contracts/[id]/
│   │       └── page.tsx          # Live analysis view (SSE)
│   └── components/
│       ├── ContractUploader.tsx
│       ├── GraphProgress.tsx     # LangGraph node tracker
│       ├── RiskGauge.tsx         # Animated SVG arc
│       ├── ClauseTable.tsx       # Expandable risk table
│       └── EscalationBanner.tsx  # Human review UI
├── evals/
│   ├── ground_truth.json         # 30 labelled contracts
│   ├── eval_deterministic.py     # Rule-based assertions
│   ├── eval_llm_judge.py         # Gemini LLM-as-judge
│   └── run_evals.py              # Orchestrator
├── tools/
│   └── clause_hasher.rs          # Rust SHA-256 hasher
├── seed_clauses.py               # CUAD → pgvector pipeline
├── docker-compose.yml            # Full stack
└── .github/workflows/
    └── evals.yml                 # CI with hallucination gate
```

---

## Observability

Set `LOGFIRE_TOKEN` in `.env` (free tier at [logfire.pydantic.dev](https://logfire.pydantic.dev)) to get the full distributed trace waterfall.

Without a token, traces print to console — still useful for local development.

---

## License

MIT
