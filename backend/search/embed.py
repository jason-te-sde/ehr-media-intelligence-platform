"""Sentence-transformers wrapper for the semantic search index.

The model is loaded once at import time. Embeddings are L2-normalized so
ChromaDB's cosine-distance space reduces to a dot product internally.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Return a 384-dim L2-normalized embedding for ``text``."""
    return _model().encode(text, normalize_embeddings=True).tolist()


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Batch-embed ``texts``. Returns one 384-dim normalized vector per input."""
    arr = _model().encode(texts, normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    return arr.tolist()
