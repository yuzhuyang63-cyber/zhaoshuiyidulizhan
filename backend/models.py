from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProductInfo:
    product_id: str
    product_name: str
    aliases: list[str]
    languages: list[str]


@dataclass
class KnowledgeChunk:
    id: str
    product_id: str
    product_name: str
    lang: str
    section_path: list[str]
    section_title: str
    keywords: list[str]
    source_file: str
    content: str
    title_terms: set[str]
    keyword_terms: set[str]
    content_terms: set[str]
    compact_content: str
    compact_title: str


@dataclass
class FaqSeed:
    source_chunk_id: str
    product_id: str
    lang: str
    question: str
    question_terms: set[str]
    answer_terms: set[str]
