from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import AppConfig
from .logging_setup import get_logger, log_event
from .models import FaqSeed, KnowledgeChunk, ProductInfo
from .text_utils import clean_text_for_lang, compact_text, detect_language, extract_terms, normalize_text, resolve_language


def read_jsonl(path: Path) -> list[dict]:
    logger = get_logger()
    records: list[dict] = []
    if not path.exists():
        log_event(
            logger,
            logging.WARNING,
            "jsonl_file_missing",
            "jsonl file not found",
            path=path,
        )
        return records

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "jsonl_parse_failed",
                    "failed to parse jsonl record",
                    exc_info=exc,
                    path=path,
                    line_number=line_number,
                )
                raise
    return records


class LocalKnowledgeBase:
    def __init__(self, config: AppConfig):
        self.config = config
        self.logger = get_logger()
        self.chunks_path = config.chunks_path
        self.catalog_path = config.catalog_path
        self.faq_path = config.faq_path
        self.products = self._load_products()
        self.chunks = self._load_chunks()
        self.chunk_by_id = {chunk.id: chunk for chunk in self.chunks}
        self.faq_seeds = self._load_faq_seeds()

    def _load_products(self) -> dict[str, ProductInfo]:
        if not self.catalog_path.exists():
            log_event(
                self.logger,
                logging.WARNING,
                "catalog_file_missing",
                "catalog file not found",
                path=self.catalog_path,
            )
            return {}

        try:
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log_event(
                self.logger,
                logging.ERROR,
                "catalog_parse_failed",
                "failed to parse catalog json",
                exc_info=exc,
                path=self.catalog_path,
            )
            raise
        products: dict[str, ProductInfo] = {}
        for item in data:
            product = ProductInfo(
                product_id=item["product_id"],
                product_name=item["product_name"],
                aliases=list(item.get("aliases", [])),
                languages=list(item.get("languages", [])),
            )
            products[product.product_id] = product
        return products

    def _load_chunks(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for record in read_jsonl(self.chunks_path):
            lang = resolve_language(record.get("lang", "zh"))
            section_path = [
                clean_text_for_lang(part, lang)
                for part in record.get("section_path", [])
                if clean_text_for_lang(part, lang)
            ]
            fallback_title = section_path[-1] if section_path else ""
            section_title = clean_text_for_lang(record.get("section_title", "") or fallback_title, lang)
            keywords = [
                clean_text_for_lang(keyword, lang)
                for keyword in record.get("keywords", [])
                if clean_text_for_lang(keyword, lang)
            ]
            content = clean_text_for_lang(record.get("content", ""), lang)
            source_file = clean_text_for_lang(record.get("source_file", ""), lang)

            searchable_title = " ".join(section_path)
            searchable_keywords = " ".join(keywords)

            chunks.append(
                KnowledgeChunk(
                    id=record["id"],
                    product_id=record["product_id"],
                    product_name=record["product_name"],
                    lang=lang,
                    section_path=section_path,
                    section_title=section_title,
                    keywords=keywords,
                    source_file=source_file,
                    content=content,
                    title_terms=extract_terms(searchable_title),
                    keyword_terms=extract_terms(searchable_keywords),
                    content_terms=extract_terms(content),
                    compact_content=compact_text(content),
                    compact_title=compact_text(section_title),
                )
            )

        return chunks

    def _load_faq_seeds(self) -> list[FaqSeed]:
        faq_seeds: list[FaqSeed] = []
        for record in read_jsonl(self.faq_path):
            lang = resolve_language(record.get("lang", "zh"))
            question = clean_text_for_lang(record["question"], lang)
            answer = clean_text_for_lang(record["answer"], lang)
            faq_seeds.append(
                FaqSeed(
                    source_chunk_id=record["source_chunk_id"],
                    product_id=record["product_id"],
                    lang=lang,
                    question=question,
                    question_terms=extract_terms(question),
                    answer_terms=extract_terms(answer),
                )
            )
        return faq_seeds

    @property
    def is_ready(self) -> bool:
        return bool(self.chunks)

    def detect_products(self, text: str) -> list[str]:
        compact = compact_text(text)
        matched: list[str] = []
        for product in self.products.values():
            aliases = [product.product_name, *product.aliases]
            if any(alias and compact_text(alias) in compact for alias in aliases):
                matched.append(product.product_id)
        return matched

    def infer_products(self, message: str, history: list[dict]) -> list[str]:
        matched = self.detect_products(message)
        if matched:
            return matched

        for item in reversed(history):
            inferred = self.detect_products(item["content"])
            if inferred:
                return inferred

        return []

    def infer_language(self, message: str, history: list[dict]) -> str:
        lang = detect_language(message)
        if lang:
            return lang

        for item in reversed(history):
            lang = detect_language(item["content"])
            if lang:
                return lang

        return "zh"

    def build_product_terms(self, product_ids: list[str]) -> set[str]:
        terms: set[str] = set()
        for product_id in product_ids:
            product = self.products.get(product_id)
            if not product:
                continue

            for alias in [product.product_name, *product.aliases]:
                terms.update(extract_terms(alias))

        return terms

    def list_product_aliases(self, product_ids: list[str]) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        for product_id in product_ids:
            product = self.products.get(product_id)
            if not product:
                continue

            for alias in [product.product_name, *product.aliases]:
                normalized = normalize_text(alias)
                if normalized and normalized not in seen:
                    aliases.append(normalized)
                    seen.add(normalized)

        aliases.sort(key=len, reverse=True)
        return aliases

    def strip_product_mentions(self, text: str, product_ids: list[str]) -> str:
        cleaned = normalize_text(text)
        for alias in self.list_product_aliases(product_ids):
            cleaned = re.sub(re.escape(alias), " ", cleaned, flags=re.IGNORECASE)
        return normalize_text(cleaned)

    def score_faq(self, query_terms: set[str], preferred_lang: str, product_ids: list[str]) -> dict[str, float]:
        boosts: dict[str, float] = {}
        for faq in self.faq_seeds:
            question_overlap = len(query_terms & faq.question_terms)
            answer_overlap = len(query_terms & faq.answer_terms)
            if question_overlap == 0 and answer_overlap == 0:
                continue

            score = question_overlap * 7 + answer_overlap * 1.5
            if preferred_lang == faq.lang:
                score += 1.5
            if product_ids and faq.product_id in product_ids:
                score += 8

            if score >= 7:
                boosts[faq.source_chunk_id] = max(boosts.get(faq.source_chunk_id, 0.0), score)

        return boosts

    def search(self, message: str, history: list[dict], top_k: int | None = None) -> list[dict]:
        if not self.is_ready:
            return []

        top_k = top_k or self.config.rag_top_k
        query = normalize_text(message)
        preferred_lang = self.infer_language(message, history)
        product_ids = self.infer_products(message, history)
        query_terms = extract_terms(query)
        product_terms = self.build_product_terms(product_ids)
        semantic_query = self.strip_product_mentions(query, product_ids) if product_ids else query
        semantic_terms = extract_terms(semantic_query)
        if not semantic_terms:
            semantic_terms = query_terms - product_terms
        if not semantic_terms:
            return []
        compact_query = compact_text(query)

        if not query_terms and not product_ids:
            return []

        faq_boosts = self.score_faq(semantic_terms, preferred_lang, product_ids)
        scored: list[tuple[float, KnowledgeChunk]] = []

        candidate_chunks = self.chunks
        if product_ids:
            candidate_chunks = [chunk for chunk in self.chunks if chunk.product_id in product_ids]

        for chunk in candidate_chunks:
            title_overlap = len(semantic_terms & chunk.title_terms)
            keyword_overlap = len(semantic_terms & chunk.keyword_terms)
            content_overlap = len(semantic_terms & chunk.content_terms)
            semantic_overlap = title_overlap + keyword_overlap + content_overlap
            faq_boost = faq_boosts.get(chunk.id, 0.0)

            if semantic_terms and semantic_overlap == 0 and faq_boost == 0:
                continue

            score = 0.0
            score += title_overlap * 6
            score += keyword_overlap * 4
            score += content_overlap * 2.2

            if preferred_lang == chunk.lang:
                score += 2

            if product_ids:
                score += 12

            if compact_query:
                if chunk.compact_title and chunk.compact_title in compact_query:
                    score += 8
                if len(compact_query) >= 4 and compact_query in chunk.compact_content:
                    score += 6

            score += faq_boost

            if score >= self.config.rag_min_score:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        preferred_scored = [item for item in scored if item[1].lang == preferred_lang]
        fallback_scored = [item for item in scored if item[1].lang != preferred_lang]
        ordered_scored = preferred_scored + fallback_scored

        selected: list[dict] = []
        total_chars = 0
        seen_chunk_ids: set[str] = set()

        for score, chunk in ordered_scored:
            if chunk.id in seen_chunk_ids:
                continue

            projected = total_chars + len(chunk.content)
            if selected and projected > self.config.rag_max_context_chars:
                break

            selected.append(
                {
                    "id": chunk.id,
                    "score": round(score, 2),
                    "product_id": chunk.product_id,
                    "product_name": chunk.product_name,
                    "lang": chunk.lang,
                    "section_path": chunk.section_path,
                    "section_title": chunk.section_title,
                    "source_file": chunk.source_file,
                    "content": chunk.content,
                }
            )
            seen_chunk_ids.add(chunk.id)
            total_chars = projected

            if len(selected) >= top_k:
                break

        return selected
