"""Parse Microsoft SupportArticles-docs markdown into searchable chunks.

Articles are split on their ``##`` headings rather than fixed-size windows, because a
troubleshooting article's sections (Symptoms, Cause, Resolution) are the units a person
actually needs. Every chunk carries the article title and section heading so it still
makes sense when retrieved on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

LEARN_BASE_URL = "https://learn.microsoft.com/en-us/troubleshoot/"

# Sections that are boilerplate across the corpus and never answer a user's question.
SKIPPED_SECTIONS = {"data collection", "contact us for help", "third-party information disclaimer"}

NON_ARTICLE_TOPICS = {"landing-page", "hub-page", "toc"}

# Articles are split at this heading level; deeper headings stay inside their section.
SECTION_LEVEL = 2

# Long sections are split on paragraph boundaries to stay well inside embedding limits.
MAX_CHUNK_CHARS = 3000

_FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_IMAGE_BLOCK = re.compile(r":::image\b.*?:::(?:\s*:::image-end:::)?", re.DOTALL)
_INCLUDE = re.compile(r"\[!INCLUDE\s*\[[^\]]*\]\([^)]*\)\]")
_ANCHOR = re.compile(r"<a name=[^>]*>\s*(</a>)?", re.IGNORECASE)
_ALERT = re.compile(r"^>\s*\[!(NOTE|IMPORTANT|TIP|WARNING|CAUTION)\]\s*$", re.MULTILINE)
_DIV = re.compile(r"^>\s*\[!div[^\]]*\]\s*$", re.MULTILINE)
_NO_LOC = re.compile(r':::no-loc\s+text="([^"]*)":::')
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


@dataclass(frozen=True)
class Article:
    id: str  # path under support/ without extension, e.g. "windows-client/printing/foo"
    title: str
    description: str
    url: str
    updated: str  # ms.date as written in the article (MM/DD/YYYY)
    body: str


@dataclass(frozen=True)
class Chunk:
    id: str  # "<article id>#<n>"
    article_id: str
    title: str
    section: str
    url: str
    text: str  # what gets embedded and shown to the model


class NotAnArticleError(ValueError):
    """Raised for landing pages, TOCs and other files that are not troubleshooting content."""


def article_url(article_id: str) -> str:
    return LEARN_BASE_URL + article_id


def parse_article(path: Path, support_root: Path) -> Article:
    raw = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise NotAnArticleError(f"{path}: no front matter")
    meta = yaml.safe_load(match.group(1)) or {}
    # Many Intune and Entra articles have no ms.topic at all, so only known non-article
    # topics are rejected.
    if meta.get("ms.topic") in NON_ARTICLE_TOPICS or not meta.get("title"):
        raise NotAnArticleError(f"{path}: ms.topic={meta.get('ms.topic')!r}")

    article_id = path.relative_to(support_root).with_suffix("").as_posix()
    body = clean_markdown(raw[match.end() :])
    return Article(
        id=article_id,
        title=str(meta.get("title", "")).strip(),
        description=str(meta.get("description", "")).strip(),
        url=article_url(article_id),
        updated=str(meta.get("ms.date", "")),
        body=body,
    )


def clean_markdown(text: str) -> str:
    """Remove docs-platform markup that means nothing outside learn.microsoft.com."""
    text = _IMAGE_BLOCK.sub("", text)
    text = _INCLUDE.sub("", text)
    text = _ANCHOR.sub("", text)
    text = _NO_LOC.sub(r"\1", text)
    text = _DIV.sub("", text)
    text = _ALERT.sub(lambda m: f"> **{m.group(1).capitalize()}:**", text)
    text = text.replace("&nbsp;", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_article(article: Article) -> list[Chunk]:
    sections = _split_sections(article.body)
    chunks: list[Chunk] = []
    for heading, content in sections:
        if heading.lower() in SKIPPED_SECTIONS or not content.strip():
            continue
        for piece in _split_long(content):
            header = f"{article.title}\nSection: {heading}\n\n"
            chunks.append(
                Chunk(
                    id=f"{article.id}#{len(chunks)}",
                    article_id=article.id,
                    title=article.title,
                    section=heading,
                    url=article.url,
                    text=header + piece.strip(),
                )
            )
    return chunks


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split on level-1/2 headings; deeper headings stay inside their parent section."""
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        heading = None if in_code else _HEADING.match(line)
        if heading and len(heading.group(1)) == 1:
            continue  # the H1 duplicates the title, which every chunk already carries
        if heading and len(heading.group(1)) == SECTION_LEVEL:
            sections.append((heading.group(2), []))
        else:
            sections[-1][1].append(line)
    return [(name, "\n".join(lines).strip()) for name, lines in sections]


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    pieces: list[str] = []
    current = ""
    for para in _paragraphs(text):
        if current and len(current) + len(para) + 2 > MAX_CHUNK_CHARS:
            pieces.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces


def _paragraphs(text: str) -> list[str]:
    """Paragraphs, with any single paragraph over the limit (big tables, logs) cut by line."""
    out: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        rest = paragraph
        while len(rest) > MAX_CHUNK_CHARS:
            cut = rest.rfind("\n", 0, MAX_CHUNK_CHARS)
            cut = cut if cut > 0 else MAX_CHUNK_CHARS
            out.append(rest[:cut])
            rest = rest[cut:].lstrip("\n")
        out.append(rest)
    return out


def load_corpus(support_root: Path, topics: list[str]) -> tuple[list[Article], list[Path]]:
    """Return parsed articles under the given topic folders, plus the files that were skipped."""
    articles: list[Article] = []
    skipped: list[Path] = []
    for topic in topics:
        topic_dir = support_root / topic
        if not topic_dir.is_dir():
            raise FileNotFoundError(f"topic folder not found: {topic_dir}")
        for path in sorted(topic_dir.rglob("*.md")):
            if not path.is_file() or "media" in path.relative_to(topic_dir).parts:
                continue
            try:
                articles.append(parse_article(path, support_root))
            except NotAnArticleError:
                skipped.append(path)
    return articles, skipped
