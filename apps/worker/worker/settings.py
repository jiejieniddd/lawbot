from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://lawbot:lawbot@localhost:5432/lawbot"
    worker_poll_seconds: int = 5
    import_max_rows: int = Field(default=200, validation_alias=AliasChoices("IMPORT_MAX_ROWS", "import_max_rows"))
    hf_dataset_id: str = Field(
        default="senry5433/china-effective-laws-regulations",
        validation_alias=AliasChoices("HF_DATASET_ID", "hf_dataset_id"),
    )
    index_backend: str = Field(default="memory", validation_alias=AliasChoices("INDEX_BACKEND", "index_backend"))
    rag_memory_dir: str = Field(
        default="data/rag_memory",
        validation_alias=AliasChoices("RAG_MEMORY_DIR", "rag_memory_dir"),
    )
    qdrant_url: str = Field(default="http://localhost:6333", validation_alias=AliasChoices("QDRANT_URL"))
    opensearch_url: str = Field(default="http://localhost:9200", validation_alias=AliasChoices("OPENSEARCH_URL"))
    qdrant_collection: str = "lawbot_articles_v1"
    opensearch_index: str = "lawbot_articles_v1"
    embedding_model: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_MODEL"))
    embedding_api_key: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_API_KEY"))
    embedding_api_base: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_BASE"))
    embedding_dim: int = Field(default=384, validation_alias=AliasChoices("EMBEDDING_DIM"))
    embedding_mode: str = Field(default="auto", validation_alias=AliasChoices("EMBEDDING_MODE"))


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
