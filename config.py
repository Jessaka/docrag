"""Configuration module loading environment variables.

All variables are defined in `.env.example`. The application uses
`pydantic.BaseSettings` to read them, providing type hints and default
values where appropriate.
"""

import os
from typing import List, Optional
from pydantic import BaseSettings, Field, validator

class Settings(BaseSettings):
    # LLM - Generation
    ANTHROPIC_API_KEY: str = Field(..., env="ANTHROPIC_API_KEY")

    # Embeddings
    OPENAI_API_KEY: str = Field(..., env="OPENAI_API_KEY")

    # Qdrant
    QDRANT_HOST: str = Field("localhost", env="QDRANT_HOST")
    QDRANT_PORT: int = Field(6333, env="QDRANT_PORT")
    QDRANT_COLLECTION: str = Field("ai_docs", env="QDRANT_COLLECTION")

    # BM25
    BM25_INDEX_PATH: str = Field("data/indexes/bm25_index.pkl", env="BM25_INDEX_PATH")
    DOCS_STORE_PATH: str = Field("data/docs_store.pkl", env="DOCS_STORE_PATH")

    # API
    CORS_ALLOWED_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        env="CORS_ALLOWED_ORIGINS",
    )
    MAX_REQUEST_BODY_BYTES: int = Field(10240, env="MAX_REQUEST_BODY_BYTES")
    RATE_LIMIT_ENABLED: bool = Field(False, env="RATE_LIMIT_ENABLED")

    # Cache
    USE_REDIS_CACHE: bool = Field(False, env="USE_REDIS_CACHE")
    REDIS_URL: Optional[str] = Field(None, env="REDIS_URL")

    # Session
    SESSION_TTL_SECONDS: int = Field(3600, env="SESSION_TTL_SECONDS")
    MAX_SESSIONS: int = Field(50, env="MAX_SESSIONS")

    # Debug
    DEBUG_API_ERRORS: bool = Field(False, env="DEBUG_API_ERRORS")

    # Telemetry
    TELEMETRY_ENABLED: bool = Field(True, env="TELEMETRY_ENABLED")
    TELEMETRY_LOG_PATH: str = Field("logs/telemetry.jsonl", env="TELEMETRY_LOG_PATH")
    TELEMETRY_QUERY_LOGGING: str = Field("hashed", env="TELEMETRY_QUERY_LOGGING")

    @validator("CORS_ALLOWED_ORIGINS", pre=True)
    def split_origins(cls, v: str) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Export a singleton for convenient import
settings = Settings()
