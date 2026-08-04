#!/usr/bin/env python3
"""Extract publication-title candidates from AYS annual-report PDFs.

The output is deliberately provenance-rich.  Each row retains its report, PDF page,
faculty heading, raw citation, extraction method, and confidence so questionable
records can be reviewed without returning to the PDFs by hand.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


START_RE = re.compile(
    r"papers?\s*,?\s*books?.{0,45}?chapters?.{0,10}?published\s+or\s+forthcoming",
    re.I,
)
STOP_RE = re.compile(
    r"^(?:(?:papers?|publications?)\s*,?\s+(?:under\s+review|in\s+progress)|research\s+in\s+progress|"
    r"presentations?|conference\s+presentations?|sponsored\s+(?:research|grants?)|"
    r"external\s+grants?|journal\s+refereeing|faculty\s+(?:activities|awards)|service\s+activities)\b",
    re.I,
)
YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
QUOTED_RE = re.compile(r"[\u201c\"]([^\u201d\"]{5,300})[\u201d\"]")
MULTI_TITLE_REPORT_YEARS = {2010, 2011, 2012, 2013}
BIBLIOGRAPHIC_TAIL_FILTER_YEARS = {2011, 2012}
BIBLIOGRAPHIC_TAIL_RE = re.compile(
    r"(^by\b|^forthcoming$|\b(?:vol\.|pp\.|press|publishers?|university press|"
    r"\(eds?\.\)|\bedition\b|\bed\.|journal of|review of)\b|"
    r"^[A-Z][^:]{0,40}:\s)", re.I
)


def normalize(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\u2010", "-").replace("\u2011", "-")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def report_year(path: Path) -> int | None:
    matches = YEAR_RE.findall(path.stem)
    if matches:
        return int(matches[0])
    if re.search(r"(?:^|\D)96(?:\D|$)", path.stem):
        return 1996
    return None


def pdf_pages(path: Path) -> list[str]:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (Poppler) is required but was not found on PATH")
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        proc = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", str(path), tmp.name],
            check=True,
            capture_output=True,
            text=True,
        )
        del proc
        return Path(tmp.name).read_text(encoding="utf-8", errors="replace").split("\f")


def is_faculty_heading(block: str) -> bool:
    s = normalize(block)
    if not s or len(s) > 80 or len(s.split()) > 8:
        return False
    if any(ch in s for ch in ".,;:\"()0123456789"):
        return False
    words = [w for w in re.split(r"\s+", s) if w.lower() not in {"and", "de", "van", "von"}]
    return len(words) >= 2 and all(w[:1].isupper() or w.isupper() for w in words)


def page_blocks(page: str) -> list[str]:
    """Split a page into citation-sized blocks, including reports without blank lines."""
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            value = normalize("\n".join(current))
            if value:
                blocks.append(value)
            current.clear()

    for raw in page.splitlines():
        s = raw.strip()
        if not s:
            flush()
            continue
        citation_start = bool(re.match(
            r"^(?:[*^]\s*)?(?:[\u201c\"]|and\s+|,\s+|\(with\s+|Editors?\.\s+|"
            r"[A-Z][A-Za-z'\u2019-]+,\s+[A-Z](?:\.|[A-Za-z-]))",
            s,
        ))
        heading_start = is_faculty_heading(s)
        if current and (citation_start or heading_start):
            flush()
        current.append(s)
    flush()
    return blocks


def title_from_citation(citation: str) -> tuple[str, str, float]:
    q = QUOTED_RE.search(citation)
    if q:
        return normalize(q.group(1)), "quoted_title", 0.96

    # Common modern APA-like form: Authors. 2019/Forthcoming. Title. Venue.
    apa = re.search(
        r"\((?:Published|Electronic Pre-Publication|Accepted/Forthcoming/In Press)\)\s*"
        r"(?:\((?:in press|(?:19|20)\d{2})\)\s*)?[.:]?\s*"
        r"(.+?)(?=\.\s+(?:To appear in\s+)?[A-Z]|$)", citation, re.I
    )
    if not apa:
        apa = re.search(
            r"(?:\b(?:19|20)\d{2}\b|\bForthcoming\b|"
            r"\bPre-publication\s+(?:19|20)\d{2}\b)\s*[.:]\s*"
            r"(.+?)(?=\.\s+(?:To appear in\s+)?[A-Z]|$)", citation, re.I
        )
    if apa:
        candidate = normalize(apa.group(1)).rstrip(".")
        if 5 <= len(candidate) <= 350:
            return candidate, "apa_title", 0.82

    editor = re.search(r"\bEditors?\.\s+(.+?)(?=,\s+(?:[A-Z][\w.-]+\s*){1,4}:|,\s*(?:19|20)\d{2}\b|$)", citation)
    if editor:
        return normalize(editor.group(1)), "editor_book_title", 0.78

    review = re.search(
        r"^wrote (?:a |the )?review of (?:the book )?(.+?)(?=,\s+in\s+[^,]+(?:,|$))",
        citation, re.I,
    )
    if review:
        return normalize(review.group(1)), "reviewed_work_title", 0.84

    status_leading = re.search(r"^\((?:forthcoming|in press)\)\.\s+(.+?)(?=,\s+[A-Z][^,]{2,80}(?:Press|University)|$)", citation, re.I)
    if status_leading:
        return normalize(status_leading.group(1)), "status_leading_title", 0.80

    standalone_work = re.search(
        r"^(.+?)(?=\.\s+Report prepared\b|,\s+Atlanta,\s+Ga\.:\s+Georgia State University Library\b)",
        citation, re.I,
    )
    if standalone_work:
        return normalize(standalone_work.group(1)), "standalone_work_title", 0.80

    # Preserve an uncertain but useful title-like segment for manual QA.
    after_author = re.search(r"^[^,]{2,100},\s+(.+?)(?=,\s*(?:Vol\.|No\.|pp?\.|19\d{2}|20\d{2}|forthcoming)\b|$)", citation, re.I)
    if after_author:
        candidate = normalize(after_author.group(1)).strip("\"\u201c\u201d .")
        if 5 <= len(candidate) <= 350:
            return candidate, "title_like_segment", 0.55
    return "", "unresolved", 0.0


def looks_like_citation(block: str) -> bool:
    s = normalize(block)
    if len(s) < 25:
        return False
    low = s.lower()
    reject = (
        "during " in low[:20] or low.startswith("the faculty publication record")
        or low.startswith("co-authored papers are listed") or low.startswith("all andrew young school")
        or low.startswith("see also ") or low.startswith("papers, books")
    )
    if reject:
        return False
    signals = bool(QUOTED_RE.search(s) or YEAR_RE.search(s) or re.search(r"\bforthcoming\b", s, re.I))
    signals |= bool(re.search(r"\b(?:journal|press|review|chapter|editor|editors|volume|vol\.|pp\.)\b", s, re.I))
    return signals


def extract_report(path: Path) -> tuple[list[dict], dict]:
    year = report_year(path)
    pages = pdf_pages(path)
    starts: list[tuple[int, int]] = []
    for i, page in enumerate(pages):
        match = START_RE.search(normalize(page))
        if match:
            starts.append((i, match.start()))
    # Newer reports have graphical section headers that pdftotext cannot see.  Their
    # TOC still gives reliable printed-page boundaries, so translate those to PDF pages.
    toc_start_number = toc_next_number = None
    for page in pages[:15]:
        lines = [normalize(line) for line in page.splitlines()]
        for i, line in enumerate(lines):
            if START_RE.search(line):
                m = re.search(r"(\d+)\s*$", line)
                if m:
                    toc_start_number = int(m.group(1))
                    for later in lines[i + 1 :]:
                        if re.search(r"papers?\s+under\s+review|journal\s+refereeing|papers?\s+presented", later, re.I):
                            n = re.search(r"(\d+)\s*$", later)
                            if n:
                                toc_next_number = int(n.group(1))
                            break
                break

    # When the TOC matches, the next occurrence is normally the real section. Later
    # occurrences are cross-references elsewhere in the report, not section starts.
    narrative_starts = []
    annual_narrative_re = re.compile(
        r"during\s+(?:19|20)\d{2}\s*,?\s*(?:about\s+)?\d+\s+scholarly\s+"
        r"(?:papers|articles)", re.I
    )
    # Some editions label this section only "Publications". The narrative count is
    # a more stable locator than the heading across the report series.
    narrative_pages = [
        i for i, page in enumerate(pages)
        if annual_narrative_re.search(normalize(page))
    ]
    for page, position in starts:
        nearby = normalize(pages[page])[position : position + 900]
        if (page >= 14 or position < 200) and re.search(r"(?:during\s+(?:19|20)\d{2}|this year.s output|faculty publication record|\d+\s+scholarly papers)", nearby, re.I):
            narrative_starts.append(page)
    heading_starts = [page for page, position in starts if position < 200 and page >= 10]
    section_candidates = narrative_pages + narrative_starts + heading_starts
    if section_candidates:
        start_page = min(section_candidates)
    elif len(starts) == 1 and starts[0][0] < 15 and toc_start_number is not None:
        start_page = toc_start_number - 1
    elif starts:
        start_page = starts[0][0]
    elif toc_start_number is not None:
        start_page = toc_start_number - 1
    else:
        return [], {"report": path.name, "year": report_year(path), "pages": len(pages), "status": "section_not_found"}

    rows: list[dict] = []
    faculty = ""
    end_page = len(pages) - 1
    if toc_start_number is not None and toc_next_number is not None:
        end_page = min(end_page, start_page + (toc_next_number - toc_start_number) - 1)
    explicit_stop_pages = [
        i for i in range(start_page + 1, len(pages))
        if STOP_RE.search(normalize(pages[i]))
    ]
    if explicit_stop_pages:
        # Prefer an observed section heading. TOC page arithmetic is unreliable in
        # editions whose front matter and printed page numbers use different offsets.
        end_page = explicit_stop_pages[0] - 1
    for page_idx in range(start_page, len(pages)):
        if page_idx > end_page:
            break
        page = pages[page_idx]
        blocks = page_blocks(page)
        if page_idx > start_page:
            early = blocks[:4]
            if any(STOP_RE.search(b) for b in early):
                end_page = page_idx - 1
                break
        for block_idx, block in enumerate(blocks):
            if START_RE.search(block) or re.fullmatch(r"(?:Page\s+)?\d+", block, re.I):
                continue
            if is_faculty_heading(block):
                faculty = block
                continue
            if not looks_like_citation(block):
                continue
            quoted_titles = [normalize(value).strip(" .,") for value in QUOTED_RE.findall(block)]
            quoted_titles = [value for value in quoted_titles if len(value) >= 5]
            if quoted_titles and year in MULTI_TITLE_REPORT_YEARS:
                parsed_titles = [(value, "quoted_title", 0.96) for value in quoted_titles]
            else:
                parsed_titles = [title_from_citation(block)]
            for title, method, confidence in parsed_titles:
                # The downstream object is a publication title, not merely a paragraph
                # containing a year or venue keyword. Retaining unresolved blocks inflated
                # annual counts without adding usable publications.
                if not title:
                    continue
                if (year in BIBLIOGRAPHIC_TAIL_FILTER_YEARS
                        and method == "title_like_segment"
                        and BIBLIOGRAPHIC_TAIL_RE.search(title)):
                    continue
                digest = hashlib.sha1(
                    f"{path.name}|{page_idx+1}|{block}|{title}".encode()
                ).hexdigest()[:16]
                rows.append({
                    "record_id": digest,
                    "report_year": year,
                    "report_file": path.name,
                    "pdf_page": page_idx + 1,
                    "faculty_heading": faculty,
                    "title": title,
                    "raw_citation": block,
                    "extraction_method": method,
                    "confidence": f"{confidence:.2f}",
                    "needs_review": confidence < 0.75,
                })
    # Exact repeated titles are cross-listing artifacts (usually a faculty entry plus
    # a coauthor reference), not additional publications. Keep the first provenance.
    deduplicated: list[dict] = []
    seen_titles: set[str] = set()
    for row in rows:
        key = re.sub(r"[^a-z0-9]+", " ", row["title"].lower()).strip()
        if key and key in seen_titles:
            continue
        seen_titles.add(key)
        deduplicated.append(row)
    rows = deduplicated

    summary = {
        "report": path.name,
        "year": year,
        "pages": len(pages),
        "section_start_pdf_page": start_page + 1,
        "section_end_pdf_page": end_page + 1,
        "candidate_citations": len(rows),
        "titles_extracted": sum(bool(r["title"]) for r in rows),
        "needs_review": sum(r["needs_review"] for r in rows),
        "status": "ok",
    }
    return rows, summary


def write_outputs(rows: list[dict], summaries: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["record_id", "report_year", "report_file", "pdf_page", "faculty_heading", "title", "raw_citation", "extraction_method", "confidence", "needs_review"]
    with (output_dir / "publication_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "publication_candidates.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "extraction_summary.json").open("w", encoding="utf-8") as f:
        json.dump({"reports": summaries, "totals": {
            "reports": len(summaries), "candidate_citations": len(rows),
            "titles_extracted": sum(bool(r["title"]) for r in rows),
            "needs_review": sum(r["needs_review"] for r in rows),
            "methods": Counter(r["extraction_method"] for r in rows),
        }}, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/Annual-Reports"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--limit", type=int, help="Process only the first N reports (for testing)")
    args = parser.parse_args()
    pdfs = sorted(args.input_dir.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]
    rows, summaries = [], []
    for pdf in pdfs:
        extracted, summary = extract_report(pdf)
        rows.extend(extracted)
        summaries.append(summary)
        print(f"{pdf.name}: {summary['status']} ({len(extracted)} candidates)")
    write_outputs(rows, summaries, args.output_dir)
    print(f"Wrote {len(rows)} candidates from {len(pdfs)} reports to {args.output_dir}")


if __name__ == "__main__":
    main()
