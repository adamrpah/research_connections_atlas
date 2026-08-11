#!/usr/bin/env python3
"""Refresh publication-level OpenAlex impact measures without citation records.

One current row is written per deduplicated publication, and successful observations
are appended to a dated snapshot file. No citing-work or citation-edge data is stored.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from resolve_and_download_publications import request_json


IMPACT_FIELDS = [
    "publication_id", "openalex_work_id", "doi", "canonical_title",
    "publication_year", "publication_date", "impact_observed_at",
    "openalex_updated_date", "cited_by_count", "citations_by_year", "fwci",
    "citation_percentile", "is_top_10_percent", "is_top_1_percent",
    "same_year_percentile_min", "same_year_percentile_max",
    "referenced_works_count", "is_oa", "oa_status", "is_retracted",
    "publication_age_years", "citations_per_year", "citations_last_1_year",
    "citations_last_2_years", "citations_last_5_years", "recent_citation_share",
    "years_since_earliest_reported_citation", "citation_active_years", "is_uncited",
]


def text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def title_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text(value).casefold()).strip()


def publication_id(doi: object, title: object) -> str:
    key = f"doi:{text(doi).lower()}" if text(doi) else f"title:{title_key(title)}"
    return "pub_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=IMPACT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def parse_observed_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc, microsecond=0)


def numeric(value: object) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def publication_age(publication_date: object, publication_year: object, observed: datetime) -> float:
    try:
        published = date.fromisoformat(text(publication_date))
        return max((observed.date() - published).days / 365.2425, 0.0)
    except ValueError:
        year = numeric(publication_year)
        return max(observed.year - int(year) + 0.5, 0.0) if year else 0.0


def extract_impact(work: dict, source: dict, observed: datetime) -> dict:
    counts = sorted(
        ({"year": int(row["year"]), "cited_by_count": int(row.get("cited_by_count") or 0)}
         for row in work.get("counts_by_year") or [] if row.get("year")),
        key=lambda row: row["year"],
    )
    by_year = {row["year"]: row["cited_by_count"] for row in counts}
    cited_by_count = int(work.get("cited_by_count") or 0)
    normalized = work.get("citation_normalized_percentile") or {}
    same_year = work.get("cited_by_percentile_year") or {}
    open_access = work.get("open_access") or {}
    year = work.get("publication_year") or source.get("publication_year") or ""
    age = publication_age(work.get("publication_date"), year, observed)
    recent_two = sum(by_year.get(year_value, 0) for year_value in range(observed.year - 1, observed.year + 1))
    active_years = sorted(year_value for year_value, count in by_year.items() if count > 0)
    return {
        "publication_id": publication_id(source.get("doi"), source.get("canonical_title")),
        "openalex_work_id": work.get("id") or source.get("openalex_work_id") or "",
        "doi": text(source.get("doi")),
        "canonical_title": text(source.get("canonical_title")),
        "publication_year": year,
        "publication_date": work.get("publication_date") or "",
        "impact_observed_at": observed.isoformat().replace("+00:00", "Z"),
        "openalex_updated_date": work.get("updated_date") or "",
        "cited_by_count": cited_by_count,
        "citations_by_year": json.dumps(counts, separators=(",", ":")),
        "fwci": "" if work.get("fwci") is None else work["fwci"],
        "citation_percentile": normalized.get("value", ""),
        "is_top_10_percent": normalized.get("is_in_top_10_percent", ""),
        "is_top_1_percent": normalized.get("is_in_top_1_percent", ""),
        "same_year_percentile_min": same_year.get("min", ""),
        "same_year_percentile_max": same_year.get("max", ""),
        "referenced_works_count": work.get("referenced_works_count", ""),
        "is_oa": open_access.get("is_oa", ""),
        "oa_status": open_access.get("oa_status", ""),
        "is_retracted": bool(work.get("is_retracted")),
        "publication_age_years": round(age, 4),
        "citations_per_year": round(cited_by_count / max(age, 1.0), 4),
        "citations_last_1_year": by_year.get(observed.year, 0),
        "citations_last_2_years": recent_two,
        "citations_last_5_years": sum(
            by_year.get(year_value, 0) for year_value in range(observed.year - 4, observed.year + 1)
        ),
        "recent_citation_share": round(recent_two / cited_by_count, 4) if cited_by_count else 0.0,
        "years_since_earliest_reported_citation": observed.year - active_years[0] if active_years else "",
        "citation_active_years": len(active_years),
        "is_uncited": cited_by_count == 0,
    }


def deduplicate_resolution(rows: list[dict]) -> list[dict]:
    works: dict[str, dict] = {}
    for row in rows:
        if text(row.get("match_status")) != "matched" or not text(row.get("openalex_work_id")):
            continue
        key = publication_id(row.get("doi"), row.get("canonical_title"))
        current = works.get(key)
        if current is None or len(text(row.get("canonical_title"))) > len(text(current.get("canonical_title"))):
            works[key] = row
    return [works[key] for key in sorted(works)]


def refresh(
    resolution_path: Path, output_dir: Path, api_key: str, observed: datetime,
    delay: float = 0.1, limit: int | None = None,
) -> dict:
    all_sources = deduplicate_resolution(read_csv(resolution_path))
    eligible_ids = {
        publication_id(row.get("doi"), row.get("canonical_title")) for row in all_sources
    }
    sources = all_sources
    if limit is not None:
        sources = sources[:limit]
    current_path = output_dir / "current_work_impact.csv"
    snapshot_path = output_dir / "work_impact_snapshots.csv"
    previous = {
        row["publication_id"]: row for row in read_csv(current_path)
        if row.get("publication_id") in eligible_ids
    }
    refreshed, failures = {}, []
    for index, source in enumerate(sources, start=1):
        work_id = text(source.get("openalex_work_id"))
        try:
            work = request_json(
                f"https://api.openalex.org/works/{quote(work_id.rsplit('/', 1)[-1], safe='')}",
                {"api_key": api_key},
            )
            row = extract_impact(work, source, observed)
            refreshed[row["publication_id"]] = row
            print(f"impact {index}: {row['cited_by_count']} citations {row['canonical_title'][:70]}")
        except Exception as exc:  # preserve the last successful snapshot on transient/API failures
            failures.append({"openalex_work_id": work_id, "error": type(exc).__name__})
        if delay:
            time.sleep(delay)
    current = dict(previous)
    current.update(refreshed)
    current_rows = [current[key] for key in sorted(current)]
    snapshots = {
        (row.get("publication_id", ""), row.get("impact_observed_at", "")): row
        for row in read_csv(snapshot_path)
    }
    for row in refreshed.values():
        snapshots[(row["publication_id"], row["impact_observed_at"])] = row
    snapshot_rows = [snapshots[key] for key in sorted(snapshots)]
    write_csv(current_path, current_rows)
    write_csv(snapshot_path, snapshot_rows)
    qa = {
        "impact_observed_at": observed.isoformat().replace("+00:00", "Z"),
        "eligible_openalex_publications": len(all_sources),
        "attempted_publications": len(sources),
        "refreshed_publications": len(refreshed),
        "retained_previous_publications": len(set(previous) - set(refreshed)),
        "current_publications": len(current_rows),
        "snapshot_rows": len(snapshot_rows),
        "failures": failures,
        "stores_individual_citation_records": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "impact_qa.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    return qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=Path,
                        default=Path("results/publication_resolution/publication_resolution.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/impact"))
    parser.add_argument("--openalex-api-key-file", type=Path, required=True)
    parser.add_argument("--observed-at", help="ISO timestamp override, primarily for reproducible tests")
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    api_key = args.openalex_api_key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        raise SystemExit("OpenAlex API key file is empty")
    qa = refresh(args.resolution, args.output_dir, api_key, parse_observed_at(args.observed_at),
                 args.delay, args.limit)
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
