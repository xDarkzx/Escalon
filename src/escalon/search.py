"""Hybrid (keyword + vector) search over knowledge-base chunks.

Both implementations do the same thing: BM25 keyword ranking and vector similarity ranking,
fused with reciprocal rank fusion. Keyword search matters here because users paste exact
error codes ("0x0000052e", "AADSTS50076") that embeddings blur together.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from escalon.kb import Chunk
from escalon.models import Embedder

RRF_K = 60  # standard reciprocal-rank-fusion constant; also what Azure AI Search uses
CANDIDATES_PER_RANKER = 50
# One article's Symptoms/Cause/Resolution chunks otherwise crowd out every other candidate.
MAX_CHUNKS_PER_ARTICLE = 2


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    article_id: str
    title: str
    section: str
    url: str
    text: str
    score: float


class SearchIndex(Protocol):
    async def search(self, query: str, top_k: int) -> list[Hit]: ...

    async def upsert(self, chunks: Sequence[Chunk]) -> None: ...


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 OR-query of quoted terms."""
    terms = {t.lower() for t in re.findall(r"[\w.-]+", text) if len(t) > 1}
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in sorted(terms))


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return scores


def diversify(ranked: Iterable[Hit], top_k: int, per_article: int = MAX_CHUNKS_PER_ARTICLE) -> list[Hit]:
    taken: dict[str, int] = {}
    out: list[Hit] = []
    for hit in ranked:
        if taken.get(hit.article_id, 0) < per_article:
            taken[hit.article_id] = taken.get(hit.article_id, 0) + 1
            out.append(hit)
            if len(out) == top_k:
                break
    return out


class LocalIndex:
    """SQLite FTS5 for BM25 plus an in-memory matrix of normalised vectors."""

    def __init__(self, path: Path, embedder: Embedder) -> None:
        self._embedder = embedder
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                rowid INTEGER PRIMARY KEY,
                id TEXT UNIQUE NOT NULL,
                article_id TEXT NOT NULL,
                title TEXT NOT NULL,
                section TEXT NOT NULL,
                url TEXT NOT NULL,
                text TEXT NOT NULL,
                vector BLOB NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                title, section, text, content='chunks', content_rowid='rowid',
                tokenize = "unicode61 tokenchars '.-'"
            );
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, title, section, text)
                VALUES (new.rowid, new.title, new.section, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, title, section, text)
                VALUES ('delete', old.rowid, old.title, old.section, old.text);
            END;
            """
        )
        self._load_vectors()

    def _load_vectors(self) -> None:
        rows = self._db.execute("SELECT id, vector FROM chunks ORDER BY rowid").fetchall()
        self._ids = [r[0] for r in rows]
        if rows:
            self._matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        else:
            self._matrix = np.zeros((0, self._embedder.dimensions), dtype=np.float32)

    def __len__(self) -> int:
        return len(self._ids)

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        vectors = await self._embedder.embed_documents([c.text for c in chunks])
        with self._db:
            for chunk, vector in zip(chunks, vectors, strict=True):
                self._db.execute("DELETE FROM chunks WHERE id = ?", (chunk.id,))
                self._db.execute(
                    "INSERT INTO chunks (id, article_id, title, section, url, text, vector) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        chunk.article_id,
                        chunk.title,
                        chunk.section,
                        chunk.url,
                        chunk.text,
                        _normalise(vector).tobytes(),
                    ),
                )
        self._load_vectors()

    async def search(self, query: str, top_k: int) -> list[Hit]:
        keyword_ids = self._keyword_ranking(query)
        vector_ids = await self._vector_ranking(query)
        fused = reciprocal_rank_fusion([keyword_ids, vector_ids])
        ranked = sorted(fused, key=fused.__getitem__, reverse=True)
        return diversify((self._hit(chunk_id, fused[chunk_id]) for chunk_id in ranked), top_k)

    def _keyword_ranking(self, query: str) -> list[str]:
        match = fts_query(query)
        if match is None:
            return []
        rows = self._db.execute(
            "SELECT c.id FROM chunks_fts f JOIN chunks c ON c.rowid = f.rowid "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 4.0, 2.0, 1.0) LIMIT ?",
            (match, CANDIDATES_PER_RANKER),
        ).fetchall()
        return [r[0] for r in rows]

    async def _vector_ranking(self, query: str) -> list[str]:
        if not self._ids:
            return []
        query_vector = _normalise(await self._embedder.embed_query(query))
        similarities = self._matrix @ query_vector
        order = np.argsort(-similarities)[:CANDIDATES_PER_RANKER]
        return [self._ids[i] for i in order]

    def _hit(self, chunk_id: str, score: float) -> Hit:
        row = self._db.execute(
            "SELECT id, article_id, title, section, url, text FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"chunk {chunk_id} was ranked but is missing from the index")
        chunk, article_id, title, section, url, text = row
        return Hit(chunk, article_id, title, section, url, text, score=score)


def _normalise(vector: Sequence[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise ValueError("embedding model returned a zero vector")
    return array / norm
