from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import AppConfig
from .feishu_service import FeishuService
from .inquiry_service import InquiryService


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    logger: logging.Logger
    inquiry_service: InquiryService
    feishu_service: FeishuService
