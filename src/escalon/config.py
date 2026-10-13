"""Runtime settings.

``ESCALON_PROFILE`` picks the backing services explicitly:

* ``azure`` - Azure OpenAI + Azure AI Search, authenticated with Entra ID (no keys).
* ``local`` - an OpenAI-compatible local server (Ollama) + an on-disk index.

A profile with missing settings is a startup error. Nothing falls back to the other profile.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(StrEnum):
    AZURE = "azure"
    LOCAL = "local"


class AuthMode(StrEnum):
    ENTRA = "entra"
    DISABLED = "disabled"  # local development only; logged loudly at startup


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ESCALON_", env_file=".env", extra="ignore")

    profile: Profile

    # Models. In the azure profile these are deployment names.
    chat_model: str
    embedding_model: str
    embedding_dimensions: int
    # Some embedding models (nomic-embed-text) are trained with task prefixes; Azure's are not.
    embedding_query_prefix: str = ""
    embedding_document_prefix: str = ""

    # azure profile
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_search_endpoint: str | None = None
    azure_search_index: str = "escalon-kb"

    # local profile
    local_openai_base_url: str | None = None
    local_index_path: Path = Path("data/index.sqlite")

    # Ticketing
    zammad_url: str | None = None
    zammad_token: str | None = None
    zammad_group: str = "Users"

    # Inbound auth for the MCP server and API
    auth_mode: AuthMode = AuthMode.ENTRA
    entra_tenant_id: str | None = None
    entra_audience: str | None = None  # the app ID URI or client ID clients request tokens for
    public_url: str = "http://localhost:8000"  # where clients reach this server; the OAuth resource id
    dev_user_email: str | None = None  # identity used when auth_mode=disabled

    # Sampling temperature; unset keeps the model's default.
    temperature: float | None = None

    # Retrieval
    search_top_k: int = 5

    @model_validator(mode="after")
    def _check_profile(self) -> Settings:
        required = {
            Profile.AZURE: ["azure_openai_endpoint", "azure_search_endpoint"],
            Profile.LOCAL: ["local_openai_base_url"],
        }[self.profile]
        if self.auth_mode is AuthMode.ENTRA:
            required = [*required, "entra_tenant_id", "entra_audience"]
        else:
            required = [*required, "dev_user_email"]
        missing = [f"ESCALON_{name.upper()}" for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(f"profile {self.profile.value!r} requires: {', '.join(missing)}")
        return self

    def required(self, name: str) -> str:
        """A setting the validator guarantees for this profile; fails loudly if that's ever untrue."""
        value = getattr(self, name)
        if not value:
            raise ValueError(f"ESCALON_{name.upper()} is not set")
        return str(value)

    def require_zammad(self) -> tuple[str, str]:
        if not (self.zammad_url and self.zammad_token):
            raise ValueError("ticketing requires ESCALON_ZAMMAD_URL and ESCALON_ZAMMAD_TOKEN")
        return self.zammad_url, self.zammad_token


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # populated from the environment
