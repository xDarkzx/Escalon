from types import SimpleNamespace

import pytest

from escalon.models import Embedder


class StubOpenAI:
    """Just enough of AsyncOpenAI.embeddings for the Embedder."""

    def __init__(self, dims: int = 3) -> None:
        self.sent: list[list[str]] = []
        self._dims = dims
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, model: str, input: list[str]) -> SimpleNamespace:
        self.sent.append(input)
        data = [SimpleNamespace(index=i, embedding=[float(i)] * self._dims) for i in range(len(input))]
        return SimpleNamespace(data=data[::-1])  # out of order, to prove results are re-sorted


async def test_prefixes_batching_and_order():
    client = StubOpenAI()
    embedder = Embedder(client, "m", 3, query_prefix="q: ", document_prefix="d: ", batch_size=2)  # type: ignore[arg-type]

    vectors = await embedder.embed_documents(["a", "b", "c"])
    query = await embedder.embed_query("z")

    assert vectors == [[0.0] * 3, [1.0] * 3, [0.0] * 3]
    assert query == [0.0] * 3
    assert client.sent == [["d: a", "d: b"], ["d: c"], ["q: z"]]


async def test_dimension_mismatch_fails_loudly():
    embedder = Embedder(StubOpenAI(dims=5), "m", 3)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="returned 5 dimensions, expected 3"):
        await embedder.embed_documents(["a"])
