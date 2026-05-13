"""Configuration for Trace2Quality"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables"""

    # === Application ===
    app_env: str = "development"
    app_debug: bool = True
    app_workers: int = 4
    app_port: int = 8000

    # === Security ===
    app_encryption_key: str = "dev-encryption-key-change-in-production"
    app_secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # === Database ===
    database_url: str = "sqlite:///./data/trace2quality.db"

    # === Redis ===
    redis_url: str = "redis://localhost:6379/0"

    # === Celery ===
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # === Azure DevOps ===
    azure_devops_org_url: str = "https://dev.azure.com/yourorg"
    azure_devops_project: str = "YourProject"
    azure_devops_pat: str = ""

    # === Confluence ===
    confluence_base_url: str = "https://yourdomain.atlassian.net/wiki"
    confluence_space: str = "YOURSPACE"
    confluence_email: str = ""
    confluence_api_token: str = ""

    # === Jira ===
    jira_base_url: str = "https://yourdomain.atlassian.net"
    jira_email: str = ""
    jira_api_token: str = ""

    # === Gemini ===
    gemini_api_key: str = ""
    gemini_model: str = "gemini-pro"

    # === Logging ===
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"

    # === Storage ===
    artifact_storage_path: str = "./data/artifacts"
    cache_storage_path: str = "./data/cache"

    # === Features ===
    feature_data_migration: bool = True
    feature_webhook_sync: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
