from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .config import AppConfig


LOGGER_NAME = "chat_backend"
TRANSCRIPT_LOGGER_NAME = "chat_transcript"
_BASE_LOG_RECORD = logging.makeLogRecord({})
_RESERVED_FIELDS = set(_BASE_LOG_RECORD.__dict__.keys())
_RESERVED_FIELDS.update({"message", "asctime", "event"})


def _normalize_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return str(value)


class PlainTextLogFormatter(logging.Formatter):
    def __init__(self, project_root: Path):
        super().__init__(
            fmt="%(asctime)s:%(filename)s:%(funcName)s:%(lineno)d:%(levelname)s:%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.project_root = project_root

    def format(self, record: logging.LogRecord) -> str:
        base_message = super().format(record)
        extras = []
        event = getattr(record, "event", "")
        if event:
            extras.append(f"event={event}")

        for key, value in record.__dict__.items():
            if key in _RESERVED_FIELDS or key.startswith("_"):
                continue

            normalized_value = _normalize_value(value)
            if key == "pathname":
                normalized_value = self._relative_path(str(normalized_value))
            extras.append(f"{key}={normalized_value}")

        if extras:
            return f"{base_message} | {' '.join(extras)}"
        return base_message

    def _relative_path(self, pathname: str) -> str:
        try:
            return str(Path(pathname).resolve().relative_to(self.project_root))
        except Exception:
            return pathname


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def get_transcript_logger() -> logging.Logger:
    return logging.getLogger(TRANSCRIPT_LOGGER_NAME)


def normalize_log_text(value: object) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str | None = None,
    *,
    exc_info=None,
    stacklevel: int = 1,
    **context,
) -> None:
    if isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)

    logger.log(
        level,
        message or event,
        extra={"event": event, **context},
        exc_info=exc_info,
        stacklevel=stacklevel + 1,
    )


def log_chat_transcript(
    *,
    request_id: str,
    user_message: str,
    assistant_reply: str,
    mode: str,
    reply_lang: str,
    retrieved_chunk_count: int,
) -> None:
    transcript_logger = get_transcript_logger()
    transcript_logger.info(
        "chat transcript"
        f" | request_id={request_id}"
        f" mode={mode}"
        f" reply_lang={reply_lang}"
        f" retrieved_chunk_count={retrieved_chunk_count}"
        f" user={normalize_log_text(user_message)}"
        f" assistant={normalize_log_text(assistant_reply)}",
        stacklevel=2,
    )


def install_exception_hooks(logger: logging.Logger) -> None:
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        log_event(
            logger,
            logging.CRITICAL,
            "uncaught_exception",
            "uncaught exception reached process boundary",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        log_event(
            logger,
            logging.CRITICAL,
            "uncaught_thread_exception",
            "uncaught exception reached thread boundary",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            thread_name=args.thread.name if args.thread else "unknown",
        )

    sys.excepthook = handle_uncaught_exception
    threading.excepthook = handle_thread_exception


def configure_logging(config: AppConfig) -> logging.Logger:
    logger = get_logger()
    transcript_logger = get_transcript_logger()
    if logger.handlers and transcript_logger.handlers:
        return logger

    log_level = getattr(logging, config.log_level, logging.INFO)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    config.transcript_log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = PlainTextLogFormatter(config.project_root)

    logger.setLevel(log_level)
    logger.propagate = False
    transcript_logger.setLevel(logging.INFO)
    transcript_logger.propagate = False

    file_handler = RotatingFileHandler(
        config.log_path,
        maxBytes=max(config.log_max_bytes, 1024),
        backupCount=max(config.log_backup_count, 0),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    transcript_handler = RotatingFileHandler(
        config.transcript_log_path,
        maxBytes=max(config.transcript_log_max_bytes, 1024),
        backupCount=max(config.transcript_log_backup_count, 0),
        encoding="utf-8",
    )
    transcript_handler.setFormatter(formatter)
    transcript_logger.addHandler(transcript_handler)

    if config.log_stdout:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    install_exception_hooks(logger)

    log_event(
        logger,
        logging.INFO,
        "logging_configured",
        "logging configured",
        log_level=logging.getLevelName(log_level),
        log_path=config.log_path,
        log_stdout=config.log_stdout,
        log_max_bytes=max(config.log_max_bytes, 1024),
        log_backup_count=max(config.log_backup_count, 0),
        transcript_log_path=config.transcript_log_path,
        transcript_log_max_bytes=max(config.transcript_log_max_bytes, 1024),
        transcript_log_backup_count=max(config.transcript_log_backup_count, 0),
    )
    return logger
