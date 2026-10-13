"""OpenAI-protocol clients for chat and embeddings, per profile."""

from __future__ import annotations

from collections.abc import Sequence

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI, AsyncOpenAI

from escalon.config import Profile, Settings

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


def openai_client(settings: Settings) -> AsyncOpenAI:
    if settings.profile is Profile.AZURE:
        # Managed identity in Azure, `az login` on a dev machine. No API keys anywhere.
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), COGNITIVE_SERVICES_SCOPE)
        return AsyncAzureOpenAI(
            azure_endpoint=settings.required("azure_openai_endpoint"),
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_api_version,
        )
    # Ollama ignores the key, but the client requires one.
    return AsyncOpenAI(base_url=settings.local_openai_base_url, api_key="ollama")


class Embedder:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        dimensions: int,
        *,
        query_prefix: str = "",
        document_prefix: str = "",
        batch_size: int = 64,
    ) -> None:
        self._client = client
        self._model = model
        self.dimensions = dimensions
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._batch_size = batch_size

    @classmethod
    def from_settings(cls, client: AsyncOpenAI, settings: Settings) -> Embedder:
        return cls(
            client,
            settings.embedding_model,
            settings.embedding_dimensions,
            query_prefix=settings.embedding_query_prefix,
            document_prefix=settings.embedding_document_prefix,
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self.embed([self._document_prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([self._query_prefix + text]))[0]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            response = await self._client.embeddings.create(model=self._model, input=batch)
            for item in sorted(response.data, key=lambda d: d.index):
                if len(item.embedding) != self.dimensions:
                    raise ValueError(
                        f"{self._model} returned {len(item.embedding)} dimensions, "
                        f"expected {self.dimensions} (ESCALON_EMBEDDING_DIMENSIONS)"
                    )
                vectors.append(item.embedding)
        return vectors
