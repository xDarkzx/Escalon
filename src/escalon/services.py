"""Builds the configured search index for a profile."""

from __future__ import annotations

from azure.identity.aio import DefaultAzureCredential

from escalon.azure_search import AzureSearchIndex
from escalon.config import Profile, Settings
from escalon.models import Embedder, openai_client
from escalon.search import LocalIndex, SearchIndex


def build_index(settings: Settings) -> SearchIndex:
    embedder = Embedder.from_settings(openai_client(settings), settings)
    if settings.profile is Profile.AZURE:
        return AzureSearchIndex(
            settings.required("azure_search_endpoint"),
            settings.azure_search_index,
            DefaultAzureCredential(),
            embedder,
        )
    return LocalIndex(settings.local_index_path, embedder)
