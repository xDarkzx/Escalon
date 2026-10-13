import pytest

from escalon.search import LocalIndex, fts_query, reciprocal_rank_fusion
from tests.conftest import make_chunk

CHUNKS = [
    make_chunk("printing/a", 0, "Network printer install fails", "Error 0x0000052e means bad credentials."),
    make_chunk("printing/b", 0, "Printer driver missing", "Drivers from Windows Update are not all listed."),
    make_chunk("mfa/c", 0, "MFA prompt loop", "Users see AADSTS50076 and are asked to sign in again."),
    make_chunk(
        "network/d", 0, "Wi-Fi keeps disconnecting", "Wireless adapter power saving drops the connection."
    ),
]


@pytest.fixture
async def index(tmp_path, embedder):
    idx = LocalIndex(tmp_path / "index.sqlite", embedder)
    await idx.upsert(CHUNKS)
    return idx


async def test_exact_error_code_ranks_first(index):
    hits = await index.search("my printer says 0x0000052e when I add it", top_k=3)
    assert hits[0].article_id == "printing/a"


async def test_entra_error_code_matches(index):
    hits = await index.search("AADSTS50076", top_k=1)
    assert hits[0].article_id == "mfa/c"


async def test_upsert_replaces_existing_chunk_and_persists(tmp_path, embedder, index):
    await index.upsert([make_chunk("printing/a", 0, "Network printer install fails", "Updated text.")])
    reopened = LocalIndex(tmp_path / "index.sqlite", embedder)

    assert len(reopened) == len(CHUNKS)
    hits = await reopened.search("Updated text", top_k=1)
    assert hits[0].text.endswith("Updated text.")


async def test_query_with_no_terms_still_uses_vectors(index):
    hits = await index.search("?!", top_k=2)
    assert len(hits) == 2


def test_fts_query_quotes_terms_so_user_text_cannot_inject_syntax():
    assert fts_query('printer" OR NEAR(x') == '"near" OR "or" OR "printer"'
    assert fts_query("?") is None


def test_rrf_rewards_items_ranked_well_by_both():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    assert max(scores, key=scores.__getitem__) in {"a", "b"}
    assert scores["a"] == scores["b"] > scores["c"] > 0
