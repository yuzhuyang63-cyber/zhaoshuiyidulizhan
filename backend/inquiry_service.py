from __future__ import annotations

import json
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from .config import AppConfig
from .logging_setup import get_logger
from .text_utils import normalize_text


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_form_text(value: object, *, limit: int = 1000) -> str:
    return normalize_text(str(value or ""))[:limit]


class InquiryService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.inquiry_dir = config.inquiry_dir
        self.logger = get_logger()

    def validate_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Invalid inquiry payload")

        name = clean_form_text(payload.get("name"), limit=120)
        company = clean_form_text(payload.get("company"), limit=160)
        email = clean_form_text(payload.get("email"), limit=160)
        whatsapp = clean_form_text(payload.get("whatsapp"), limit=80)
        interest = clean_form_text(payload.get("interest"), limit=160)
        message = clean_form_text(payload.get("message"), limit=3000)
        language = clean_form_text(payload.get("language"), limit=16).lower() or "en"
        source_page = clean_form_text(payload.get("source_page"), limit=200)

        if len(name) < 1:
            raise ValueError("Please provide your name")
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Please provide a valid email address")
        if not email and not whatsapp:
            raise ValueError("Please provide an email address or WhatsApp number")

        return {
            "name": name,
            "company": company,
            "email": email,
            "whatsapp": whatsapp,
            "interest": interest,
            "message": message,
            "language": language,
            "source_page": source_page,
        }

    def persist(self, payload: dict, handler) -> dict:
        self.inquiry_dir.mkdir(parents=True, exist_ok=True)
        inquiry_id = uuid4().hex[:12]
        record = {
            "id": inquiry_id,
            "created_at": utc_now_iso(),
            "remote_addr": handler.client_address[0],
            "forwarded_for": handler.headers.get("X-Forwarded-For", ""),
            "user_agent": clean_form_text(handler.headers.get("User-Agent", ""), limit=300),
            "referer": clean_form_text(handler.headers.get("Referer", ""), limit=300),
            **payload,
        }
        target_path = self.inquiry_dir / f"{datetime.now(timezone.utc):%Y-%m}.jsonl"
        with target_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def email_is_configured(self) -> bool:
        return bool(
            self.config.smtp_host
            and self.config.smtp_port
            and self.config.smtp_user
            and self.config.smtp_password
            and self.config.smtp_from
            and self.config.smtp_to
        )

    def build_email_body(self, inquiry: dict) -> str:
        fields = [
            ("询盘编号", inquiry.get("id", "")),
            ("提交时间", inquiry.get("created_at", "")),
            ("客户姓名", inquiry.get("name", "")),
            ("公司名称", inquiry.get("company", "")),
            ("客户邮箱", inquiry.get("email", "")),
            ("WhatsApp", inquiry.get("whatsapp", "")),
            ("感兴趣产品", inquiry.get("interest", "")),
            ("页面语言", inquiry.get("language", "")),
            ("来源页面", inquiry.get("source_page", "")),
            ("访客 IP", inquiry.get("forwarded_for") or inquiry.get("remote_addr", "")),
        ]
        lines = ["网站收到新的询盘", ""]
        lines.extend(f"{label}：{value or '-'}" for label, value in fields)
        lines.extend(["", "留言内容：", inquiry.get("message", "") or "-"])
        return "\n".join(lines)

    def send_email_notification(self, inquiry: dict) -> bool:
        if not self.email_is_configured():
            return False

        message = EmailMessage()
        inquiry_id = inquiry.get("id", "")
        sender_name = inquiry.get("name", "Website visitor")
        message["Subject"] = f"网站新询盘：{sender_name} ({inquiry_id})"
        message["From"] = self.config.smtp_from
        message["To"] = ", ".join(self.config.smtp_to)
        if inquiry.get("email"):
            message["Reply-To"] = inquiry["email"]
        message.set_content(self.build_email_body(inquiry))

        if self.config.smtp_use_ssl:
            with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(message)
            return True

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            if self.config.smtp_use_tls:
                smtp.starttls()
            smtp.login(self.config.smtp_user, self.config.smtp_password)
            smtp.send_message(message)
        return True
