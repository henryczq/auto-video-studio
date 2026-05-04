"""Bilibili Web Upload Logger."""

import sys
from pathlib import Path
from loguru import logger

from conf import BASE_DIR, LOG_DIR


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def log_formatter(record: dict) -> str:
    colors = {
        "TRACE": "#cfe2f3",
        "INFO": "#9cbfdd",
        "DEBUG": "#8598ea",
        "WARNING": "#dcad5a",
        "SUCCESS": "#3dd08d",
        "ERROR": "#ae2c2c"
    }
    color = colors.get(record["level"].name, "#b3cfe7")
    return f"<fg #70acde>{{time:YYYY-MM-DD HH:mm:ss}}</fg #70acde> | <fg {color}>{{level}}</fg {color}>: <light-white>{{message}}</light-white>\n"


def create_logger(log_name: str, file_path: str):
    def filter_record(record):
        return record["extra"].get("business_name") == log_name

    LOG_DIR.mkdir(exist_ok=True)
    logger.add(
        LOG_DIR / file_path,
        filter=filter_record,
        level="INFO",
        rotation="10 MB",
        retention="10 days",
        backtrace=True,
        diagnose=True
    )
    return logger.bind(business_name=log_name)


# Remove all existing handlers
logger.remove()
# Add console handler
logger.add(sys.stdout, colorize=True, format=log_formatter)

# Create logger instance
bilibili_web_logger = create_logger('bilibili_web', 'bilibili_web.log')
