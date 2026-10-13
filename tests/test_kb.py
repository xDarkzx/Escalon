from pathlib import Path

import pytest

from escalon.kb import (
    MAX_CHUNK_CHARS,
    Article,
    NotAnArticleError,
    chunk_article,
    clean_markdown,
    load_corpus,
    parse_article,
)

SUPPORT = Path(__file__).parent / "fixtures" / "support"
PRINTER_ERROR = SUPPORT / "windows-client/printing/error-message-0x0000052e-install-network-printer.md"


def test_parse_article_reads_metadata_and_public_url():
    article = parse_article(PRINTER_ERROR, SUPPORT)

    assert article.id == "windows-client/printing/error-message-0x0000052e-install-network-printer"
    assert article.title == "Error message when you try to install a network printer in Windows 7"
    assert article.url == (
        "https://learn.microsoft.com/en-us/troubleshoot/windows-client/printing/"
        "error-message-0x0000052e-install-network-printer"
    )
    assert article.updated == "02/12/2026"


def test_landing_pages_are_rejected():
    with pytest.raises(NotAnArticleError):
        parse_article(SUPPORT / "windows-client/printing/landing.md", SUPPORT)


def test_chunks_follow_sections_and_drop_boilerplate():
    chunks = chunk_article(parse_article(PRINTER_ERROR, SUPPORT))
    sections = [c.section for c in chunks]

    assert sections == ["Overview", "Symptoms", "Cause", "Workaround", "More Information"]
    workaround = chunks[sections.index("Workaround")]
    # Sub-headings stay inside their parent section so both workarounds are retrieved together.
    assert "Workaround 1" in workaround.text
    assert "Workaround 2" in workaround.text
    assert workaround.text.startswith(
        "Error message when you try to install a network printer in Windows 7\nSection: Workaround"
    )
    assert all(c.id.startswith(c.article_id + "#") for c in chunks)


def test_clean_markdown_strips_docs_platform_markup():
    raw = (
        ':::image type="content" source="media/x.png" alt-text="Screenshot.":::\n'
        "[!INCLUDE [Registry important alert](../../includes/registry-important-alert.md)]\n"
        '<a name="method1"></a>\n'
        "> [!NOTE]\n> Restart the spooler.\n"
    )
    assert clean_markdown(raw) == "> **Note:**\n> Restart the spooler."


def test_load_corpus_reports_skipped_files():
    articles, skipped = load_corpus(SUPPORT, ["windows-client/printing"])

    assert len(articles) == 2
    assert [p.name for p in skipped] == ["landing.md"]


def test_load_corpus_fails_loudly_on_missing_topic():
    with pytest.raises(FileNotFoundError):
        load_corpus(SUPPORT, ["windows-client/not-a-topic"])


def test_long_sections_split_on_paragraphs_and_oversized_blocks_by_line():
    table = "\n".join(f"| row {i} | {'x' * 60} |" for i in range(80))  # one ~5.6k-char paragraph
    body = "## Resolution\n\n" + "\n\n".join(["Step text. " * 40] * 6) + "\n\n" + table
    article = Article("t/a", "Title", "", "https://x", "01/01/2026", body)

    chunks = chunk_article(article)

    assert len(chunks) > 2
    assert all(len(c.text.split("\n\n", 1)[1]) <= MAX_CHUNK_CHARS for c in chunks)
    joined = "".join(c.text for c in chunks)
    assert "row 0 |" in joined
    assert "row 79 |" in joined


def test_code_fences_hide_heading_lookalikes():
    body = "## Resolution\n\n```console\n## not a heading\n```\n\n## Cause\n\nreal"
    sections = [c.section for c in chunk_article(Article("t/a", "T", "", "u", "", body))]

    assert sections == ["Resolution", "Cause"]
