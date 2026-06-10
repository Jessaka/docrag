from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # LLM Provider
    LLM_PROVIDER: str = Field("anthropic", env="LLM_PROVIDER")

    # Anthropic
    ANTHROPIC_API_KEY: str = Field(..., env="ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = Field("claude-sonnet-4-20250514", env="ANTHROPIC_MODEL")

    # OpenAI
    OPENAI_API_KEY: str = Field(..., env="OPENAI_API_KEY")
    OPENAI_EMBED_MODEL: str = Field("text-embedding-3-small", env="OPENAI_EMBED_MODEL")

    # Nvidia
    NVIDIA_API_KEY: Optional[str] = Field(None, env="NVIDIA_API_KEY")
    NVIDIA_BASE_URL: str = Field("https://integrate.api.nvidia.com/v1", env="NVIDIA_BASE_URL")
    NVIDIA_MODEL: str = Field("meta/llama-3.3-70b-instruct", env="NVIDIA_MODEL")

    # Gemini
    GEMINI_API_KEY: Optional[str] = Field(None, env="GEMINI_API_KEY")
    GEMINI_MODEL: str = Field("gemini-2.0-flash", env="GEMINI_MODEL")

    # Qdrant
    QDRANT_HOST: str = Field("localhost", env="QDRANT_HOST")
    QDRANT_PORT: int = Field(6333, env="QDRANT_PORT")
    QDRANT_COLLECTION: str = Field("ai_docs", env="QDRANT_COLLECTION")

    # BM25
    BM25_INDEX_PATH: str = Field("data/indexes/bm25_index.pkl", env="BM25_INDEX_PATH")
    DOCS_STORE_PATH: str = Field("data/docs_store.pkl", env="DOCS_STORE_PATH")

    # Reranker
    RERANKER_MODEL: str = Field("cross-encoder/ms-marco-MiniLM-L-6-v2", env="RERANKER_MODEL")
    RERANKER_DEVICE: str = Field("cpu", env="RERANKER_DEVICE")

    # API
    CORS_ALLOWED_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        env="CORS_ALLOWED_ORIGINS"
    )
    MAX_REQUEST_BODY_BYTES: int = Field(10240, env="MAX_REQUEST_BODY_BYTES")
    RATE_LIMIT_ENABLED: bool = Field(False, env="RATE_LIMIT_ENABLED")

    # Cache & Sessions
    USE_REDIS_CACHE: bool = Field(False, env="USE_REDIS_CACHE")
    USE_REDIS_SESSIONS: bool = Field(False, env="USE_REDIS_SESSIONS")
    REDIS_URL: Optional[str] = Field(None, env="REDIS_URL")
    SESSION_TTL_SECONDS: int = Field(3600, env="SESSION_TTL_SECONDS")
    MAX_SESSIONS: int = Field(50, env="MAX_SESSIONS")

    # LLM params
    LLM_TEMPERATURE: float = Field(0.1, env="LLM_TEMPERATURE")
    LLM_MAX_TOKENS: int = Field(1024, env="LLM_MAX_TOKENS")
    LLM_TIMEOUT: int = Field(20, env="LLM_TIMEOUT")
    LLM_MAX_RETRIES: int = Field(1, env="LLM_MAX_RETRIES")

    # Debug & Telemetry
    DEBUG_API_ERRORS: bool = Field(False, env="DEBUG_API_ERRORS")
    TELEMETRY_ENABLED: bool = Field(True, env="TELEMETRY_ENABLED")
    TELEMETRY_LOG_PATH: str = Field("logs/telemetry.jsonl", env="TELEMETRY_LOG_PATH")
    TELEMETRY_QUERY_LOGGING: str = Field("hashed", env="TELEMETRY_QUERY_LOGGING")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

settings = Settings()
