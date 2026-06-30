from __future__ import annotations

import calendar
import ipaddress
import json
import logging
import re
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from .config import AppConfig
from .inquiry_report import (
    LOCAL_TIMEZONE,
    month_key_for_record,
    write_inquiry_statistics_report,
    write_monthly_inquiry_report,
)
from .logging_setup import get_logger, log_event
from .text_utils import normalize_text


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_form_text(value: object, *, limit: int = 1000) -> str:
    return normalize_text(str(value or ""))[:limit]


COUNTRY_HEADER_NAMES = (
    "CF-IPCountry",
    "CloudFront-Viewer-Country",
    "X-Vercel-IP-Country",
    "X-Country-Code",
    "X-Appengine-Country",
)

COUNTRY_NAMES_ZH = {
    "AE": "阿联酋",
    "AR": "阿根廷",
    "AU": "澳大利亚",
    "BR": "巴西",
    "CA": "加拿大",
    "CL": "智利",
    "CN": "中国",
    "DE": "德国",
    "ES": "西班牙",
    "FR": "法国",
    "GB": "英国",
    "ID": "印度尼西亚",
    "IN": "印度",
    "IT": "意大利",
    "JP": "日本",
    "KR": "韩国",
    "MX": "墨西哥",
    "MY": "马来西亚",
    "NL": "荷兰",
    "PH": "菲律宾",
    "RU": "俄罗斯",
    "SA": "沙特阿拉伯",
    "SG": "新加坡",
    "TH": "泰国",
    "TR": "土耳其",
    "US": "美国",
    "VN": "越南",
    "ZA": "南非",
}


def country_name_from_code(value: object) -> str:
    country_code = clean_form_text(value, limit=32).upper()
    if country_code in {"", "XX", "ZZ", "T1"}:
        return ""
    if re.fullmatch(r"[A-Z]{2}", country_code):
        country_name = COUNTRY_NAMES_ZH.get(country_code)
        return f"{country_name} ({country_code})" if country_name else country_code
    return clean_form_text(value, limit=80)


def detect_country_from_headers(headers) -> str:
    for header_name in COUNTRY_HEADER_NAMES:
        country = country_name_from_code(headers.get(header_name, ""))
        if country:
            return country
    return ""


def first_public_ip(*values: object) -> str:
    for value in values:
        for part in str(value or "").split(","):
            ip_text = part.strip().strip("[]")
            if not ip_text:
                continue
            try:
                ip_value = ipaddress.ip_address(ip_text)
            except ValueError:
                continue
            if (
                ip_value.is_loopback
                or ip_value.is_private
                or ip_value.is_reserved
                or ip_value.is_multicast
                or ip_value.is_unspecified
            ):
                continue
            return str(ip_value)
    return ""


def country_from_geoip_payload(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""

    status = str(payload.get("status") or "").lower()
    if status and status not in {"success", "ok"}:
        return ""
    if payload.get("success") is False:
        return ""

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    country_code = (
        payload.get("country_code")
        or payload.get("countryCode")
        or payload.get("country_code2")
        or data.get("country_code")
        or data.get("countryCode")
        or payload.get("country")
    )
    country = country_name_from_code(country_code)
    if country:
        return country

    country_name = payload.get("country") or payload.get("country_name") or data.get("country") or data.get("country_name")
    return clean_form_text(country_name, limit=80)


class InquiryService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.inquiry_dir = config.inquiry_dir
        self.logger = get_logger()
        self._last_cleanup_date = None
        self._geoip_cache: dict[str, str] = {}
        self.cleanup_old_inquiry_files(force=True)

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

    def lookup_country_by_ip(self, ip_address: str) -> str:
        if not self.config.geoip_enabled or not self.config.geoip_api_url_template or not ip_address:
            return ""
        if ip_address in self._geoip_cache:
            return self._geoip_cache[ip_address]

        encoded_ip = urllib.parse.quote(ip_address, safe="")
        url = self.config.geoip_api_url_template.format(ip=encoded_ip)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "zhaoshuiyidulizhan-inquiry/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=max(1, self.config.geoip_timeout_seconds)) as response:
                response_body = response.read().decode("utf-8")
            country = country_from_geoip_payload(json.loads(response_body))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            country = ""
            log_event(
                self.logger,
                logging.WARNING,
                "geoip_lookup_failed",
                "IP country lookup failed",
                exc_info=exc,
                error_type=type(exc).__name__,
            )

        self._geoip_cache[ip_address] = country
        return country

    def detect_country(self, handler) -> str:
        header_country = detect_country_from_headers(handler.headers)
        if header_country:
            return header_country

        visitor_ip = first_public_ip(
            handler.headers.get("X-Real-IP", ""),
            handler.headers.get("X-Forwarded-For", ""),
            handler.client_address[0],
        )
        return self.lookup_country_by_ip(visitor_ip)

    def persist(self, payload: dict, handler) -> dict:
        self.inquiry_dir.mkdir(parents=True, exist_ok=True)
        inquiry_id = uuid4().hex[:12]
        record = {
            "id": inquiry_id,
            "created_at": utc_now_iso(),
            "remote_addr": handler.client_address[0],
            "forwarded_for": handler.headers.get("X-Forwarded-For", ""),
            "country": self.detect_country(handler),
            "user_agent": clean_form_text(handler.headers.get("User-Agent", ""), limit=300),
            "referer": clean_form_text(handler.headers.get("Referer", ""), limit=300),
            **payload,
        }
        target_path = self.inquiry_dir / f"{datetime.now(timezone.utc):%Y-%m}.jsonl"
        with target_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        try:
            record["_statistics_report_path"] = str(self.build_statistics_report())
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "inquiry_report_failed",
                "inquiry was saved but statistics Excel report generation failed",
                exc_info=exc,
                inquiry_id=inquiry_id,
            )
        self.cleanup_old_inquiry_files()
        return record

    def should_delete_month_file(self, path: Path, cutoff: datetime) -> bool:
        month_key = path.stem
        if month_key.startswith("inquiry-report-"):
            month_key = month_key.removeprefix("inquiry-report-")

        try:
            year, month = (int(part) for part in month_key.split("-", 1))
            last_day = calendar.monthrange(year, month)[1]
            month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
            return month_end < cutoff
        except Exception:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            return modified_at < cutoff

    def cleanup_old_inquiry_files(self, *, force: bool = False) -> int:
        retention_days = self.config.inquiry_retention_days
        if retention_days <= 0:
            return 0

        today = datetime.now(timezone.utc).date()
        if not force and self._last_cleanup_date == today:
            return 0

        self._last_cleanup_date = today
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        candidates = list(self.inquiry_dir.glob("*.jsonl"))
        candidates.extend((self.inquiry_dir / "reports").glob("inquiry-report-*.xlsx"))

        deleted = 0
        for path in candidates:
            if not path.is_file() or not self.should_delete_month_file(path, cutoff):
                continue
            try:
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                continue

        if deleted:
            log_event(
                self.logger,
                logging.INFO,
                "old_inquiry_files_deleted",
                "old inquiry files deleted by retention policy",
                deleted=deleted,
                retention_days=retention_days,
            )
        return deleted

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
            ("Inquiry ID", inquiry.get("id", "")),
            ("Submitted at", inquiry.get("created_at", "")),
            ("Customer name", inquiry.get("name", "")),
            ("Company", inquiry.get("company", "")),
            ("Customer email", inquiry.get("email", "")),
            ("WhatsApp", inquiry.get("whatsapp", "")),
            ("Interested product", inquiry.get("interest", "")),
            ("Country/Region", inquiry.get("country", "")),
            ("Visitor IP", inquiry.get("forwarded_for") or inquiry.get("remote_addr", "")),
        ]
        lines = ["New website inquiry received", ""]
        lines.extend(f"{label}: {value or '-'}" for label, value in fields)
        lines.extend(["", "Message:", inquiry.get("message", "") or "-"])
        lines.extend(["", "The latest long-term Excel inquiry statistics report is attached when report generation succeeds."])
        return "\n".join(lines)

    def build_monthly_report(self, inquiry: dict) -> Path:
        return write_monthly_inquiry_report(self.inquiry_dir, month_key_for_record(inquiry))

    def build_statistics_report(self) -> Path:
        return write_inquiry_statistics_report(self.inquiry_dir)

    def attach_statistics_report(self, message: EmailMessage, inquiry: dict | None = None) -> Path:
        raw_report_path = str((inquiry or {}).get("_statistics_report_path") or "").strip()
        report_path = Path(raw_report_path) if raw_report_path else None
        if report_path is None or not report_path.exists():
            report_path = self.build_statistics_report()

        message.add_attachment(
            report_path.read_bytes(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=report_path.name,
        )
        return report_path

    def send_message(self, message: EmailMessage) -> None:
        if self.config.smtp_use_ssl:
            with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            if self.config.smtp_use_tls:
                smtp.starttls()
            smtp.login(self.config.smtp_user, self.config.smtp_password)
            smtp.send_message(message)

    def send_email_notification(self, inquiry: dict) -> bool:
        if not self.email_is_configured():
            return False

        message = EmailMessage()
        inquiry_id = inquiry.get("id", "")
        sender_name = inquiry.get("name", "Website visitor")
        message["Subject"] = f"New website inquiry: {sender_name} ({inquiry_id})"
        message["From"] = self.config.smtp_from
        message["To"] = ", ".join(self.config.smtp_to)
        if inquiry.get("email"):
            message["Reply-To"] = inquiry["email"]
        message.set_content(self.build_email_body(inquiry))

        try:
            self.attach_statistics_report(message, inquiry)
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "inquiry_statistics_attachment_failed",
                "failed to prepare inquiry statistics Excel attachment",
                exc_info=exc,
                inquiry_id=inquiry_id,
            )

        self.send_message(message)
        return True

    def send_statistics_report_email(self) -> bool:
        if not self.email_is_configured():
            return False

        message = EmailMessage()
        today = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d")
        message["Subject"] = f"Inquiry statistics report ({today})"
        message["From"] = self.config.smtp_from
        message["To"] = ", ".join(self.config.smtp_to)
        message.set_content(
            "\n".join(
                [
                    "Daily scheduled inquiry statistics report.",
                    "",
                    "The attached Excel file is generated from all saved inquiry records on the server.",
                    "It includes raw inquiries plus daily, weekly, monthly, quarterly, yearly, and product interest summaries.",
                ]
            )
        )
        report_path = self.attach_statistics_report(message)
        self.send_message(message)
        log_event(
            self.logger,
            logging.INFO,
            "scheduled_inquiry_statistics_sent",
            "scheduled inquiry statistics report sent",
            report_path=report_path,
            recipients=list(self.config.smtp_to),
        )
        return True
