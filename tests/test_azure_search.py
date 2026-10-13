import base64

import pytest

from escalon.azure_search import AzureSearchIndex, document_key, index_definition
from escalon.config import Settings
from escalon.search import LocalIndex
from escalon.services import build_index
from tests.conftest import make_chunk


def test_document_key_is_azure_safe_and_reversible():
    key = document_key("windows-client/printing/a#3")
    assert set(key) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")
    assert base64.urlsafe_b64decode(key).decode() == "windows-client/printing/a#3"


def test_index_definition_vector_field_matches_embedding_size():
    index = index_definition("kb", 1536)
    vector = next(f for f in index.fields if f.name == "vector")
    assert vector.vector_search_dimensions == 1536
    assert next(f for f in index.fields if f.key).name == "key"


class FakeCredential:
    async def get_token(self, *scopes, **kwargs):
        raise AssertionError("tests never reach the network")


class StubSearchClient:
    def __init__(self, rows=(), failures=()):
        self.rows = list(rows)
        self.failures = set(failures)
        self.uploaded = []
        self.query = None

    async def merge_or_upload_documents(self, documents):
        self.uploaded.extend(documents)
        return [
            type("R", (), {"key": d["key"], "succeeded": d["key"] not in self.failures})() for d in documents
        ]

    async def search(self, **kwargs):
        self.query = kwargs

        async def results():
            for row in self.rows:
                yield row

        return results()


def azure_index(embedder, client):
    index = AzureSearchIndex(
        "https://s.search.windows.net", "kb", credential=FakeCredential(), embedder=embedder
    )
    index._client = client
    return index


def row(article, n, score):
    c = make_chunk(article, n, f"T {article}", "body")
    return {
        "chunk_id": c.id,
        "article_id": article,
        "title": c.title,
        "section": c.section,
        "url": c.url,
        "text": c.text,
        "@search.score": score,
    }


async def test_hybrid_query_and_per_article_cap(embedder):
    client = StubSearchClient([row("a", 0, 0.9), row("a", 1, 0.8), row("a", 2, 0.7), row("b", 0, 0.6)])

    hits = await azure_index(embedder, client).search("printer 0x0000052e", top_k=3)

    assert [h.article_id for h in hits] == ["a", "a", "b"]
    assert client.query["search_text"] == "printer 0x0000052e"
    assert client.query["vector_queries"][0].fields == "vector"


async def test_rejected_documents_fail_the_upload(embedder):
    chunk = make_chunk("a", 0, "t", "x")
    client = StubSearchClient(failures={document_key(chunk.id)})

    with pytest.raises(RuntimeError, match="rejected 1 documents"):
        await azure_index(embedder, client).upsert([chunk])


def base_settings(**overrides):
    values = {
        "chat_model": "m",
        "embedding_model": "e",
        "embedding_dimensions": 8,
        "auth_mode": "disabled",
        "dev_user_email": "d@contoso.test",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_profiles_build_their_own_index(tmp_path):
    local = build_index(
        base_settings(
            profile="local", local_openai_base_url="http://x/v1", local_index_path=tmp_path / "i.sqlite"
        )
    )
    azure = build_index(
        base_settings(
            profile="azure",
            azure_openai_endpoint="https://o.openai.azure.com",
            azure_search_endpoint="https://s.search.windows.net",
        )
    )
    assert isinstance(local, LocalIndex)
    assert isinstance(azure, AzureSearchIndex)


def test_azure_profile_without_endpoints_is_a_startup_error():
    with pytest.raises(ValueError, match="ESCALON_AZURE_OPENAI_ENDPOINT, ESCALON_AZURE_SEARCH_ENDPOINT"):
        base_settings(profile="azure")
