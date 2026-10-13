from pathlib import Path

from escalon import ingest as ingest_module
from escalon.search import LocalIndex

FIXTURES = Path(__file__).parent / "fixtures" / "support"


async def test_ingest_indexes_every_chunk_in_batches(tmp_path, embedder, monkeypatch):
    monkeypatch.setattr(ingest_module, "KB_TOPICS", ["windows-client/printing"])
    index = LocalIndex(tmp_path / "i.sqlite", embedder)

    count = await ingest_module.ingest(FIXTURES, index, batch_size=3)

    assert count == len(index) > 3
    hits = await index.search("0x0000052e", top_k=1)
    assert hits[0].article_id.endswith("error-message-0x0000052e-install-network-printer")
