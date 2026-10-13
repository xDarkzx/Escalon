import hashlib
import re
from collections.abc import Sequence

import numpy as np
import pytest

from escalon.kb import Chunk


class HashingEmbedder:
    """Deterministic bag-of-words embedder so search tests need no model server."""

    dimensions = 64

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for word in re.findall(r"\w+", text.lower()):
            vector[int(hashlib.blake2b(word.encode(), digest_size=8).hexdigest(), 16) % self.dimensions] += (
                1.0
            )
        vector[0] += 0.01  # never all-zero
        return vector.tolist()


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


def make_chunk(article_id: str, n: int, title: str, text: str, section: str = "Resolution") -> Chunk:
    return Chunk(
        id=f"{article_id}#{n}",
        article_id=article_id,
        title=title,
        section=section,
        url=f"https://learn.microsoft.com/en-us/troubleshoot/{article_id}",
        text=f"{title}\nSection: {section}\n\n{text}",
    )
