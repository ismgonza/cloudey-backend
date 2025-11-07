"""System configuration for Cloudey.

This file contains non-secret configuration settings.
For secrets (API keys, encryption keys), use .env file.
"""

import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from backend directory
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


class CacheConfig:
    """Cache system configuration."""
    
    # Redis connection settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Cache TTLs (in seconds)
    # Dashboards are expensive to generate and data doesn't change often
    DASHBOARD_TTL: int = 86400  # 24 hours - full dashboard cache
    COST_DATA_TTL: int = 43200  # 12 hours - cost data is relatively static
    RESOURCE_TTL: int = 21600  # 6 hours - resource inventory (instances, volumes)
    OPTIMIZATION_TTL: int = 43200  # 12 hours - optimization analysis
    PRICING_TTL: int = 86400  # 24 hours - pricing rarely changes
    COMPARTMENT_TTL: int = 86400  # 24 hours - compartment structure is stable


class APIConfig:
    """API server configuration."""
    
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True  # Auto-reload for development
    
    # CORS settings
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative frontend port
    ]


class DatabaseConfig:
    """Database configuration."""
    
    # PostgreSQL settings
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "cloudey")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "cloudey")
    # Password comes from DATABASE_URL or env var (never hardcode!)
    
    # Full connection URL (built from components or override)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgresql://{POSTGRES_USER}:{os.getenv('POSTGRES_PASSWORD', '')}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )


class LoggingConfig:
    """Logging configuration."""
    
    LEVEL: str = "DEBUG"  # DEBUG, INFO, WARNING, ERROR
    FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"


class OCIConfig:
    """OCI-specific configuration."""
    
    # Rate limiting
    CALLS_PER_SECOND: int = 5
    CALLS_PER_MINUTE: int = 100
    
    # Retry configuration
    MAX_RETRIES: int = 3
    RETRY_BACKOFF: float = 2.0  # Exponential backoff multiplier


class LLMConfig:
    """LLM provider configuration."""
    
    DEFAULT_PROVIDER: str = "anthropic"  # or "openai"
    DEFAULT_MODEL: str = "claude-3-5-sonnet-20241022"
    
    # OpenAI models
    OPENAI_MODELS: list[str] = [
        "gpt-4.1-mini",
        "gpt-4-turbo-preview",
        "gpt-4",
        "gpt-3.5-turbo"
    ]
    
    # Anthropic models
    ANTHROPIC_MODELS: list[str] = [
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229"
    ]


# Environment-specific overrides (optional)
ENV = os.getenv("ENVIRONMENT", "development")  # development, staging, production

if ENV == "production":
    LoggingConfig.LEVEL = "INFO"
    APIConfig.RELOAD = False
    CacheConfig.REDIS_HOST = os.getenv("REDIS_HOST", "redis")  # Docker service name
    DatabaseConfig.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")  # Docker service name
elif ENV == "staging":
    LoggingConfig.LEVEL = "INFO"
    CacheConfig.REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    DatabaseConfig.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")

