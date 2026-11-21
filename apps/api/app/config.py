from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/config.py -> repo root (LawBot/)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILES = (
    str(_REPO_ROOT / ".env"),
    ".env",  # cwd override (e.g. apps/api/.env) wins if present
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
    llm_timeout_seconds: float = Field(
        default=60.0,
        validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS", "llm_timeout_seconds"),
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
    retrieve_min_score: float = Field(
        default=0.6, validation_alias=AliasChoices("RETRIEVE_MIN_SCORE", "retrieve_min_score")
    )
    agent_max_followups: int = Field(
        default=2, validation_alias=AliasChoices("AGENT_MAX_FOLLOWUPS", "agent_max_followups")
    )
    agent_history_rounds: int = Field(
        default=6, validation_alias=AliasChoices("AGENT_HISTORY_ROUNDS", "agent_history_rounds")
    )
    agent_trace_dir: str = Field(
        default="data/agent_traces",
        validation_alias=AliasChoices("AGENT_TRACE_DIR", "agent_trace_dir"),
    )
    langfuse_host: str = Field(default="", validation_alias=AliasChoices("LANGFUSE_HOST", "langfuse_host"))
    langfuse_public_key: str = Field(
        default="", validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "langfuse_public_key")
    )
    langfuse_secret_key: str = Field(
        default="", validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "langfuse_secret_key")
    )
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
        default="data/hf/Chinese_interview_large",
        validation_alias=AliasChoices("HF_DATASET_ID"),
    )
    embedding_model: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_MODEL"))
    embedding_api_key: str = Field(default="", validation_alias=AliasChoices("EMBEDDING_API_KEY"))
    embedding_api_base: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_BASE"))
    embedding_dim: int = Field(default=384, validation_alias=AliasChoices("EMBEDDING_DIM"))
    embedding_mode: str = Field(default="auto", validation_alias=AliasChoices("EMBEDDING_MODE"))

    upload_dir: str = Field(default="data/uploads/avatars", validation_alias=AliasChoices("UPLOAD_DIR"))
    avatar_max_bytes: int = Field(default=2_097_152, validation_alias=AliasChoices("AVATAR_MAX_BYTES"))
    resume_upload_dir: str = Field(
        default="data/uploads/resumes",
        validation_alias=AliasChoices("RESUME_UPLOAD_DIR", "resume_upload_dir"),
    )
    resume_max_bytes: int = Field(
        default=8_388_608,
        validation_alias=AliasChoices("RESUME_MAX_BYTES", "resume_max_bytes"),
    )
    jd_upload_dir: str = Field(
        default="data/uploads/jds",
        validation_alias=AliasChoices("JD_UPLOAD_DIR", "jd_upload_dir"),
    )
    jd_max_bytes: int = Field(
        default=8_388_608,
        validation_alias=AliasChoices("JD_MAX_BYTES", "jd_max_bytes"),
    )
    rag_self_test_dir: str = Field(
        default="data/rag_memory_self_test",
        validation_alias=AliasChoices("RAG_SELF_TEST_DIR", "rag_self_test_dir"),
    )

    # Mail / password reset. Used only when mail_settings has no saved row.
    mail_enabled: bool = Field(default=False, validation_alias=AliasChoices("MAIL_ENABLED", "mail_enabled"))
    smtp_host: str = Field(default="", validation_alias=AliasChoices("SMTP_HOST", "smtp_host"))
    smtp_port: int = Field(default=587, validation_alias=AliasChoices("SMTP_PORT", "smtp_port"))
    smtp_security: str = Field(
        default="starttls", validation_alias=AliasChoices("SMTP_SECURITY", "smtp_security")
    )
    smtp_username: str = Field(default="", validation_alias=AliasChoices("SMTP_USERNAME", "smtp_username"))
    smtp_password: str = Field(default="", validation_alias=AliasChoices("SMTP_PASSWORD", "smtp_password"))
    smtp_from_address: str = Field(
        default="", validation_alias=AliasChoices("SMTP_FROM_ADDRESS", "smtp_from_address")
    )
    smtp_from_name: str = Field(
        default="LawBot", validation_alias=AliasChoices("SMTP_FROM_NAME", "smtp_from_name")
    )
    password_reset_ttl_minutes: int = Field(
        default=10, validation_alias=AliasChoices("PASSWORD_RESET_TTL_MINUTES", "password_reset_ttl_minutes")
    )
    password_reset_resend_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("PASSWORD_RESET_RESEND_SECONDS", "password_reset_resend_seconds"),
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def resolved_rag_memory_dir(self) -> str:
        from lawbot.paths import resolve_rag_memory_dir

        return str(resolve_rag_memory_dir(self.rag_memory_dir))


@lru_cache
def get_settings() -> Settings:
    return Settings()
