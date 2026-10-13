from escalon import cli, ingest
from escalon.search import Hit


class OneHitIndex:
    async def search(self, query, top_k):
        return [Hit("a#0", "a", "Printer error", "Cause", "https://learn.microsoft.com/x", "t", 0.5)]


def test_search_command_prints_ranked_hits(monkeypatch, capsys):
    monkeypatch.setenv("ESCALON_PROFILE", "local")
    monkeypatch.setenv("ESCALON_LOCAL_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ESCALON_CHAT_MODEL", "m")
    monkeypatch.setenv("ESCALON_EMBEDDING_MODEL", "e")
    monkeypatch.setenv("ESCALON_EMBEDDING_DIMENSIONS", "8")
    monkeypatch.setenv("ESCALON_AUTH_MODE", "disabled")
    monkeypatch.setenv("ESCALON_DEV_USER_EMAIL", "d@contoso.test")
    cli.get_settings.cache_clear()
    monkeypatch.setattr("escalon.services.build_index", lambda settings: OneHitIndex())

    cli.main(["search", "printer"])

    assert "0.5000  Printer error | Cause" in capsys.readouterr().out
    cli.get_settings.cache_clear()


def test_fetch_kb_pins_the_commit_and_sparse_checks_out_topics(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ingest, "_git", lambda cwd, *args: calls.append(args))

    root = ingest.fetch_kb(tmp_path / "kb")

    assert root == tmp_path / "kb" / "support"
    assert ("fetch", "--depth", "1", "--filter=blob:none", "origin", ingest.KB_COMMIT) in calls
    sparse = next(c for c in calls if c[:2] == ("sparse-checkout", "set"))
    assert "support/windows-client/" in sparse
