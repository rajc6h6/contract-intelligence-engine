"""
Database layer: PostgreSQL + pgvector setup.

Manages:
  - The asyncpg connection pool (shared across all requests)
  - The LangGraph AsyncPostgresSaver checkpointer (durable graph state)
  - Schema initialisation for clause_precedents and jurisdiction_rules tables
  - The contracts and analysis_runs tracking tables
"""

from __future__ import annotations

import os
import asyncpg
from asyncpg import Pool
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# ── Schema DDL ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Enable pgvector extension (must be installed in the image)
CREATE EXTENSION IF NOT EXISTS vector;

-- Contracts submitted for analysis
CREATE TABLE IF NOT EXISTS contracts (
    id              VARCHAR(36) PRIMARY KEY,
    filename        VARCHAR(500),
    raw_text        TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- pending | running | completed | escalated | failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

-- Historical clause embeddings for pgvector similarity search
-- Seeded from the CUAD dataset (510 real contracts, 41 clause types)
CREATE TABLE IF NOT EXISTS clause_precedents (
    id              SERIAL PRIMARY KEY,
    clause_text     TEXT NOT NULL,
    clause_type     VARCHAR(100) NOT NULL,
    -- CUAD clause category (e.g. 'Liability Cap', 'IP Ownership Assignment')
    embedding       vector(768),
    -- text-embedding-004 produces 768-dim vectors
    outcome         TEXT,
    -- Real-world outcome label derived from CUAD annotations
    jurisdiction    VARCHAR(100),
    risk_label      VARCHAR(50),
    -- 'low' | 'medium' | 'high' | 'critical'
    content_hash    VARCHAR(64) UNIQUE NOT NULL,
    -- SHA-256 via tools/clause_hasher.rs for deduplication
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Jurisdiction-specific regulatory flags
CREATE TABLE IF NOT EXISTS jurisdiction_rules (
    id              SERIAL PRIMARY KEY,
    jurisdiction    VARCHAR(100) NOT NULL,
    rule_type       VARCHAR(100) NOT NULL,
    description     TEXT NOT NULL,
    severity        VARCHAR(50) NOT NULL DEFAULT 'medium',
    source          VARCHAR(500)
);

-- pgvector IVFFlat index: cosine similarity, 100 clusters
-- Provides sub-10ms p99 for 500+ clause embeddings
CREATE INDEX IF NOT EXISTS clause_precedents_embedding_idx
    ON clause_precedents
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Fast jurisdiction lookups
CREATE INDEX IF NOT EXISTS jurisdiction_rules_jurisdiction_idx
    ON jurisdiction_rules (jurisdiction);

-- Analysis run status for SSE streaming
CREATE TABLE IF NOT EXISTS analysis_runs (
    contract_id     VARCHAR(36) PRIMARY KEY REFERENCES contracts(id),
    current_node    VARCHAR(100),
    risk_score      INTEGER,
    risk_report     JSONB,
    requires_escalation BOOLEAN DEFAULT FALSE,
    thread_id       VARCHAR(36) UNIQUE
    -- LangGraph thread ID for checkpointer
);
"""

SEED_JURISDICTIONS_SQL = """
INSERT INTO jurisdiction_rules (jurisdiction, rule_type, description, severity, source)
VALUES
    ('California, USA',    'privacy',       'CCPA compliance required for personal data processing',              'high',     'California Consumer Privacy Act'),
    ('California, USA',    'employment',    'Non-compete clauses are largely unenforceable under California law', 'high',     'California Business and Professions Code §16600'),
    ('Delaware, USA',      'corporate',     'Preferred jurisdiction for SaaS contracts — established case law',   'low',      'Delaware General Corporation Law'),
    ('New York, USA',      'finance',       'UCC Article 9 governs security interests in software licenses',      'medium',   'UCC Article 9'),
    ('England and Wales',  'gdpr',          'UK GDPR data processing addendum required for personal data',        'high',     'UK GDPR / Data Protection Act 2018'),
    ('European Union',     'gdpr',          'EU GDPR DPA mandatory; Standard Contractual Clauses for transfers', 'critical', 'GDPR Article 28'),
    ('European Union',     'digital',       'Digital Markets Act obligations for gatekeepers',                    'medium',   'EU DMA 2022'),
    ('India',              'data',          'DPDP Act 2023 requires data fiduciary obligations',                  'high',     'Digital Personal Data Protection Act 2023'),
    ('Not specified',      'jurisdiction',  'No governing law specified — increases dispute resolution risk',     'high',     'General contract law principle')
ON CONFLICT DO NOTHING;
"""

# ── Connection Pool ─────────────────────────────────────────────────────────

_pool: Pool | None = None
_pg_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


async def get_pool() -> Pool:
    """Return the shared asyncpg connection pool, creating it if necessary."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=2,
            max_size=10,
            command_timeout=60,
            # Register pgvector codec so we can read/write vector columns
            init=_register_vector_codec,
        )
    return _pool


async def _register_vector_codec(conn: asyncpg.Connection) -> None:
    """Register pgvector type codec with asyncpg."""
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: str(v),
        decoder=lambda v: [float(x) for x in v.strip("[]").split(",")],
        schema="public",
        format="text",
    )


async def init_db() -> None:
    """Create all tables and seed jurisdiction rules. Idempotent."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await conn.execute(SEED_JURISDICTIONS_SQL)


async def get_checkpointer() -> AsyncPostgresSaver:
    """
    Return the LangGraph AsyncPostgresSaver backed by our PostgreSQL instance.

    langgraph-checkpoint-postgres 3.x requires a psycopg AsyncConnectionPool.
    The pool uses autocommit=True and prepare_threshold=0 as required by
    LangGraph's checkpoint implementation.
    """
    global _checkpointer, _pg_pool
    if _checkpointer is None:
        db_url = os.environ["DATABASE_URL"]
        _pg_pool = AsyncConnectionPool(
            conninfo=db_url,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await _pg_pool.open()
        _checkpointer = AsyncPostgresSaver(_pg_pool)
        await _checkpointer.setup()  # Creates LangGraph checkpoint tables
    return _checkpointer


async def close_db() -> None:
    """Graceful shutdown: close pool and checkpointer connections."""
    global _pool, _checkpointer, _pg_pool
    if _pool:
        await _pool.close()
        _pool = None
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None
    _checkpointer = None
