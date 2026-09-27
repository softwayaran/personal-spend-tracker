"""Settings and configuration management."""

from pathlib import Path
from typing import List, Optional
from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings
import yaml


class Settings(BaseSettings):
    """
    Application settings loaded from config.yaml and environment variables.

    Environment variables take precedence over config file values.
    Prefix all env vars with BUDGET_PARSER_ (e.g., BUDGET_PARSER_TODO_FOLDER).
    """

    model_config = ConfigDict(
        env_prefix="BUDGET_PARSER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Folder paths
    todo_folder: str = Field(default="todo", description="Folder containing PDFs to process")
    done_folder: str = Field(default="done", description="Folder for processed PDFs")

    # LLM settings
    llm_model: str = Field(default="gemma4", description="Ollama model name")
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="LLM temperature")
    llm_top_p: float = Field(default=0.2, ge=0.0, le=1.0, description="LLM top_p parameter")
    llm_num_predict: int = Field(default=3000, gt=0, description="Max tokens to generate")

    # Processing settings
    lines_per_chunk: int = Field(default=30, gt=0, description="Lines per PDF chunk")
    enable_regex_fallback: bool = Field(default=True, description="Enable regex fallback extraction")

    # Filter keywords
    rewards_keywords: List[str] = Field(
        default=[
            "points earned", "pts earned", "points", "pts",
            "miles", "cashback", "cash back", "promotional",
            "thank you bonus", "rewards", "bonus points"
        ],
        description="Keywords to filter out rewards transactions"
    )

    payment_keywords: List[str] = Field(
        default=[
            "autopay", "automatic payment", "payment - thank you",
            "remit coupon", "payment received", "thank you"
        ],
        description="Keywords to filter out payment transactions"
    )

    aggregate_keywords: List[str] = Field(
        default=[
            "purchases", "total", "balance", "beginning balance",
            "ending balance", "payment due", "total for"
        ],
        description="Keywords to filter out aggregate/summary lines"
    )

    # Logging settings
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="logs/budget_parser.log", description="Log file path")
    log_max_bytes: int = Field(default=10*1024*1024, description="Max log file size (10MB)")
    log_backup_count: int = Field(default=5, description="Number of log backup files")

    # File movement settings
    move_to_done: bool = Field(default=True, description="Move processed PDFs to done folder")

    # Categorization settings
    categorize_batch_size: int = Field(default=20, gt=0, description="Transactions per LLM call")

    # Web enrichment settings
    web_enrichment_enabled: bool = Field(default=True, description="Enable web search enrichment")
    web_enrichment_delay: float = Field(
        default=1.5, ge=0.0, description="Seconds between DuckDuckGo requests"
    )
    web_enrichment_max_snippets: int = Field(
        default=3, gt=0, description="Number of search results to grab"
    )
    web_enrichment_model: str = Field(
        default="llama3", description="Ollama model for summarizing search results"
    )

    # Laya classification settings
    laya_model: str = Field(
        default="convaiinnovations/laya", description="HuggingFace laya checkpoint"
    )
    laya_confidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Below this confidence, fall back to LLM"
    )
    laya_enabled: bool = Field(
        default=True, description="Use laya for categorization; false reverts to LLM-only"
    )

    # Location categorizer settings
    home_state: str = Field(
        default="MI", description="Two-letter home state/province code for vacation detection"
    )

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> 'Settings':
        """Load settings from YAML file."""
        if not yaml_path.exists():
            # Return default settings if file doesn't exist
            return cls()

        with open(yaml_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f) or {}

        return cls(**config_data)


# Singleton instance
_settings: Optional[Settings] = None


def get_settings(config_path: Optional[Path] = None) -> Settings:
    """
    Get settings singleton instance.

    Args:
        config_path: Optional path to config.yaml file

    Returns:
        Settings instance
    """
    global _settings

    if _settings is None:
        if config_path and config_path.exists():
            _settings = Settings.from_yaml(config_path)
        else:
            # Try default locations
            default_paths = [
                Path("config.yaml"),
                Path("budget_parser/config/default_config.yaml")
            ]

            for path in default_paths:
                if path.exists():
                    _settings = Settings.from_yaml(path)
                    break
            else:
                # Use defaults if no config file found
                _settings = Settings()

    return _settings


def reset_settings():
    """Reset settings singleton (useful for testing)."""
    global _settings
    _settings = None
