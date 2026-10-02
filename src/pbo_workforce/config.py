"""Application settings loaded from the environment.

Each process loads only the settings, and database credentials, it needs:

* the API (``Settings``) connects as ``pbo_api`` (read-only);
* the importer (``ImportSettings``) connects as ``pbo_import`` (read/write);
* migrations (``MigrationSettings``) connect as the schema owner, and read
  the two role URLs only to set those roles' passwords.

So the API container never holds import or owner credentials, and the
import container never holds the owner's.
"""

import re
from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pbo_workforce.domain.period import QuarterBasis

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class _EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        # .env also holds variables for other processes and tools.
        extra="ignore",
        frozen=True,
    )


class Settings(_EnvSettings):
    """API configuration."""

    # pbo_api role: SELECT on the served tables only.
    database_url: str
    # SHA-256 hex digests of the accepted API keys; never the keys themselves.
    # NoDecode: read as a comma-separated string rather than JSON.
    api_key_hashes: Annotated[frozenset[str], NoDecode] = frozenset()
    # D2: calendar quarters until analysts confirm otherwise.
    quarter_basis: QuarterBasis = QuarterBasis.CALENDAR
    environment: Literal["dev", "prod"] = "prod"
    docs_enabled: bool = False

    @field_validator("api_key_hashes", mode="before")
    @classmethod
    def _split_hashes(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(h.strip().lower() for h in value.split(",") if h.strip())
        return value

    @field_validator("api_key_hashes")
    @classmethod
    def _check_hashes(cls, value: frozenset[str]) -> frozenset[str]:
        for digest in value:
            if not _SHA256_HEX.fullmatch(digest):
                raise ValueError("API_KEY_HASHES must be 64-char SHA-256 hex digests")
        return value

    @model_validator(mode="after")
    def _safe_in_prod(self) -> Self:
        if self.environment == "prod" and self.docs_enabled:
            raise ValueError("DOCS_ENABLED must be false when ENVIRONMENT=prod")
        # Without keys every request would get 401; fail at startup instead.
        if self.environment == "prod" and not self.api_key_hashes:
            raise ValueError("API_KEY_HASHES must be set when ENVIRONMENT=prod")
        return self


class ImportSettings(_EnvSettings):
    """Importer configuration."""

    # pbo_import role: read/write on application tables, no DDL.
    import_database_url: str


class MigrationSettings(_EnvSettings):
    """Migration configuration."""

    # Schema owner: runs DDL and creates the two roles below.
    migrations_database_url: str
    # Migration 0002 sets the roles' passwords from these URLs.
    database_url: str
    import_database_url: str


def _from_environment[T: _EnvSettings](settings_class: type[T]) -> T:
    # pydantic-settings fills the required fields from the environment, which
    # the type checker cannot see. Passing an (empty) keyword mapping tells it
    # the arguments are supplied at runtime. Any: values of mixed field types.
    from_environment: dict[str, Any] = {}
    return settings_class(**from_environment)


@lru_cache
def get_settings() -> Settings:
    """The API's settings, read once from the environment."""
    return _from_environment(Settings)


@lru_cache
def get_import_settings() -> ImportSettings:
    """The importer's settings, read once from the environment."""
    return _from_environment(ImportSettings)


@lru_cache
def get_migration_settings() -> MigrationSettings:
    """The migrations' settings, read once from the environment."""
    return _from_environment(MigrationSettings)
