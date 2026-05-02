# Product Knowledge Base

This directory holds the source config and generated knowledge-base data for the product manuals.

## Files

- `sources.json`: manual source definitions and parsing markers.
- `build_product_kb.py`: extracts DOCX text, splits it by section, and writes JSON/JSONL outputs.
- `generated/manual_chunks.jsonl`: retrieval chunks for RAG.
- `generated/faq_seed.jsonl`: seed QA pairs built from the extracted sections.
- `generated/product_catalog.json`: product metadata for filtering and routing.
- `generated/extraction_report.json`: extraction summary, including sparse sections that likely need manual supplementation.

## Build

```powershell
python kb/build_product_kb.py
```

## Notes

- The two manuals are bilingual and are split into separate Chinese and English chunks.
- Some technical parameter sections in the manuals are embedded as images or screenshots, so the extraction report should be reviewed and supplemented manually if exact numeric specs are needed in the chatbot.
