#!/usr/bin/env python3
"""Resolve publication candidates and download legally accessible PDF copies.

Crossref is used for DOI/metadata matching. Unpaywall and OpenAlex are optional OA
location providers when UNPAYWALL_EMAIL and OPENALEX_API_KEY are configured. The
pipeline is resumable and never attempts to bypass authentication or paywalls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
import unicodedata
from html import unescape
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "ays-scholarly-impact/0.1 (metadata resolution; contact configurable)"
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_score(query: str, candidate: str) -> float:
    q, c = normalize_title(query), normalize_title(candidate)
    if not q or not c:
        return 0.0
    sequence = SequenceMatcher(None, q, c).ratio()
    q_words, c_words = set(q.split()), set(c.split())
    token = len(q_words & c_words) / len(q_words | c_words) if q_words | c_words else 0
    containment = len(q_words & c_words) / len(q_words) if q_words else 0
    return round(0.50 * sequence + 0.30 * token + 0.20 * containment, 4)


def citation_year(raw: str, report_year: int) -> int:
    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw)]
    plausible = [y for y in years if 1900 <= y <= report_year + 2]
    return plausible[-1] if plausible else report_year


def request_json(url: str, params: dict | None = None, retries: int = 3) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
        except (URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def crossref_candidates(title: str, raw: str, mailto: str | None) -> list[dict]:
    params = {"query.bibliographic": raw[:1000], "rows": 5, "select":
              "DOI,title,author,published,published-print,published-online,type,URL,container-title,link,license,abstract"}
    if mailto:
        params["mailto"] = mailto
    data = request_json("https://api.crossref.org/works", params)
    return data.get("message", {}).get("items", [])


def crossref_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "published"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return parts[0][0]
    return None


def select_crossref_match(row: dict, threshold: float) -> tuple[dict | None, float]:
    items = crossref_candidates(row["title"], row["raw_citation"], os.getenv("CROSSREF_MAILTO"))
    expected_year = citation_year(row["raw_citation"], int(row["report_year"]))
    ranked = []
    for item in items:
        candidate_title = (item.get("title") or [""])[0]
        score = title_score(row["title"], candidate_title)
        year = crossref_year(item)
        if year and abs(year - expected_year) <= 1:
            score = min(1.0, score + 0.04)
        elif year and abs(year - expected_year) > 3:
            score = max(0.0, score - 0.08)
        ranked.append((score, item))
    if not ranked:
        return None, 0.0
    score, item = max(ranked, key=lambda pair: pair[0])
    return (item, round(score, 4)) if score >= threshold else (None, round(score, 4))


def openalex_search(row: dict, api_key: str, threshold: float) -> tuple[dict | None, float]:
    """Search OpenAlex directly and conservatively select an unambiguous work."""
    data = request_json("https://api.openalex.org/works", {
        "api_key": api_key,
        "search": row["title"],
        "per_page": 10,
        "select": "id,doi,display_name,publication_year,type,authorships,primary_location,locations,abstract_inverted_index",
    })
    expected_year = citation_year(row["raw_citation"], int(row["report_year"]))
    ranked: list[tuple[float, dict]] = []
    for item in data.get("results") or []:
        score = title_score(row["title"], item.get("display_name") or "")
        year = item.get("publication_year")
        if year and abs(year - expected_year) <= 1:
            score = min(1.0, score + 0.04)
        elif year and abs(year - expected_year) > 3:
            score = max(0.0, score - 0.08)
        ranked.append((round(score, 4), item))
    if not ranked:
        return None, 0.0
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    # Near-perfect title matches may stand alone. Otherwise require separation from
    # the runner-up so generic titles do not resolve arbitrarily.
    unambiguous = best_score >= 0.96 or best_score - runner_up >= 0.04
    return (best, best_score) if best_score >= threshold and unambiguous else (None, best_score)


def inverted_abstract(index: dict | None) -> str:
    if not index:
        return ""
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned))


def clean_abstract(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def openalex_authorships(item: dict) -> list[dict]:
    """Return stable, JSON-serializable identity metadata from an OpenAlex work."""
    records = []
    for authorship in item.get("authorships") or []:
        author = authorship.get("author") or {}
        institutions = []
        for institution in authorship.get("institutions") or []:
            institutions.append({
                "id": institution.get("id") or "",
                "display_name": institution.get("display_name") or "",
                "ror": institution.get("ror") or "",
                "country_code": institution.get("country_code") or "",
                "type": institution.get("type") or "",
            })
        records.append({
            "author_id": author.get("id") or "",
            "display_name": author.get("display_name") or authorship.get("raw_author_name") or "",
            "orcid": author.get("orcid") or "",
            "author_position": authorship.get("author_position") or "",
            "is_corresponding": bool(authorship.get("is_corresponding")),
            "raw_author_name": authorship.get("raw_author_name") or "",
            "institutions": institutions,
        })
    return records


def encode_authorships(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, separators=(",", ":")) if records else ""


def oa_metadata(doi: str, crossref_item: dict, openalex_api_key: str | None) -> tuple[list[dict], str, str, dict]:
    locations: list[dict] = []
    abstract = clean_abstract(crossref_item.get("abstract"))
    abstract_source = "crossref" if abstract else ""
    openalex_work: dict = {}
    email = os.getenv("UNPAYWALL_EMAIL")
    if email:
        try:
            data = request_json(f"https://api.unpaywall.org/v2/{quote(doi, safe='')}", {"email": email})
            for loc in data.get("oa_locations") or []:
                if loc.get("url_for_pdf"):
                    locations.append({"url": loc["url_for_pdf"], "source": "unpaywall",
                                      "license": loc.get("license"), "version": loc.get("version")})
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass
    api_key = openalex_api_key or os.getenv("OPENALEX_API_KEY")
    if api_key:
        try:
            data = request_json(f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='/')}",
                                {"api_key": api_key})
            openalex_work = data
            openalex_abstract = inverted_abstract(data.get("abstract_inverted_index"))
            if openalex_abstract:
                abstract, abstract_source = openalex_abstract, "openalex"
            for loc in data.get("locations") or []:
                if loc.get("pdf_url") and loc.get("is_oa"):
                    locations.append({"url": loc["pdf_url"], "source": "openalex",
                                      "license": loc.get("license"), "version": loc.get("version")})
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass
    # Crossref license/link metadata may describe text-and-data-mining access rather
    # than public full-text access. It is therefore metadata-only here; PDF downloads
    # require an OA location explicitly identified by Unpaywall or OpenAlex.
    deduped = []
    seen = set()
    for loc in locations:
        if loc["url"] not in seen:
            seen.add(loc["url"])
            deduped.append(loc)
    return deduped, abstract, abstract_source, openalex_work


def openalex_item_metadata(item: dict) -> tuple[list[dict], str]:
    locations = []
    for loc in item.get("locations") or []:
        if loc.get("pdf_url") and loc.get("is_oa"):
            locations.append({"url": loc["pdf_url"], "source": "openalex",
                              "license": loc.get("license"), "version": loc.get("version")})
    seen, deduped = set(), []
    for loc in locations:
        if loc["url"] not in seen:
            seen.add(loc["url"])
            deduped.append(loc)
    return deduped, inverted_abstract(item.get("abstract_inverted_index"))


def safe_pdf_name(row: dict, doi: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_title(row["title"]))[:90].strip("-")
    digest = hashlib.sha1(doi.encode()).hexdigest()[:10]
    return f"{row['report_year']}_{slug}_{digest}.pdf"


def download_pdf(url: str, destination: Path, max_bytes: int) -> tuple[bool, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
    try:
        with urlopen(req, timeout=60) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            return False, "too_large"
        if not data.startswith(b"%PDF-"):
            return False, f"not_pdf:{content_type or 'unknown'}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return True, "downloaded"
    except HTTPError as exc:
        return False, f"http_{exc.code}"
    except (URLError, TimeoutError) as exc:
        return False, f"network:{type(exc).__name__}"


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    cache = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
                cache[item["record_id"]] = item
            except (json.JSONDecodeError, KeyError):
                continue
    return cache


def write_csv(path: Path, records: list[dict]) -> None:
    fields = ["record_id", "report_year", "original_title", "normalized_title", "match_status", "match_source",
              "match_score", "canonical_title", "doi", "publication_year", "work_type",
              "authors", "openalex_work_id", "openalex_authorships", "landing_url", "pdf_url", "pdf_source",
              "license", "local_pdf", "download_status"]
    fields.extend(["abstract", "abstract_source", "local_abstract"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/publication_resolution"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/publication_pdfs"))
    parser.add_argument("--abstract-dir", type=Path, default=Path("data/publication_abstracts"))
    parser.add_argument("--limit", type=int, help="Process at most N uncached records")
    parser.add_argument("--min-confidence", type=float, default=0.75,
                        help="Skip low-confidence extracted titles (default: 0.75)")
    parser.add_argument("--match-threshold", type=float, default=0.86)
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between metadata requests")
    parser.add_argument("--max-pdf-mb", type=int, default=100)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Re-resolve cached records")
    parser.add_argument("--prune-cache-to-input", action="store_true",
                        help="Discard cached records absent from the current candidate input")
    parser.add_argument("--retry-pdfs", action="store_true",
                        help="Retry all OA PDF locations for matched cached records")
    parser.add_argument("--refresh-openalex-authors", action="store_true",
                        help="Backfill OpenAlex work IDs and structured authorships for cached DOI matches")
    parser.add_argument("--force-openalex-metadata", action="store_true",
                        help="Refresh OpenAlex authorships, abstracts, and OA locations for every cached DOI match")
    parser.add_argument("--openalex-fallback", action="store_true",
                        help="Directly search OpenAlex for cached unmatched records")
    parser.add_argument("--openalex-match-threshold", type=float, default=0.88)
    parser.add_argument("--openalex-api-key-file", type=Path,
                        help="File containing only the OpenAlex API key; its value is never printed")
    args = parser.parse_args()
    openalex_api_key = None
    if args.openalex_api_key_file:
        openalex_api_key = args.openalex_api_key_file.read_text(encoding="utf-8").strip()
        if not openalex_api_key:
            raise SystemExit("OpenAlex API key file is empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.output_dir / "resolution_cache.jsonl"
    cache = load_cache(cache_path)
    candidate_rows = {row["record_id"]: row for row in csv.DictReader(
        args.input.open(encoding="utf-8", newline="")
    )}
    if args.prune_cache_to_input:
        cache = {record_id: record for record_id, record in cache.items() if record_id in candidate_rows}
        cache_tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        with cache_tmp.open("w", encoding="utf-8") as handle:
            for record_id in sorted(cache):
                handle.write(json.dumps(cache[record_id], ensure_ascii=False) + "\n")
        cache_tmp.replace(cache_path)
    if args.openalex_fallback:
        if not openalex_api_key:
            raise SystemExit("--openalex-fallback requires an OpenAlex API key")
        resolved = 0
        with cache_path.open("a", encoding="utf-8") as cache_handle:
            for record_id, result in list(cache.items()):
                if result.get("match_status") != "unmatched" or record_id not in candidate_rows:
                    continue
                if args.limit is not None and resolved >= args.limit:
                    break
                row = candidate_rows[record_id]
                try:
                    item, score = openalex_search(row, openalex_api_key, args.openalex_match_threshold)
                    result["openalex_search_score"] = score
                    if item:
                        doi_url = item.get("doi") or ""
                        doi = doi_url.removeprefix("https://doi.org/").lower()
                        structured_authors = openalex_authorships(item)
                        authors = [entry["display_name"] for entry in structured_authors if entry["display_name"]]
                        primary = item.get("primary_location") or {}
                        result.update({"match_status": "matched", "match_source": "openalex_search",
                                       "match_score": score, "canonical_title": item.get("display_name") or "",
                                       "doi": doi, "publication_year": item.get("publication_year") or "",
                                       "work_type": item.get("type") or "", "authors": "; ".join(authors),
                                       "openalex_work_id": item.get("id") or "",
                                       "openalex_authorships": encode_authorships(structured_authors),
                                       "landing_url": primary.get("landing_page_url") or item.get("id") or ""})
                        locations, abstract = openalex_item_metadata(item)
                        if abstract:
                            abstract_name = Path(safe_pdf_name(row, doi or item.get("id") or record_id)).with_suffix(".txt")
                            abstract_path = args.abstract_dir / abstract_name
                            abstract_path.parent.mkdir(parents=True, exist_ok=True)
                            abstract_path.write_text(abstract + "\n", encoding="utf-8")
                            result.update({"abstract": abstract, "abstract_source": "openalex",
                                           "local_abstract": str(abstract_path)})
                        result.update({"pdf_url": "", "pdf_source": "", "license": "",
                                       "local_pdf": "", "download_status": "no_oa_pdf"})
                        for loc in locations:
                            result.update({"pdf_url": loc["url"], "pdf_source": loc["source"],
                                           "license": loc.get("license") or ""})
                            if args.no_download:
                                break
                            destination = args.pdf_dir / safe_pdf_name(row, doi or item.get("id") or record_id)
                            ok, status = download_pdf(loc["url"], destination, args.max_pdf_mb * 1024 * 1024)
                            result["download_status"] = status
                            if ok:
                                result["local_pdf"] = str(destination)
                                break
                    cache[record_id] = result
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    result["openalex_fallback_error"] = type(exc).__name__
                    cache[record_id] = result
                cache_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                cache_handle.flush()
                resolved += 1
                print(f"fallback {resolved}: {result['match_status']} {score if 'score' in locals() else 0} {row['title'][:70]}")
                time.sleep(args.delay)
        candidates = []
    elif args.refresh_openalex_authors or args.force_openalex_metadata:
        if not openalex_api_key:
            raise SystemExit("--refresh-openalex-authors requires an OpenAlex API key")
        refreshed = 0
        with cache_path.open("a", encoding="utf-8") as cache_handle:
            for record_id, result in list(cache.items()):
                if result.get("match_status") != "matched" or not result.get("doi"):
                    continue
                # A work ID marks a completed lookup even when OpenAlex returns no
                # authorships, preventing empty-author works from being retried forever.
                if result.get("openalex_work_id") and not args.force_openalex_metadata:
                    continue
                if args.limit is not None and refreshed >= args.limit:
                    break
                try:
                    data = request_json(
                        f"https://api.openalex.org/works/https://doi.org/{quote(result['doi'], safe='/')}",
                        {"api_key": openalex_api_key},
                    )
                    structured_authors = openalex_authorships(data)
                    result["openalex_work_id"] = data.get("id") or ""
                    result["openalex_authorships"] = encode_authorships(structured_authors)
                    if structured_authors:
                        result["authors"] = "; ".join(
                            entry["display_name"] for entry in structured_authors if entry["display_name"]
                        )
                    abstract = inverted_abstract(data.get("abstract_inverted_index"))
                    if abstract:
                        abstract_name = Path(safe_pdf_name(
                            {"report_year": result["report_year"], "title": result["original_title"]},
                            result["doi"],
                        )).with_suffix(".txt")
                        abstract_path = args.abstract_dir / abstract_name
                        abstract_path.parent.mkdir(parents=True, exist_ok=True)
                        abstract_path.write_text(abstract + "\n", encoding="utf-8")
                        result.update({"abstract": abstract, "abstract_source": "openalex",
                                       "local_abstract": str(abstract_path)})
                    locations, _ = openalex_item_metadata(data)
                    if locations:
                        location = locations[0]
                        result.update({"pdf_url": location["url"], "pdf_source": "openalex",
                                       "license": location.get("license") or ""})
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    result["openalex_authorship_error"] = type(exc).__name__
                cache[record_id] = result
                cache_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                cache_handle.flush()
                refreshed += 1
                print(f"authorship {refreshed}: {result.get('openalex_work_id') or 'not_found'} {result['original_title'][:70]}")
                time.sleep(args.delay)
        candidates = []
    elif args.retry_pdfs:
        retried = 0
        with cache_path.open("a", encoding="utf-8") as cache_handle:
            for record_id, result in list(cache.items()):
                if (result.get("match_status") != "matched" or not result.get("doi")
                        or result.get("download_status") == "downloaded"):
                    continue
                if args.limit is not None and retried >= args.limit:
                    break
                locations, abstract, abstract_source, openalex_work = oa_metadata(
                    result["doi"], {}, openalex_api_key
                )
                if openalex_work:
                    structured_authors = openalex_authorships(openalex_work)
                    result["openalex_work_id"] = openalex_work.get("id") or ""
                    result["openalex_authorships"] = encode_authorships(structured_authors)
                if abstract and not result.get("abstract"):
                    abstract_name = Path(safe_pdf_name(
                        {"report_year": result["report_year"], "title": result["original_title"]},
                        result["doi"],
                    )).with_suffix(".txt")
                    abstract_path = args.abstract_dir / abstract_name
                    abstract_path.parent.mkdir(parents=True, exist_ok=True)
                    abstract_path.write_text(abstract + "\n", encoding="utf-8")
                    result.update({"abstract": abstract, "abstract_source": abstract_source,
                                   "local_abstract": str(abstract_path)})
                result.update({"pdf_url": "", "pdf_source": "", "license": "",
                               "local_pdf": "", "download_status": "no_oa_pdf"})
                for loc in locations:
                    result.update({"pdf_url": loc["url"], "pdf_source": loc["source"],
                                   "license": loc.get("license") or ""})
                    if args.no_download:
                        break
                    destination = args.pdf_dir / safe_pdf_name(
                        {"report_year": result["report_year"], "title": result["original_title"]},
                        result["doi"],
                    )
                    ok, status = download_pdf(loc["url"], destination, args.max_pdf_mb * 1024 * 1024)
                    result["download_status"] = status
                    if ok:
                        result["local_pdf"] = str(destination)
                        break
                cache[record_id] = result
                cache_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                cache_handle.flush()
                retried += 1
                print(f"retry {retried}: {result['download_status']} {result['original_title'][:70]}")
                time.sleep(args.delay)
        candidates = []
    else:
        candidates = list(candidate_rows.values())
    processed = 0
    with cache_path.open("a", encoding="utf-8") as cache_handle:
        for row in candidates:
            cached = cache.get(row["record_id"])
            if ((cached and not args.refresh and cached.get("match_status") != "api_error")
                    or float(row["confidence"]) < args.min_confidence):
                continue
            if args.limit is not None and processed >= args.limit:
                break
            result = {"record_id": row["record_id"], "report_year": row["report_year"],
                      "original_title": row["title"], "normalized_title": normalize_title(row["title"]),
                      "match_status": "unmatched", "match_source": "", "match_score": 0, "canonical_title": "", "doi": "",
                      "publication_year": "", "work_type": "", "authors": "", "openalex_work_id": "",
                      "openalex_authorships": "", "landing_url": "",
                      "pdf_url": "", "pdf_source": "", "license": "", "local_pdf": "",
                      "download_status": "not_attempted", "abstract": "", "abstract_source": "",
                      "local_abstract": ""}
            try:
                item, score = select_crossref_match(row, args.match_threshold)
                result["match_score"] = score
                if item:
                    doi = item.get("DOI", "").lower()
                    result.update({"match_status": "matched", "match_source": "crossref", "canonical_title": (item.get("title") or [""])[0],
                                   "doi": doi, "publication_year": crossref_year(item) or "",
                                   "work_type": item.get("type", ""),
                                   "authors": "; ".join(" ".join(filter(None, [a.get("given"), a.get("family")]))
                                                        for a in item.get("author") or []),
                                   "landing_url": item.get("URL", "")})
                    locations, abstract, abstract_source, openalex_work = (
                        oa_metadata(doi, item, openalex_api_key)
                        if doi else ([], clean_abstract(item.get("abstract")), "crossref", {})
                    )
                    if openalex_work:
                        structured_authors = openalex_authorships(openalex_work)
                        result["openalex_work_id"] = openalex_work.get("id") or ""
                        result["openalex_authorships"] = encode_authorships(structured_authors)
                        result["authors"] = "; ".join(
                            entry["display_name"] for entry in structured_authors if entry["display_name"]
                        )
                    if abstract:
                        abstract_name = Path(safe_pdf_name(row, doi or row["record_id"])).with_suffix(".txt")
                        abstract_path = args.abstract_dir / abstract_name
                        abstract_path.parent.mkdir(parents=True, exist_ok=True)
                        abstract_path.write_text(abstract + "\n", encoding="utf-8")
                        result.update({"abstract": abstract, "abstract_source": abstract_source,
                                       "local_abstract": str(abstract_path)})
                    if locations:
                        for loc in locations:
                            result.update({"pdf_url": loc["url"], "pdf_source": loc["source"],
                                           "license": loc.get("license") or ""})
                            if args.no_download:
                                break
                            destination = args.pdf_dir / safe_pdf_name(row, doi)
                            ok, status = download_pdf(loc["url"], destination, args.max_pdf_mb * 1024 * 1024)
                            result["download_status"] = status
                            if ok:
                                result["local_pdf"] = str(destination)
                                break
                cache[row["record_id"]] = result
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                result["match_status"] = "api_error"
                result["download_status"] = type(exc).__name__
                cache[row["record_id"]] = result
            cache_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            cache_handle.flush()
            processed += 1
            print(f"{processed}: {result['match_status']} {result['match_score']} {row['title'][:70]}")
            time.sleep(args.delay)

    records = [cache[key] for key in sorted(cache)]
    write_csv(args.output_dir / "publication_resolution.csv", records)
    write_csv(
        args.output_dir / "openalex_fallback_matches.csv",
        [record for record in records if record.get("match_source") == "openalex_search"],
    )
    summary = {"cached_records": len(records),
               "matched": sum(r["match_status"] == "matched" for r in records),
               "matched_crossref": sum(r.get("match_source", "crossref") == "crossref" and r["match_status"] == "matched" for r in records),
               "matched_openalex_search": sum(r.get("match_source") == "openalex_search" for r in records),
               "unmatched": sum(r["match_status"] == "unmatched" for r in records),
               "api_errors": sum(r["match_status"] == "api_error" for r in records),
               "pdf_locations": sum(bool(r["pdf_url"]) for r in records),
               "pdfs_downloaded": sum(r["download_status"] == "downloaded" for r in records),
               "abstracts_downloaded": sum(bool(r.get("abstract")) for r in records)}
    (args.output_dir / "resolution_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
