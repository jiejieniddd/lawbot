from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    secret_key: str = Field(
        default="dev-secret-change-me",
        validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY", "secret_key"),
    )
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    database_url: str = "postgresql+psycopg://lawbot:lawbot@localhost:5432/lawbot"
    redis_url: str = "redis://localhost:6379/0"
    seed_admin_email: str = "root"
    seed_admin_password: str = "Aa@123456"
    litellm_model: str = Field(
        default="",
        validation_alias=AliasChoices("LITELLM_MODEL", "LLM_MODEL", "litellm_model"),
    )
    litellm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LITELLM_API_KEY", "LLM_API_KEY", "litellm_api_key"),
    )
    encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices("ENCRYPTION_KEY", "encryption_key"),
    )
    cors_origins: str = (
        "http://localhost:5173,http://localhost:5174,"
        "http://localhost:8080,http://localhost:8081"
    )

    # RAG / import
    retriever_mode: str = Field(default="memory", validation_alias=AliasChoices("RETRIEVER_MODE"))
    retriever_top_k: int = Field(default=5, validation_alias=AliasChoices("RETRIEVER_TOP_K"))
    rrf_k: int = Field(default=60, validation_alias=AliasChoices("RRF_K"))
    rag_memory_dir: str = Field(
        default="data/rag_memory", validation_alias=AliasChoices("RAG_MEMORY_DIR")
    )
    index_backend: str = Field(default="memory", validation_alias=AliasChoices("INDEX_BACKEND"))
    qdrant_url: str = Field(default="http://localhost:6333", validation_alias=AliasChoices("QDRANT_URL"))
    qdrant_collection: str = Field(
        default="lawbot_articles_v1", validation_alias=AliasChoices("QDRANT_COLLECTION")
    )
    opensearch_url: str = Field(
        default="http://localhost:9200", validation_alias=AliasChoices("OPENSEARCH_URL")
    )
    opensearch_index: str = Field(
        default="lawbot_articles_v1", validation_alias=AliasChoices("OPENSEARCH_INDEX")
    )
    import_max_rows: int = Field(default=200, validation_alias=AliasChoices("IMPORT_MAX_ROWS"))
    hf_dataset_id: str = Field(
        default="senry5433/china-effective-laws-regulations",
        validation_alias=AliasChoices("HF_DATASET_ID"),
    )
    embedding_model: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_MODEL"))
    embedding_api_key: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_API_KEY"))
    embedding_api_base: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_BASE"))
    embedding_dim: int = Field(default=384, validation_alias=AliasChoices("EMBEDDING_DIM"))
    embedding_mode: str = Field(default="auto", validation_alias=AliasChoices("EMBEDDING_MODE"))

    upload_dir: str = Field(default="data/uploads/avatars", validation_alias=AliasChoices("UPLOAD_DIR"))
    avatar_max_bytes: int = Field(default=2_097_152, validation_alias=AliasChoices("AVATAR_MAX_BYTES"))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
