"""Logging configuration and utilities."""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional


# ANSI color codes for console output
class ColoredFormatter(logging.Formatter):
    """Custom formatter with color-coded log levels."""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        """Format log record with colors."""
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"

        return super().format(record)


def setup_logger(
    name: str = "budget_parser",
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console_output: bool = True
) -> logging.Logger:
    """
    Setup logger with file and console handlers.

    Args:
        name: Logger name
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (if None, only console output)
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup files to keep
        console_output: Whether to output to console

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '%(levelname)s - %(message)s'
    )

    colored_formatter = ColoredFormatter(
        '%(levelname)s - %(message)s'
    )

    # File handler with rotation
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # Capture everything in file
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)

    # Console handler with colors
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))

        # Use colored formatter if terminal supports it
        if sys.stdout.isatty():
            console_handler.setFormatter(colored_formatter)
        else:
            console_handler.setFormatter(simple_formatter)

        logger.addHandler(console_handler)

    return logger


def get_logger(name: str = "budget_parser") -> logging.Logger:
    """
    Get existing logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
