#!/usr/bin/env python3
"""Extract faculty publications from Digital Measures CV-style DOCX reports.

The parser uses only the Python standard library.  It reads WordprocessingML in
document order (paragraphs and table cells), tracks the current person's resume,
and emits the same provenance-rich rows consumed by the OpenAlex resolver.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
PUBLICATION_SECTION_RE = re.compile(
    r"^(?:publications?|intellectual contributions?(?: and creative productions?)?|"
    r"research publications?|scholarly (?:publications?|contributions|works)|"
    r"creative (?:activities|works|productions))\s*:?$", re.I
)
PUBLICATION_TYPE_RE = re.compile(
    r"^(?:(?:refereed|peer[- ]reviewed|non[- ]refereed|invited|published|accepted|forthcoming)\s+)*"
    r"(?:journal articles?|articles?|books?|book chapters?|chapters?|monographs?|"
    r"encyclopedia entries|case studies|reviews?|technical reports?|working papers?|"
    r"conference proceedings|periodicals|other(?: publications?)?)\s*:?$", re.I
)
STOP_SECTION_RE = re.compile(
    r"^(?:education|academic background|employment|professional positions?|teaching|"
    r"courses taught|grants?|contracts?|presentations?|conference presentations?|"
    r"service|professional service|university service|awards?|honors?|memberships?|"
    r"certifications?|consulting|media contributions?|student supervision|"
    r"administrative assignments?|faculty development)\s*:?$", re.I
)
NAME_LABEL_RE = re.compile(r"^(?:name|faculty(?:/staff)? member|individual)\s*:\s*(.+)$", re.I)
STATUS_RE = re.compile(r"\b(?:published|accepted|forthcoming|in press|under contract)\b", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+", re.I)
QUOTED_RE = re.compile(r"[\u201c\"]([^\u201d\"]{5,350})[\u201d\"]")


@dataclass
class Block:
    text: str
    style: str = ""
    bold: bool = False
    source: str = "paragraph"
    index: int = 0


def normalize(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2010", "-").replace("\u2011", "-")
    return re.sub(r"\s+", " ", text).strip()


def report_year(path: Path) -> int | None:
    years = YEAR_RE.findall(path.stem)
    return int(years[0]) if years else None


def _text(element: ET.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag in {W + "tab", W + "br", W + "cr"}:
            parts.append(" ")
    return normalize("".join(parts))


def docx_blocks(path: Path) -> list[Block]:
    """Return non-empty paragraphs and individual table rows in document order."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        return []
    blocks: list[Block] = []
    for child in body:
        if child.tag == W + "p":
            text = _text(child)
            if not text:
                continue
            ppr = child.find(W + "pPr")
            style_node = ppr.find(W + "pStyle") if ppr is not None else None
            style = style_node.get(W + "val", "") if style_node is not None else ""
            runs = child.findall(W + "r")
            bold_runs = sum(run.find(W + "rPr/" + W + "b") is not None for run in runs)
            blocks.append(Block(text, style, bool(runs and bold_runs == len(runs)), "paragraph", len(blocks)))
        elif child.tag == W + "tbl":
            for row in child.findall(W + "tr"):
                cells = [normalize(_text(cell)) for cell in row.findall(W + "tc")]
                cells = [cell for cell in cells if cell]
                if cells:
                    blocks.append(Block(" | ".join(cells), "table", False, "table", len(blocks)))
    return blocks


def looks_like_name(text: str, style: str = "", bold: bool = False) -> bool:
    labelled = NAME_LABEL_RE.match(text)
    if labelled:
        text = labelled.group(1)
    text = normalize(text).strip("|: ")
    if not (3 <= len(text) <= 90) or any(ch in text for ch in ";!?0123456789"):
        return False
    if PUBLICATION_SECTION_RE.match(text) or PUBLICATION_TYPE_RE.match(text) or STOP_SECTION_RE.match(text):
        return False
    words = text.split()
    if not 2 <= len(words) <= 7:
        return False
    name_particles = {"de", "del", "la", "van", "von", "da", "di", "jr", "sr"}
    name_case = all(
        word.lower().strip(",") in name_particles
        or word[:1].isupper() or word.isupper()
        for word in words
    )
    # Digital Measures marks the owner of each resume with ReportHeader. Avoid
    # treating ordinary Heading 2 labels (for example, Sponsored Activities) as people.
    heading_style = bool(re.search(r"(?:reportheader|facultyname|personname)", style, re.I))
    return name_case and (bool(labelled) or heading_style)


def normalize_person_name(value: str) -> str:
    value = normalize(value).strip("|: ")
    return re.sub(r"^(?:dr\.?|prof(?:essor)?\.?)\s+", "", value, flags=re.I)


def is_citation(text: str, report_year_value: int | None) -> bool:
    if len(text) < 18 or PUBLICATION_TYPE_RE.match(text) or PUBLICATION_SECTION_RE.match(text):
        return False
    has_year = bool(YEAR_RE.search(text))
    has_biblio = bool(DOI_RE.search(text) or QUOTED_RE.search(text) or STATUS_RE.search(text))
    has_biblio |= bool(re.search(r"\b(?:vol\.?|volume|issue|pp?\.?|journal|press|publisher)\b", text, re.I))
    if has_year and report_year_value:
        years = [int(value) for value in YEAR_RE.findall(text)]
        has_year = any(1900 <= value <= report_year_value + 3 for value in years)
    return has_biblio or (has_year and len(text.split()) >= 5)


def citation_title(citation: str) -> tuple[str, str, float]:
    quoted = QUOTED_RE.search(citation)
    if quoted:
        return normalize(quoted.group(1)).strip(" .,"), "dm_quoted_title", 0.97
    # APA: author(s). (2024). Title. Venue; also supports 2024. Title. Venue.
    apa = re.search(
        r"(?:\((?:19|20)\d{2}[a-z]?\)|(?<!\d)(?:19|20)\d{2}[a-z]?(?!\d))\s*[.):,]?\s*"
        r"(.+?)(?=\.\s+(?:[A-Z]|$)|$)", citation
    )
    if apa:
        title = normalize(apa.group(1)).strip(" .,")
        if 5 <= len(title) <= 350:
            return title, "dm_apa_title", 0.88
    # Digital Measures exports often put the work title in italics. Formatting is
    # not reliable enough across reports, so retain the citation as a search query.
    cleaned = re.sub(r"^(?:[*\u2022-]|\d+[.)])\s*", "", citation).strip()
    if 8 <= len(cleaned) <= 600:
        return cleaned, "dm_full_citation", 0.78
    return "", "dm_unresolved", 0.0


def extract_report(path: Path) -> tuple[list[dict], dict]:
    year = report_year(path)
    blocks = docx_blocks(path)
    faculty = ""
    in_publications = False
    publication_type = ""
    rows: list[dict] = []
    for block in blocks:
        text = block.text
        labelled = NAME_LABEL_RE.match(text)
        if labelled or looks_like_name(text, block.style, block.bold):
            candidate = normalize_person_name(labelled.group(1) if labelled else text)
            # A name inside a citation should never reset the resume owner.
            if not in_publications or not is_citation(text, year):
                faculty, in_publications, publication_type = candidate, False, ""
                continue
        if PUBLICATION_SECTION_RE.match(text):
            in_publications, publication_type = True, ""
            continue
        if in_publications and PUBLICATION_TYPE_RE.match(text):
            publication_type = text.rstrip(":")
            continue
        if in_publications and STOP_SECTION_RE.match(text):
            in_publications, publication_type = False, ""
            continue
        if not in_publications or not faculty or not is_citation(text, year):
            continue
        title, method, confidence = citation_title(text)
        if not title:
            continue
        digest = hashlib.sha1(f"{path.name}|{block.index}|{faculty}|{text}|{title}".encode()).hexdigest()[:16]
        rows.append({
            "record_id": digest, "report_year": year, "report_file": path.name,
            "pdf_page": "", "faculty_heading": faculty, "title": title,
            "raw_citation": text, "extraction_method": method,
            "confidence": f"{confidence:.2f}", "needs_review": confidence < 0.75,
        })
    deduped, seen = [], set()
    for row in rows:
        key = (row["faculty_heading"].casefold(), re.sub(r"[^a-z0-9]+", " ", row["title"].casefold()).strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    summary = {
        "report": path.name, "year": year, "blocks": len(blocks), "people": len({r['faculty_heading'] for r in deduped}),
        "candidate_citations": len(deduped), "titles_extracted": len(deduped),
        "needs_review": sum(r["needs_review"] for r in deduped),
        "status": "ok" if year is not None else "year_not_found",
    }
    return deduped, summary


FIELDS = ["record_id", "report_year", "report_file", "pdf_page", "faculty_heading", "title", "raw_citation", "extraction_method", "confidence", "needs_review"]


def append_candidates(rows: list[dict], candidate_path: Path) -> tuple[int, int]:
    existing: list[dict] = []
    if candidate_path.exists():
        with candidate_path.open(encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))
    ids = {row["record_id"] for row in existing}
    additions = [row for row in rows if row["record_id"] not in ids]
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing + additions)
    return len(additions), len(existing) + len(additions)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/DigitalMeasure-Reports"))
    parser.add_argument("--candidates", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--summary", type=Path, default=Path("results/digitalmeasure_extraction_summary.json"))
    parser.add_argument("--replace-digitalmeasure", action="store_true", help="Remove previously appended Digital Measures rows before appending this run")
    args = parser.parse_args()
    if not args.input_dir.exists():
        raise SystemExit(f"Digital Measures input directory not found: {args.input_dir}")
    paths = sorted([*args.input_dir.glob("*.docx"), *args.input_dir.glob("*.DOCX")])
    rows, summaries = [], []
    for path in paths:
        extracted, summary = extract_report(path)
        rows.extend(extracted)
        summaries.append(summary)
        print(f"{path.name}: {summary['status']} ({len(extracted)} candidates)")
    if args.replace_digitalmeasure and args.candidates.exists():
        with args.candidates.open(encoding="utf-8", newline="") as handle:
            retained = [row for row in csv.DictReader(handle) if not row.get("extraction_method", "").startswith("dm_")]
        with args.candidates.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader(); writer.writerows(retained)
    added, total = append_candidates(rows, args.candidates)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps({"reports": summaries, "totals": {"reports": len(paths), "candidates": len(rows), "added": added, "candidate_file_rows": total, "methods": Counter(r["extraction_method"] for r in rows)}}, indent=2, ensure_ascii=False, default=dict) + "\n", encoding="utf-8")
    print(f"Appended {added} new candidates; {args.candidates} now has {total} rows")


if __name__ == "__main__":
    main()
