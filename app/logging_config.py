"""Logging configuration for the backend application."""

import logging
import sys
from datetime import datetime


def setup_logging(level: str = "INFO"):
    """Configure logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Create formatter with timestamps
    formatter = logging.Formatter(
        fmt='%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-30s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set specific loggers to appropriate levels
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce access log noise
    logging.getLogger("httpx").setLevel(logging.WARNING)  # Reduce HTTP client noise
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    # Set our application loggers to DEBUG
    logging.getLogger("app").setLevel(logging.DEBUG)
    logging.getLogger("app.cloud").setLevel(logging.DEBUG)
    logging.getLogger("app.agents").setLevel(logging.DEBUG)
    
    logging.info(f"Logging configured at {level.upper()} level")

