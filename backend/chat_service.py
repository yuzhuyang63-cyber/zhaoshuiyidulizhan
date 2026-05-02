from __future__ import annotations

import logging

from openai import OpenAI

from .config import AppConfig, get_env_value
from .knowledge_base import LocalKnowledgeBase
from .logging_setup import get_logger, log_event
from .text_utils import clean_text_for_lang, is_greeting, localized_text, normalize_history, normalize_text, resolve_language


SYSTEM_PROMPTS = {
    "zh": (
        "你是我们公司的 AI 客服助手，你的名字叫玉竹。"
        "我们公司的人工客服联系方式是微信：Jade1998。"
        "除非用户明确要求其他语言，否则你必须始终使用中文回复。"
        "你必须严格依据检索到的知识库片段回答问题。"
        "不要猜测、编造，或补充知识库没有明确支持的信息。"
        "如果知识库不足以回答，必须明确说明当前知识库无法确认，并建议联系人工客服。"
        "优先回答产品功能、操作步骤、技术说明、连接方式、测量流程、绘图分析和注意事项。"
        "回答先给结论，再用简洁要点说明。"
        "如果不同产品的答案可能不同而用户没说清型号，先要求确认产品型号。"
        "不要编造价格、交期、库存、保修或售后政策。"
    ),
    "en": (
        "You are our company's AI customer service assistant. Your name is Yuzhu. "
        "The human customer service contact is WeChat: Jade1998. "
        "You must always reply in English unless the user explicitly asks for another language. "
        "You must answer strictly based on the retrieved knowledge base snippets. "
        "Do not guess, invent, or add details that are not clearly supported by the knowledge base. "
        "If the knowledge base is insufficient, say that you cannot confirm it from the current knowledge base and suggest contacting human customer service. "
        "Prioritize questions about product functions, operation steps, technical explanations, connection methods, measurement workflow, graph analysis, and precautions. "
        "Give the conclusion first, then explain briefly in clear points. "
        "If different products may have different answers and the user did not specify the model, ask them to confirm the product model first. "
        "Do not fabricate price, lead time, stock, warranty, or after-sales policy information that is not in the knowledge base."
    ),
}

RAG_GUARDRAILS = {
    "zh": (
        "下面是从产品知识库中检索到的相关片段。"
        "你只能依据这些片段回答。"
        "如果片段不能明确支持答案，就直接说“我暂时无法从当前知识库确认”，"
        "并建议联系人工客服微信：Jade1998。"
    ),
    "en": (
        "The following snippets were retrieved from the product knowledge base. "
        "You may answer only from these snippets. "
        "If the snippets do not clearly support the answer, say that you cannot confirm it from the current knowledge base and suggest contacting human customer service on WeChat: Jade1998."
    ),
}

NO_KB_REPLIES = {
    "zh": "我暂时无法从当前知识库确认这个问题。请告诉我具体产品型号，或联系人工客服微信：Jade1998。",
    "en": "I cannot confirm this from the current knowledge base yet. Please tell me the exact product model, or contact our human customer service on WeChat: Jade1998.",
}

GREETING_REPLIES = {
    "zh": "您好，我是玉竹客服。您可以直接咨询 ADMT 安卓屏系列或找水金箍棒的操作、连接、测量、绘图和注意事项。",
    "en": "Hello, this is Yuzhu support. You can ask about the ADMT Android screen series or the Water-seeking Golden Rod, including operation, connection, measurement, graphing, and precautions.",
}

CONTEXT_LABELS = {
    "zh": {
        "chunk": "知识片段",
        "product": "产品",
        "language": "语言",
        "section": "章节",
        "source": "来源",
        "content": "内容",
    },
    "en": {
        "chunk": "Knowledge Snippet",
        "product": "Product",
        "language": "Language",
        "section": "Section",
        "source": "Source",
        "content": "Content",
    },
}

FALLBACK_TITLES = {
    "zh": "模型服务暂时不可用，先为您返回最相关的知识库片段：",
    "en": "The model service is temporarily unavailable. Here are the most relevant knowledge base excerpts:",
}


class ChatService:
    def __init__(self, config: AppConfig, knowledge_base: LocalKnowledgeBase):
        self.config = config
        self.knowledge_base = knowledge_base
        self.logger = get_logger()
        self._client: OpenAI | None = None

    def _build_client(self) -> OpenAI:
        api_key = get_env_value("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing API key. Set DEEPSEEK_API_KEY in the environment or create a .env file in the project root."
            )

        log_event(
            self.logger,
            logging.INFO,
            "model_client_initializing",
            "initializing model client",
            base_url=self.config.deepseek_base_url,
            model=self.config.deepseek_model,
        )
        return OpenAI(api_key=api_key, base_url=self.config.deepseek_base_url)

    def get_client(self) -> OpenAI:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def has_model_api_key(self) -> bool:
        return bool(get_env_value("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_KEY"))

    def build_context(self, retrieved_chunks: list[dict], reply_lang: str) -> str:
        labels = CONTEXT_LABELS[resolve_language(reply_lang)]
        blocks: list[str] = []
        for index, chunk in enumerate(retrieved_chunks, 1):
            section = " > ".join(clean_text_for_lang(part, reply_lang) for part in chunk["section_path"])
            product_name = clean_text_for_lang(chunk["product_name"], reply_lang)
            source_file = clean_text_for_lang(chunk["source_file"], reply_lang)
            content = clean_text_for_lang(chunk["content"], reply_lang)
            blocks.append(
                "\n".join(
                    [
                        f"[{labels['chunk']} {index}]",
                        f"{labels['product']}: {product_name}",
                        f"{labels['language']}: {chunk['lang']}",
                        f"{labels['section']}: {section}",
                        f"{labels['source']}: {source_file}",
                        f"{labels['content']}: {content}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def build_citations(self, retrieved_chunks: list[dict]) -> list[dict]:
        return [
            {
                "id": chunk["id"],
                "product_id": chunk["product_id"],
                "product_name": chunk["product_name"],
                "lang": chunk["lang"],
                "section_path": chunk["section_path"],
                "source_file": chunk["source_file"],
                "score": chunk["score"],
            }
            for chunk in retrieved_chunks
        ]

    def build_retrieval_fallback_reply(self, retrieved_chunks: list[dict], reply_lang: str) -> str:
        reply_lang = resolve_language(reply_lang)
        label = FALLBACK_TITLES[reply_lang]
        items: list[str] = []

        for index, chunk in enumerate(retrieved_chunks[:3], 1):
            section = " > ".join(clean_text_for_lang(part, reply_lang) for part in chunk["section_path"])
            content = clean_text_for_lang(chunk["content"], reply_lang)
            if len(content) > 320:
                content = f"{content[:317].rstrip()}..."
            items.append(f"{index}. [{section}] {content}")

        return "\n".join([label, *items]).strip()

    def generate_rag_reply(self, message: str, history: list[dict], retrieved_chunks: list[dict], reply_lang: str) -> str:
        reply_lang = resolve_language(reply_lang)
        context = self.build_context(retrieved_chunks, reply_lang)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS[reply_lang]},
            {"role": "system", "content": RAG_GUARDRAILS[reply_lang]},
            {"role": "system", "content": context},
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        response = self.get_client().chat.completions.create(
            model=self.config.deepseek_model,
            messages=messages,
            temperature=0.1,
        )
        reply = response.choices[0].message.content or ""
        return clean_text_for_lang(reply, reply_lang)

    def create_reply(self, message: str, history: list[dict] | None) -> dict:
        normalized_message = normalize_text(message)
        if not normalized_message:
            raise ValueError("message is required")

        cleaned_history = normalize_history(history)
        reply_lang = self.knowledge_base.infer_language(normalized_message, cleaned_history)

        if is_greeting(normalized_message):
            return {
                "reply": clean_text_for_lang(localized_text(GREETING_REPLIES, reply_lang), reply_lang),
                "citations": [],
                "retrieved_chunks": [],
                "mode": "greeting",
                "reply_lang": reply_lang,
            }

        retrieved_chunks = self.knowledge_base.search(normalized_message, cleaned_history)
        if not retrieved_chunks:
            return {
                "reply": clean_text_for_lang(localized_text(NO_KB_REPLIES, reply_lang), reply_lang),
                "citations": [],
                "retrieved_chunks": [],
                "mode": "no_match",
                "reply_lang": reply_lang,
            }

        mode = "rag"
        try:
            reply = self.generate_rag_reply(normalized_message, cleaned_history, retrieved_chunks, reply_lang)
        except Exception as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "model_generation_failed",
                "model generation failed; using retrieval fallback reply",
                exc_info=exc,
                reply_lang=reply_lang,
                retrieved_chunk_count=len(retrieved_chunks),
                error_type=type(exc).__name__,
            )
            reply = self.build_retrieval_fallback_reply(retrieved_chunks, reply_lang)
            mode = "rag_fallback"

        if not reply:
            reply = clean_text_for_lang(localized_text(NO_KB_REPLIES, reply_lang), reply_lang)

        return {
            "reply": reply,
            "citations": self.build_citations(retrieved_chunks),
            "retrieved_chunks": retrieved_chunks,
            "mode": mode,
            "reply_lang": reply_lang,
        }
