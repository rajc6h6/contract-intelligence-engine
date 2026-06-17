"""
Google text-embedding-004 helpers for clause vectorisation.

text-embedding-004 produces 768-dimensional embeddings (vs OpenAI's 1536).
Optimised for semantic similarity tasks — ideal for pgvector cosine search.

Rate limit awareness: free tier is 1500 requests/minute at 100 QPM for
embeddings; the seed script uses batching to stay within limits.
"""

from __future__ import annotations

import os
import asyncio
from typing import Sequence

import google.generativeai as genai

# Configure once at import time (also called in observability.py startup)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/text-embedding-004")
EMBEDDING_DIM = 768  # Fixed for text-embedding-004


def embed_text(text: str, task_type: str = "retrieval_document") -> list[float]:
    """
    Generate a 768-dim embedding for a single text string.

    task_type options:
      - 'retrieval_document': for indexing clause precedents (seeding)
      - 'retrieval_query': for query-time clause similarity search
      - 'semantic_similarity': for general comparison

    Uses synchronous API; wrap with run_in_executor for async contexts.
    """
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text[:8000],  # text-embedding-004 max input
        task_type=task_type,
    )
    return result["embedding"]


async def embed_text_async(
    text: str,
    task_type: str = "retrieval_document",
) -> list[float]:
    """Async wrapper: runs embed_text in a thread pool to avoid blocking."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: embed_text(text, task_type),
    )


async def embed_batch(
    texts: Sequence[str],
    task_type: str = "retrieval_document",
    batch_size: int = 20,
    delay_between_batches: float = 1.2,  # Respect free-tier QPM limit
) -> list[list[float]]:
    """
    Embed a list of texts in batches with rate-limit-aware delays.

    Used by seed_clauses.py to embed 500+ CUAD clauses without hitting
    the free-tier QPM limit (100 QPM = ~1.7/second → 1.2s delay is safe).
    """
    results: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = await asyncio.gather(
            *[embed_text_async(t, task_type) for t in batch]
        )
        results.extend(batch_embeddings)
        if i + batch_size < len(texts):
            await asyncio.sleep(delay_between_batches)
    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (for local validation)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x**2 for x in a) ** 0.5
    norm_b = sum(x**2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
