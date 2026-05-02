from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "kb" / "sources.json"
DEFAULT_OUTPUT_DIR = ROOT / "kb" / "generated"
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

FIGURE_ONLY_RE = re.compile(r"^(图|Figure)\s*[A-Za-z0-9]+(?:\s*(?:、|,|，|-|–)\s*[A-Za-z0-9]+)*$", re.IGNORECASE)
PAGE_ONLY_RE = re.compile(r"^[\(（]?\d+[\)）]?$")
ZH_TOP_HEADING_RE = re.compile(r"^[一二三四五六七八九十百零]+、")
ZH_SUB_HEADING_RE = re.compile(r"^\d+\.\d+")
EN_TOP_HEADING_RE = re.compile(r"^\d+\.\s*")
EN_SUB_HEADING_RE = re.compile(r"^\d+\.\d+\s*")
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


@dataclass
class Section:
    product_id: str
    product_name: str
    lang: str
    path: list[str]
    paragraphs: list[str]


def normalize_text(text: str) -> str:
    return re.sub(r"[ \t\u00A0]+", " ", text.replace("\u3000", " ")).strip()


def clean_text_for_lang(text: str, lang: str) -> str:
    cleaned = normalize_text(text)
    if lang != "en" or not cleaned:
        return cleaned

    cleaned = unicodedata.normalize("NFKC", cleaned)
    for source, target in EN_TEXT_REPLACEMENTS.items():
        cleaned = cleaned.replace(source, target)

    cleaned = re.sub(r"\s*->\s*", " -> ", cleaned)
    cleaned = re.sub(r"\s*<-\s*", " <- ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text(text)).lower()


def strip_toc_page_suffix(text: str) -> str:
    cleaned = normalize_text(text)
    return re.sub(r"\s*\d+\s*$", "", cleaned).strip()


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def extract_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", WORD_NS):
        parts = [(node.text or "") for node in paragraph.findall(".//w:t", WORD_NS)]
        text = normalize_text("".join(parts))
        if text:
            paragraphs.append(text)
    return paragraphs


def find_occurrence(paragraphs: list[str], marker: str, occurrence: int) -> int:
    marker_key = normalize_key(marker)
    matches = [
        index
        for index, text in enumerate(paragraphs)
        if normalize_key(text) == marker_key or normalize_key(text).startswith(marker_key)
    ]
    if len(matches) < occurrence:
        raise ValueError(f"Could not find marker '{marker}' occurrence {occurrence}")
    return matches[occurrence - 1]


def infer_heading_level(text: str, lang: str) -> int:
    if lang == "zh":
        if ZH_TOP_HEADING_RE.match(text):
            return 1
        if ZH_SUB_HEADING_RE.match(text):
            return 2
        return 2

    if EN_SUB_HEADING_RE.match(text):
        return 2
    if EN_TOP_HEADING_RE.match(text):
        return 1
    return 2


def build_toc_entries(entries: list[str], lang: str, mirrored_levels: list[int] | None = None) -> list[dict]:
    toc_entries: list[dict] = []
    for index, entry in enumerate(entries):
        level = mirrored_levels[index] if mirrored_levels and index < len(mirrored_levels) else infer_heading_level(entry, lang)
        toc_entries.append(
            {
                "text": entry,
                "key": normalize_key(entry),
                "level": level,
            }
        )
    return toc_entries


def split_toc_entries(paragraphs: list[str], source: dict, zh_start_index: int) -> tuple[list[str], list[str]]:
    toc_paragraphs = paragraphs[:zh_start_index]
    toc_en_marker = source["toc_en_start_marker"]
    toc_en_index = find_occurrence(toc_paragraphs, toc_en_marker, 1)

    zh_raw = [strip_toc_page_suffix(item) for item in toc_paragraphs if strip_toc_page_suffix(item)]
    zh_entries = [clean_text_for_lang(item, "zh") for item in zh_raw[1:toc_en_index] if item not in {"目录", "Index"}]

    en_raw = [strip_toc_page_suffix(item) for item in toc_paragraphs[toc_en_index:] if strip_toc_page_suffix(item)]
    en_entries = [clean_text_for_lang(item, "en") for item in en_raw if item not in {"目录", "Index"}]

    return zh_entries, en_entries


def should_skip_paragraph(text: str) -> bool:
    cleaned = normalize_text(text)
    if cleaned in {"目录", "Index"}:
        return True
    if FIGURE_ONLY_RE.match(cleaned):
        return True
    if PAGE_ONLY_RE.match(cleaned):
        return True
    if re.fullmatch(r"[\W_]+", cleaned):
        return True
    return False


def find_next_heading_index(key: str, toc_entries: list[dict], start_index: int) -> int | None:
    for index in range(start_index, len(toc_entries)):
        if toc_entries[index]["key"] == key:
            return index
    return None


def update_heading_path(path: list[str], level: int, heading: str) -> list[str]:
    adjusted_level = max(1, min(level, len(path) + 1))
    new_path = path[: adjusted_level - 1]
    new_path.append(heading)
    return new_path


def parse_sections(source: dict, lang: str, paragraphs: list[str], toc_entries: list[dict]) -> tuple[list[Section], list[str]]:
    sections: list[Section] = []
    missing_headings = [entry["text"] for entry in toc_entries]

    current_path: list[str] = []
    current_paragraphs: list[str] = []
    current_heading_seen = False
    toc_pointer = 0

    def flush_current() -> None:
        nonlocal current_paragraphs
        if not current_path:
            current_paragraphs = []
            return
        paragraphs_to_save = [item for item in current_paragraphs if not should_skip_paragraph(item)]
        sections.append(
            Section(
                product_id=source["product_id"],
                product_name=source["product_name"],
                lang=lang,
                path=current_path.copy(),
                paragraphs=paragraphs_to_save,
            )
        )
        current_paragraphs = []

    for paragraph in paragraphs:
        cleaned = clean_text_for_lang(paragraph, lang)
        if not cleaned or cleaned in {"目录", "Index"}:
            continue

        key = normalize_key(cleaned)
        heading_index = find_next_heading_index(key, toc_entries, toc_pointer)

        if heading_index is not None:
            flush_current()
            toc_pointer = heading_index + 1
            current_heading_seen = True
            level = toc_entries[heading_index]["level"]
            current_path = update_heading_path(current_path, level, cleaned)
            if toc_entries[heading_index]["text"] in missing_headings:
                missing_headings.remove(toc_entries[heading_index]["text"])
            continue

        if not current_heading_seen:
            continue

        current_paragraphs.append(cleaned)

    flush_current()
    return sections, missing_headings


def split_into_chunks(paragraphs: list[str], max_chars: int = 900, min_chars: int = 220) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_chars = 0

    for paragraph in paragraphs:
        paragraph = normalize_text(paragraph)
        if not paragraph:
            continue

        projected_chars = buffer_chars + len(paragraph) + (1 if buffer else 0)
        if buffer and projected_chars > max_chars and buffer_chars >= min_chars:
            chunks.append("\n".join(buffer))
            buffer = [paragraph]
            buffer_chars = len(paragraph)
            continue

        buffer.append(paragraph)
        buffer_chars = projected_chars

    if buffer:
        chunks.append("\n".join(buffer))

    return chunks


def build_keywords(source: dict, path: list[str]) -> list[str]:
    raw_items = [source["product_name"], *source.get("aliases", []), *path]
    keywords: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        cleaned = normalize_text(item)
        key = normalize_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            keywords.append(cleaned)

    return keywords


def zh_question_for_heading(product_name: str, heading: str) -> str:
    if "概述" in heading:
        return f"{product_name}是什么？"
    if "特点" in heading:
        return f"{product_name}有哪些主要特点？"
    if "工作原理" in heading:
        return f"{product_name}的工作原理是什么？"
    if "技术参数" in heading:
        return f"{product_name}的主要技术参数是什么？"
    if "初始化" in heading:
        return f"{product_name}如何做初始化设置？"
    if "连接" in heading:
        return f"{product_name}如何连接设备？"
    if "登录" in heading or "注册" in heading:
        return f"{product_name}如何登录或注册？"
    if "新建测量" in heading:
        return f"{product_name}如何新建测量？"
    if "在线测量" in heading:
        return f"{product_name}如何进行在线测量？"
    if "离线测量" in heading:
        return f"{product_name}如何进行离线测量？"
    if "绘图" in heading:
        return f"{product_name}如何进行绘图分析？"
    if "AI自动分析" in heading or "AI分析" in heading:
        return f"{product_name}如何使用AI分析功能？"
    if "数据处理" in heading:
        return f"{product_name}如何进行数据处理？"
    if "野外测线" in heading or "测线布设" in heading:
        return f"{product_name}如何布设野外测线？"
    if "注意事项" in heading:
        return f"使用{product_name}时有哪些注意事项？"
    return f"{product_name}的“{heading}”怎么操作？"


def en_question_for_heading(product_name: str, heading: str) -> str:
    lowered = heading.lower()
    if "overview" in lowered:
        return f"What is {product_name}?"
    if "main features" in lowered or "features" in lowered:
        return f"What are the main features of {product_name}?"
    if "working principle" in lowered:
        return f"What is the working principle of {product_name}?"
    if "main parameters" in lowered or "technical" in lowered:
        return f"What are the main technical parameters of {product_name}?"
    if "initialize" in lowered:
        return f"How do I initialize {product_name}?"
    if "connect" in lowered or "connection" in lowered:
        return f"How do I connect {product_name}?"
    if "login" in lowered or "registation" in lowered or "registration" in lowered:
        return f"How do I log in or register for {product_name}?"
    if "new measurement" in lowered:
        return f"How do I create a new measurement in {product_name}?"
    if "online measurement" in lowered:
        return f"How do I perform online measurement with {product_name}?"
    if "off-line" in lowered or "offline" in lowered:
        return f"How do I perform offline measurement with {product_name}?"
    if "drawing" in lowered:
        return f"How do I use the drawing and analysis features of {product_name}?"
    if "ai automatic analysis" in lowered or "ai analysis" in lowered:
        return f"How do I use AI analysis in {product_name}?"
    if "data processing" in lowered:
        return f"How do I process data in {product_name}?"
    if "layout" in lowered:
        return f"How do I lay out survey lines for {product_name}?"
    if "precautions" in lowered:
        return f"What precautions should I follow when using {product_name}?"
    return f"How do I use the '{heading}' function of {product_name}?"


def question_for_chunk(chunk: dict) -> str:
    heading = chunk["section_path"][-1]
    if chunk["lang"] == "zh":
        return zh_question_for_heading(chunk["product_name"], heading)
    return en_question_for_heading(chunk["product_name"], heading)


def build_records(source: dict, sections: list[Section]) -> tuple[list[dict], list[dict], list[dict]]:
    chunks: list[dict] = []
    faq_seeds: list[dict] = []
    sparse_sections: list[dict] = []
    section_chunk_counters: defaultdict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
    section_faq_seen: set[tuple[str, str, tuple[str, ...]]] = set()
    chunk_serial = 1
    section_paths_by_lang: defaultdict[str, list[tuple[str, ...]]] = defaultdict(list)

    for section in sections:
        section_paths_by_lang[section.lang].append(tuple(section.path))

    for section in sections:
        usable_paragraphs = [paragraph for paragraph in section.paragraphs if not should_skip_paragraph(paragraph)]
        if not usable_paragraphs:
            current_path = tuple(section.path)
            has_children = any(
                len(other_path) > len(current_path) and other_path[: len(current_path)] == current_path
                for other_path in section_paths_by_lang[section.lang]
            )
            if not has_children:
                sparse_sections.append(
                    {
                        "product_id": section.product_id,
                        "product_name": section.product_name,
                        "lang": section.lang,
                        "section_path": section.path,
                        "reason": "No extractable text in this section. The source likely contains figures, tables, or screenshots only.",
                    }
                )
            continue

        chunk_texts = split_into_chunks(usable_paragraphs)
        section_key = (section.lang, tuple(section.path))

        for chunk_index, content in enumerate(chunk_texts, 1):
            section_chunk_counters[section_key] += 1
            chunk_id = f"{section.product_id}_{section.lang}_{chunk_serial:04d}"
            chunk_serial += 1
            record = {
                "id": chunk_id,
                "product_id": section.product_id,
                "product_name": section.product_name,
                "lang": section.lang,
                "doc_type": "manual",
                "section_path": section.path,
                "section_title": section.path[-1],
                "section_chunk_index": chunk_index,
                "keywords": build_keywords(source, section.path),
                "source_file": source["display_name"],
                "source_path": source["source_file"],
                "content": content,
                "char_count": len(content),
            }
            chunks.append(record)

            faq_key = (section.product_id, section.lang, tuple(section.path))
            if faq_key not in section_faq_seen:
                section_faq_seen.add(faq_key)
                faq_seeds.append(
                    {
                        "id": f"faq_{section.product_id}_{section.lang}_{len(faq_seeds) + 1:04d}",
                        "product_id": section.product_id,
                        "product_name": section.product_name,
                        "lang": section.lang,
                        "question": question_for_chunk(record),
                        "answer": content,
                        "source_chunk_id": chunk_id,
                        "section_path": section.path,
                    }
                )

    return chunks, faq_seeds, sparse_sections


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_catalog(sources: list[dict], chunks: list[dict], faq_seeds: list[dict]) -> list[dict]:
    chunk_count_by_product: defaultdict[str, int] = defaultdict(int)
    faq_count_by_product: defaultdict[str, int] = defaultdict(int)
    langs_by_product: defaultdict[str, set[str]] = defaultdict(set)

    for chunk in chunks:
        chunk_count_by_product[chunk["product_id"]] += 1
        langs_by_product[chunk["product_id"]].add(chunk["lang"])

    for faq in faq_seeds:
        faq_count_by_product[faq["product_id"]] += 1

    catalog: list[dict] = []
    for source in sources:
        catalog.append(
            {
                "product_id": source["product_id"],
                "product_name": source["product_name"],
                "aliases": source.get("aliases", []),
                "languages": sorted(langs_by_product[source["product_id"]]),
                "source_file": source["display_name"],
                "source_path": source["source_file"],
                "chunk_count": chunk_count_by_product[source["product_id"]],
                "faq_seed_count": faq_count_by_product[source["product_id"]],
            }
        )
    return catalog


def build_source_report(
    source: dict,
    zh_sections: list[Section],
    en_sections: list[Section],
    zh_missing_headings: list[str],
    en_missing_headings: list[str],
    sparse_sections: list[dict],
    chunks: list[dict],
) -> dict:
    source_sparse = [item for item in sparse_sections if item["product_id"] == source["product_id"]]
    source_chunks = [item for item in chunks if item["product_id"] == source["product_id"]]

    return {
        "product_id": source["product_id"],
        "product_name": source["product_name"],
        "source_file": source["display_name"],
        "languages": ["zh", "en"],
        "section_count": {
            "zh": len(zh_sections),
            "en": len(en_sections),
        },
        "chunk_count": len(source_chunks),
        "missing_toc_headings": {
            "zh": zh_missing_headings,
            "en": en_missing_headings,
        },
        "sparse_sections": source_sparse,
        "notes": [
            "Sparse sections usually indicate screenshots, tables, or technical parameter images that were not extractable as plain text.",
            "Review sparse sections manually if you need exact numeric specifications in the chatbot.",
        ],
    }


def build_manual_kb(sources_path: Path, output_dir: Path) -> dict:
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: list[dict] = []
    all_faq_seeds: list[dict] = []
    all_sparse_sections: list[dict] = []
    source_reports: list[dict] = []

    for source in sources:
        source_path = Path(source["source_file"])
        paragraphs = extract_docx_paragraphs(source_path)

        zh_start_index = find_occurrence(paragraphs, source["zh_body_start_marker"], source["zh_body_start_occurrence"])
        en_start_index = find_occurrence(paragraphs, source["en_body_start_marker"], source["en_body_start_occurrence"])

        zh_toc_entries, en_toc_entries = split_toc_entries(paragraphs, source, zh_start_index)
        zh_toc = build_toc_entries(zh_toc_entries, "zh")
        zh_levels = [entry["level"] for entry in zh_toc]

        mirrored_levels = zh_levels if source.get("mirror_en_levels_from_zh") else None
        en_toc = build_toc_entries(en_toc_entries, "en", mirrored_levels=mirrored_levels)

        zh_body = paragraphs[zh_start_index:en_start_index]
        en_body = paragraphs[en_start_index:]

        zh_sections, zh_missing_headings = parse_sections(source, "zh", zh_body, zh_toc)
        en_sections, en_missing_headings = parse_sections(source, "en", en_body, en_toc)

        source_chunks, source_faq, source_sparse = build_records(source, [*zh_sections, *en_sections])

        all_chunks.extend(source_chunks)
        all_faq_seeds.extend(source_faq)
        all_sparse_sections.extend(source_sparse)
        source_reports.append(
            build_source_report(
                source=source,
                zh_sections=zh_sections,
                en_sections=en_sections,
                zh_missing_headings=zh_missing_headings,
                en_missing_headings=en_missing_headings,
                sparse_sections=source_sparse,
                chunks=source_chunks,
            )
        )

    catalog = build_catalog(sources, all_chunks, all_faq_seeds)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "chunk_count": len(all_chunks),
        "faq_seed_count": len(all_faq_seeds),
        "documents": source_reports,
    }

    write_jsonl(output_dir / "manual_chunks.jsonl", all_chunks)
    write_jsonl(output_dir / "faq_seed.jsonl", all_faq_seeds)
    (output_dir / "product_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "extraction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build product knowledge-base data from bilingual DOCX manuals.")
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES, help="Path to the source config JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for generated JSON files.")
    args = parser.parse_args()

    report = build_manual_kb(args.sources, args.output_dir)
    print(
        json.dumps(
            {
                "chunk_count": report["chunk_count"],
                "faq_seed_count": report["faq_seed_count"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
