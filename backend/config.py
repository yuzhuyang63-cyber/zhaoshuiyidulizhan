from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "kb" / "generated" / "manual_chunks.jsonl"
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "kb" / "generated" / "product_catalog.json"
DEFAULT_FAQ_PATH = PROJECT_ROOT / "kb" / "generated" / "faq_seed.jsonl"
DEFAULT_INQUIRY_DIR = PROJECT_ROOT / "data" / "inquiries"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "chat-backend.log"
DEFAULT_TRANSCRIPT_LOG_PATH = PROJECT_ROOT / "logs" / "chat-transcript.log"


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ[key] = value


def get_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def get_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


def get_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default

    try:
        return float(raw_value)
    except ValueError:
        return default


def get_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default
    return raw_value not in {"0", "false", "no", "off"}


def resolve_path(raw_path: str, default_path: Path) -> Path:
    path = Path(raw_path.strip()) if raw_path.strip() else default_path
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    chunks_path: Path
    catalog_path: Path
    faq_path: Path
    inquiry_dir: Path
    log_path: Path
    transcript_log_path: Path
    log_level: str
    log_stdout: bool
    log_max_bytes: int
    log_backup_count: int
    transcript_log_max_bytes: int
    transcript_log_backup_count: int
    rag_top_k: int
    rag_max_context_chars: int
    rag_min_score: float
    host: str
    port: int
    deepseek_model: str
    deepseek_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_to: tuple[str, ...]
    smtp_use_ssl: bool
    smtp_use_tls: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            project_root=PROJECT_ROOT,
            chunks_path=resolve_path(os.getenv("RAG_CHUNKS_PATH", ""), DEFAULT_CHUNKS_PATH),
            catalog_path=resolve_path(os.getenv("RAG_CATALOG_PATH", ""), DEFAULT_CATALOG_PATH),
            faq_path=resolve_path(os.getenv("RAG_FAQ_PATH", ""), DEFAULT_FAQ_PATH),
            inquiry_dir=resolve_path(os.getenv("INQUIRY_DIR", ""), DEFAULT_INQUIRY_DIR),
            log_path=resolve_path(os.getenv("CHAT_LOG_PATH", ""), DEFAULT_LOG_PATH),
            transcript_log_path=resolve_path(
                os.getenv("CHAT_TRANSCRIPT_LOG_PATH", ""),
                DEFAULT_TRANSCRIPT_LOG_PATH,
            ),
            log_level=os.getenv("CHAT_LOG_LEVEL", "INFO").strip().upper() or "INFO",
            log_stdout=get_bool_env("CHAT_LOG_STDOUT", True),
            log_max_bytes=get_int_env("CHAT_LOG_MAX_BYTES", 5 * 1024 * 1024),
            log_backup_count=get_int_env("CHAT_LOG_BACKUP_COUNT", 5),
            transcript_log_max_bytes=get_int_env("CHAT_TRANSCRIPT_LOG_MAX_BYTES", 5 * 1024 * 1024),
            transcript_log_backup_count=get_int_env("CHAT_TRANSCRIPT_LOG_BACKUP_COUNT", 5),
            rag_top_k=get_int_env("RAG_TOP_K", 5),
            rag_max_context_chars=get_int_env("RAG_MAX_CONTEXT_CHARS", 4200),
            rag_min_score=get_float_env("RAG_MIN_SCORE", 6.0),
            host=os.getenv("CHAT_SERVER_HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1").strip()
            or "127.0.0.1",
            port=get_int_env("CHAT_SERVER_PORT", get_int_env("PORT", 8000)),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat",
            deepseek_base_url=get_env_value(
                "DEEPSEEK_BASE_URL",
                "OPENAI_BASE_URL",
                default="https://api.deepseek.com",
            ),
            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=get_int_env("SMTP_PORT", 465),
            smtp_user=os.getenv("SMTP_USER", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
            smtp_from=get_env_value("SMTP_FROM", "SMTP_USER"),
            smtp_to=tuple(
                item.strip()
                for item in os.getenv("INQUIRY_TO", "").replace(";", ",").split(",")
                if item.strip()
            ),
            smtp_use_ssl=get_bool_env("SMTP_USE_SSL", True),
            smtp_use_tls=get_bool_env("SMTP_USE_TLS", False),
        )


def load_runtime_config() -> AppConfig:
    load_dotenv_file(PROJECT_ROOT / ".env")
    return AppConfig.from_env()
