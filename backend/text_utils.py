from __future__ import annotations

import re
import unicodedata


EN_TEXT_REPLACEMENTS = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2192": " -> ",
    "\u2190": " <- ",
}

GREETING_PATTERNS = ("你好", "您好", "hi", "hello", "在吗", "有人吗", "喂")
HISTORY_LIMIT = 10
TERM_STOPWORDS = {
    "zh": {
        "怎么",
        "如何",
        "多少",
        "可以",
        "是否",
        "请问",
        "一个",
        "一下子",
        "什么",
        "哪个",
        "吗",
        "呢",
        "啊",
        "介绍",
        "说明",
        "功能",
        "使用",
        "操作",
        "支持",
    },
    "en": {
        "how",
        "what",
        "which",
        "can",
        "could",
        "is",
        "are",
        "the",
        "a",
        "an",
        "for",
        "to",
        "in",
        "of",
        "do",
        "does",
        "please",
        "use",
    },
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text)).lower()


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def detect_language(text: str) -> str:
    normalized = normalize_text(text)
    zh_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    en_count = len(re.findall(r"[A-Za-z]", normalized))
    if zh_count:
        return "zh"
    if en_count:
        return "en"
    return "zh"


def resolve_language(lang: str) -> str:
    return "en" if lang == "en" else "zh"


def localized_text(texts: dict[str, str], lang: str) -> str:
    return texts[resolve_language(lang)]


def clean_text_for_lang(text: str, lang: str) -> str:
    cleaned = normalize_text(text)
    if resolve_language(lang) != "en" or not cleaned:
        return cleaned

    cleaned = unicodedata.normalize("NFKC", cleaned)
    for source, target in EN_TEXT_REPLACEMENTS.items():
        cleaned = cleaned.replace(source, target)

    cleaned = re.sub(r"\s*->\s*", " -> ", cleaned)
    cleaned = re.sub(r"\s*<-\s*", " <- ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_terms(text: str) -> set[str]:
    normalized = normalize_text(text).lower()
    terms: set[str] = set()

    for token in re.findall(r"[a-z0-9][a-z0-9_\-./]*", normalized):
        if len(token) > 1 or token.isdigit():
            terms.add(token)

    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(sequence) == 1:
            terms.add(sequence)
            continue

        if len(sequence) <= 8:
            terms.add(sequence)

        for size in (2, 3):
            if len(sequence) < size:
                continue
            for index in range(len(sequence) - size + 1):
                terms.add(sequence[index : index + size])

    return {
        term
        for term in terms
        if term not in TERM_STOPWORDS["zh"] and term not in TERM_STOPWORDS["en"]
    }


def normalize_history(history: list[dict] | None) -> list[dict]:
    cleaned_history: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = normalize_text(item.get("content", ""))
        if role in {"user", "assistant"} and content:
            cleaned_history.append({"role": role, "content": content})

    return cleaned_history[-HISTORY_LIMIT:]


def is_greeting(text: str) -> bool:
    compact = compact_text(text)
    return any(pattern in compact for pattern in GREETING_PATTERNS)
