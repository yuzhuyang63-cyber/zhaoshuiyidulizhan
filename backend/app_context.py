from __future__ import annotations

import logging
from dataclasses import dataclass

from .chat_service import ChatService
from .config import AppConfig
from .inquiry_service import InquiryService
from .knowledge_base import LocalKnowledgeBase


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    logger: logging.Logger
    knowledge_base: LocalKnowledgeBase
    chat_service: ChatService
    inquiry_service: InquiryService
