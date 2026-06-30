from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .config import AppConfig
from .inquiry_report import LOCAL_TIMEZONE, parse_inquiry_time
from .logging_setup import get_logger


class FeishuApiError(RuntimeError):
    pass


class FeishuService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = get_logger()
        self._tenant_access_token = ""
        self._tenant_access_token_expires_at = 0.0

    def is_configured(self) -> bool:
        return bool(
            self.config.feishu_enabled
            and self.config.feishu_app_id
            and self.config.feishu_app_secret
            and self.config.feishu_bitable_app_token
            and self.config.feishu_customer_table_id
        )

    def api_url(self, path: str) -> str:
        return f"{self.config.feishu_api_base_url.rstrip('/')}{path}"

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                **(headers or {}),
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise FeishuApiError(f"Feishu HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise FeishuApiError(f"Feishu request failed: {exc.reason}") from exc

        try:
            result = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise FeishuApiError(f"Feishu returned invalid JSON: {response_body[:300]}") from exc

        if int(result.get("code", -1)) != 0:
            raise FeishuApiError(f"Feishu API error: {result}")
        return result

    def get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expires_at - 60:
            return self._tenant_access_token

        result = self.post_json(
            self.api_url("/open-apis/auth/v3/tenant_access_token/internal"),
            {
                "app_id": self.config.feishu_app_id,
                "app_secret": self.config.feishu_app_secret,
            },
        )
        token = str(result.get("tenant_access_token") or "")
        if not token:
            raise FeishuApiError("Feishu tenant_access_token is empty")

        expire_seconds = int(result.get("expire", 7200) or 7200)
        self._tenant_access_token = token
        self._tenant_access_token_expires_at = now + expire_seconds
        return token

    def build_customer_fields(self, inquiry: dict[str, Any]) -> dict[str, Any]:
        created_at = parse_inquiry_time(str(inquiry.get("created_at") or ""))
        submitted_at = created_at.strftime("%Y-%m-%d %H:%M:%S")
        now_text = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

        customer_name = str(inquiry.get("name") or "").strip()
        customer_request = str(inquiry.get("message") or "").strip()
        country = str(inquiry.get("country") or inquiry.get("region") or "").strip()
        visitor_ip = str(inquiry.get("forwarded_for") or inquiry.get("remote_addr") or "").strip()

        return {
            "询盘编号": str(inquiry.get("id") or ""),
            "提交时间": submitted_at,
            "客户名单": customer_name,
            "地区名称": country,
            "客户场景": "",
            "沟通进程": "新询盘",
            "客户要求": customer_request,
            "是否需要跟进": "是",
            "已购买": "否",
            "购买金额": "",
            "成本": "",
            "利润": "",
            "发货形式": "未确定",
            "发货状态": "未发货",
            "售后跟踪": "未开始",
            "跟进备注": "",
            "下次跟进时间": "",
            "最后更新时间": now_text,
            "公司名称": str(inquiry.get("company") or ""),
            "邮箱": str(inquiry.get("email") or ""),
            "WhatsApp": str(inquiry.get("whatsapp") or ""),
            "意向产品": str(inquiry.get("interest") or ""),
            "访客IP": visitor_ip,
        }

    def create_customer_record(self, inquiry: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured():
            return {"skipped": True, "reason": "feishu_not_configured"}

        token = self.get_tenant_access_token()
        url = self.api_url(
            "/open-apis/bitable/v1/apps/"
            f"{self.config.feishu_bitable_app_token}/tables/"
            f"{self.config.feishu_customer_table_id}/records"
        )
        result = self.post_json(
            url,
            {"fields": self.build_customer_fields(inquiry)},
            headers={"Authorization": f"Bearer {token}"},
        )
        return {"skipped": False, "record": result.get("data", {}).get("record", {})}
