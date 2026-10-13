"""Azure AI Search implementation of ``SearchIndex``.

Hybrid query: the same text goes to BM25 and to an HNSW vector query, and the service fuses
the two rankings with reciprocal rank fusion — the same scheme ``LocalIndex`` uses.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence

from azure.core.credentials_async import AsyncTokenCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    LexicalAnalyzerName,
    SearchableField,
    SearchField,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from escalon.kb import Chunk
from escalon.models import Embedder
from escalon.search import CANDIDATES_PER_RANKER, MAX_CHUNKS_PER_ARTICLE, Hit, diversify

VECTOR_PROFILE = "escalon-hnsw"
EDM_STRING = "Edm.String"


def document_key(chunk_id: str) -> str:
    """Chunk ids contain '/' and '#', which Azure document keys do not allow."""
    return base64.urlsafe_b64encode(chunk_id.encode()).decode()


def index_definition(name: str, dimensions: int) -> SearchIndex:
    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="key", type=EDM_STRING, key=True),
            SimpleField(name="chunk_id", type=EDM_STRING),
            SimpleField(name="article_id", type=EDM_STRING, filterable=True),
            SearchableField(name="title", analyzer_name=LexicalAnalyzerName.EN_MICROSOFT),
            SearchableField(name="section", analyzer_name=LexicalAnalyzerName.EN_MICROSOFT),
            SearchableField(name="text", analyzer_name=LexicalAnalyzerName.EN_MICROSOFT),
            SimpleField(name="url", type=EDM_STRING),
            SearchField(
                name="vector",
                type="Collection(Edm.Single)",
                searchable=True,
                stored=False,  # never returned, so don't pay to store it
                vector_search_dimensions=dimensions,
                vector_search_profile_name=VECTOR_PROFILE,
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name="hnsw")],
        ),
    )


class AzureSearchIndex:
    def __init__(
        self, endpoint: str, index_name: str, credential: AsyncTokenCredential, embedder: Embedder
    ) -> None:
        self._endpoint = endpoint
        self._index_name = index_name
        self._credential = credential
        self._embedder = embedder
        self._client = SearchClient(endpoint, index_name, credential)

    async def ensure_index(self) -> None:
        async with SearchIndexClient(self._endpoint, self._credential) as admin:
            await admin.create_or_update_index(index_definition(self._index_name, self._embedder.dimensions))

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        vectors = await self._embedder.embed_documents([c.text for c in chunks])
        documents = [
            {
                "key": document_key(c.id),
                "chunk_id": c.id,
                "article_id": c.article_id,
                "title": c.title,
                "section": c.section,
                "text": c.text,
                "url": c.url,
                "vector": v,
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
        results = await self._client.merge_or_upload_documents(documents)
        failed = [r.key for r in results if not r.succeeded]
        if failed:
            raise RuntimeError(f"Azure AI Search rejected {len(failed)} documents, e.g. {failed[:3]}")

    async def search(self, query: str, top_k: int) -> list[Hit]:
        vector = await self._embedder.embed_query(query)
        results = await self._client.search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(vector=vector, k_nearest_neighbors=CANDIDATES_PER_RANKER, fields="vector")
            ],
            select=["chunk_id", "article_id", "title", "section", "url", "text"],
            top=top_k * MAX_CHUNKS_PER_ARTICLE * 2,  # headroom for diversify()
        )
        hits = [
            Hit(
                chunk_id=r["chunk_id"],
                article_id=r["article_id"],
                title=r["title"],
                section=r["section"],
                url=r["url"],
                text=r["text"],
                score=r["@search.score"],
            )
            async for r in results
        ]
        return diversify(hits, top_k)

    async def close(self) -> None:
        await self._client.close()
