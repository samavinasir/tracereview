from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    openrouter_api_key: str = ""
    openrouter_fallback_model: str = "openrouter/free"
    ncbi_api_key: str = ""
    contact_email: str = ""
    semantic_scholar_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "openai/gpt-oss-20b"
    groq_screening_model: str = "openai/gpt-oss-20b"
    database_url: str
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_results_per_source: int = Field(default=5, ge=1, le=100)
    max_queries_per_round: int = Field(default=6, ge=1, le=30)
    max_records_per_search_round: int = Field(default=10, ge=5, le=300)
    max_records_per_research_run: int = Field(default=10, ge=5, le=100)
    max_papers_per_review: int = Field(default=10, ge=1, le=10)
    min_abstract_chars: int = Field(default=200, ge=0, le=2000)
    min_papers_per_review: int = Field(default=3, ge=1, le=10)
    paper_digest_batch_size: int = Field(default=2, ge=1, le=5)
    extraction_batch_size: int = Field(default=2, ge=1, le=5)
    screening_batch_size: int = Field(default=5, ge=1, le=30)
    max_search_rounds: int = Field(default=2, ge=1, le=3)
    max_fulltext_sources: int = Field(default=15, ge=0, le=50)
    retrieval_concurrency: int = Field(default=8, ge=1, le=16)
    max_source_text_chars: int = Field(default=1400, ge=100, le=4000)
    groq_max_retries: int = Field(default=3, ge=0, le=8)
    groq_retry_base_seconds: float = Field(default=2, ge=0.5, le=30)
    groq_max_retry_wait_seconds: float = Field(default=5, gt=0, le=90)
    groq_tpm_budget: int = Field(default=6000, ge=1000, le=250000)
    groq_max_completion_tokens: int = Field(default=4096, ge=128, le=8192)
    paper_digest_max_completion_tokens: int = Field(default=1200, ge=128, le=4096)
    groq_max_concurrency: int = Field(default=1, ge=1, le=2)
    groq_reasoning_effort: str = "low"
    request_timeout_seconds: float = Field(default=20, gt=0, le=120)
    research_rate_limit_requests: int = Field(default=5, ge=1, le=100)
    research_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
