"""Fetch the pinned knowledge-base snapshot and index it."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from escalon.kb import chunk_article, load_corpus
from escalon.search import SearchIndex

log = logging.getLogger(__name__)

KB_REPO = "https://github.com/MicrosoftDocs/SupportArticles-docs.git"
# Pinned so retrieval and eval results are reproducible. Bump deliberately and re-run evals.
KB_COMMIT = "e6a2ec057ed493f9ab9fde7025b52cad4f01b12c"
KB_TOPICS = ["windows-client", "entra/entra-id/mfa", "mem/intune"]


def fetch_kb(dest: Path, commit: str = KB_COMMIT) -> Path:
    """Sparse-checkout only the topic folders at the pinned commit. Returns the support/ root."""
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)
        _git(dest, "init", "-q")
        _git(dest, "remote", "add", "origin", KB_REPO)
        _git(dest, "config", "core.sparseCheckout", "true")
        _git(dest, "sparse-checkout", "set", "--no-cone", *[f"support/{t}/" for t in KB_TOPICS])
    _git(dest, "fetch", "--depth", "1", "--filter=blob:none", "origin", commit)
    _git(dest, "checkout", "-q", "--detach", "FETCH_HEAD")
    return dest / "support"


def _git(cwd: Path, *args: str) -> None:
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("git is required to fetch the knowledge base")
    subprocess.run([git, *args], cwd=cwd, check=True)  # noqa: S603 - fixed arguments, no shell


async def ingest(support_root: Path, index: SearchIndex, batch_size: int = 128) -> int:
    articles, skipped = load_corpus(support_root, KB_TOPICS)
    chunks = [chunk for article in articles for chunk in chunk_article(article)]
    log.info(
        "%d articles (%d non-article files skipped) -> %d chunks", len(articles), len(skipped), len(chunks)
    )
    for start in range(0, len(chunks), batch_size):
        await index.upsert(chunks[start : start + batch_size])
        log.info("indexed %d/%d", min(start + batch_size, len(chunks)), len(chunks))
    return len(chunks)
