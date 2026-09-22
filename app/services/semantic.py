from __future__ import annotations

from app.ai.client import get_ai_client
from app.core.config import settings


class SemanticRetrievalService:
    """Optional OpenAI-compatible embedding layer with a safe lexical fallback."""

    @classmethod
    async def embed(cls, text: str) -> list[float] | None:
        if not text.strip() or not settings.embedding_model:
            return None
        try:
            client = get_ai_client()
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=text[:12000],
            )
            return list(response.data[0].embedding)
        except Exception:
            return None

    @classmethod
    async def embed_many(cls, texts: list[str]) -> list[list[float] | None]:
        if not texts or not settings.embedding_model:
            return [None for _ in texts]
        try:
            client = get_ai_client()
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=[t[:12000] for t in texts],
            )
            by_index = {item.index: list(item.embedding) for item in response.data}
            return [by_index.get(i) for i in range(len(texts))]
        except Exception:
            return [None for _ in texts]
