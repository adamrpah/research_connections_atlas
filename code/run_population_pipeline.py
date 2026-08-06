#!/usr/bin/env python3
"""Populate publication data from reports, resolve it, and reconcile annual counts.

Two modes are supported:

* append (default): preserve existing candidates and add unseen extracted records;
  the resolver processes only records that are not already cached.
* rebuild: replace the candidate dataset with a fresh extraction, prune resolution
  cache entries that are no longer candidates, and re-resolve every candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


FIELDS = [
    "record_id", "report_year", "report_file", "pdf_page", "faculty_heading",
    "title", "raw_citation", "extraction_method", "confidence", "needs_review", "category",
    "is_ongoing", "institutional_faculty_ids", "institutional_faculty_names",
    "institutional_author_evidence",
]


def run(command: list[str], label: str, cwd: Path) -> None:
    print(f"\n[{label}]", flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def read_candidates(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def merge_candidates(existing: list[dict], extracted: list[dict], mode: str) -> tuple[list[dict], int]:
    base = [] if mode == "rebuild" else existing
    merged = list(base)
    seen = {row["record_id"] for row in base}
    added = 0
    for row in extracted:
        if row["record_id"] in seen:
            continue
        seen.add(row["record_id"])
        merged.append(row)
        added += 1
    return merged, added


def write_candidates(rows: list[dict], csv_path: Path, jsonl_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    jsonl_tmp = jsonl_path.with_suffix(jsonl_path.suffix + ".tmp")
    with csv_tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with jsonl_tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    csv_tmp.replace(csv_path)
    jsonl_tmp.replace(jsonl_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("append", "rebuild"), default="append")
    parser.add_argument("--pdf-input-dir", type=Path, default=Path("data/Annual-Reports"))
    parser.add_argument("--digitalmeasure-input-dir", type=Path, default=Path("data/DigitalMeasure-Reports"))
    parser.add_argument("--candidates", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--faculty-identifiers", type=Path,
                        default=Path("data/faculty_identifiers.csv"))
    parser.add_argument("--resolution-dir", type=Path, default=Path("results/publication_resolution"))
    parser.add_argument("--openalex-api-key-file", type=Path)
    parser.add_argument("--limit", type=int, help="Limit records handled in each resolution pass")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--skip-openalex-fallback", action="store_true")
    parser.add_argument("--skip-resolution", action="store_true", help="Extract and reconcile without network resolution")
    parser.add_argument("--skip-reconciliation", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Extract and report candidate changes without modifying results or resolving")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    python = sys.executable
    candidates_path = root / args.candidates
    jsonl_path = candidates_path.with_suffix(".jsonl")

    for input_dir, label in ((args.pdf_input_dir, "PDF"), (args.digitalmeasure_input_dir, "Digital Measures")):
        if not (root / input_dir).is_dir():
            raise SystemExit(f"{label} input directory not found: {input_dir}")
    if args.openalex_api_key_file and not (root / args.openalex_api_key_file).is_file():
        raise SystemExit(f"OpenAlex API key file not found: {args.openalex_api_key_file}")

    with tempfile.TemporaryDirectory(prefix="ays-population-") as staging_name:
        staging = Path(staging_name)
        run([
            python, str(root / "code/extract_publications.py"),
            "--input-dir", str(root / args.pdf_input_dir), "--output-dir", str(staging),
        ], "annual-report PDF extraction", root)
        run([
            python, str(root / "code/extract_digitalmeasure_publications.py"),
            "--input-dir", str(root / args.digitalmeasure_input_dir),
            "--candidates", str(staging / "publication_candidates.csv"),
            "--summary", str(staging / "digitalmeasure_extraction_summary.json"),
            "--all-records-output", str(staging / "digitalmeasure_extracted_records.csv"),
            "--faculty-registry-output", str(staging / "institutional_faculty_registry.csv"),
            "--faculty-name-overrides", str(root / "data/faculty_name_overrides.csv"),
            "--faculty-identifiers", str(root / args.faculty_identifiers),
        ], "Digital Measures extraction", root)

        extracted = read_candidates(staging / "publication_candidates.csv")
        existing = read_candidates(candidates_path)
        merged, added = merge_candidates(existing, extracted, args.mode)
        status = {
            "mode": args.mode,
            "existing_candidates": len(existing),
            "freshly_extracted_candidates": len(extracted),
            "candidates_added": added,
            "final_candidates": len(merged),
            "dry_run": args.dry_run,
        }
        print("\n[candidate merge]")
        print(json.dumps(status, indent=2))
        if args.dry_run:
            return

        write_candidates(merged, candidates_path, jsonl_path)
        results = root / "results"
        shutil.copy2(staging / "extraction_summary.json", results / "extraction_summary.json")
        shutil.copy2(
            staging / "digitalmeasure_extraction_summary.json",
            results / "digitalmeasure_extraction_summary.json",
        )
        shutil.copy2(
            staging / "digitalmeasure_extracted_records.csv",
            results / "digitalmeasure_extracted_records.csv",
        )
        shutil.copy2(
            staging / "institutional_faculty_registry.csv",
            results / "institutional_faculty_registry.csv",
        )
        (results / "population_pipeline_summary.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )

    if not args.skip_resolution:
        resolver = [
            python, str(root / "code/resolve_and_download_publications.py"),
            "--input", str(candidates_path), "--output-dir", str(root / args.resolution_dir),
        ]
        if args.openalex_api_key_file:
            resolver += ["--openalex-api-key-file", str(root / args.openalex_api_key_file)]
        if args.limit is not None:
            resolver += ["--limit", str(args.limit)]
        if args.no_download:
            resolver.append("--no-download")
        if args.mode == "rebuild":
            resolver += ["--refresh", "--prune-cache-to-input"]
        run(resolver, "Crossref resolution and OA metadata/downloads", root)

        if args.openalex_api_key_file and not args.skip_openalex_fallback:
            fallback = resolver.copy()
            fallback += ["--openalex-fallback"]
            # Fallback acts on the unmatched cache produced above; refresh/pruning
            # belong only to the primary pass.
            fallback = [item for item in fallback if item not in {"--refresh", "--prune-cache-to-input"}]
            run(fallback, "OpenAlex fallback resolution", root)
        elif not args.openalex_api_key_file and not args.skip_openalex_fallback:
            print("\n[OpenAlex fallback] skipped: no --openalex-api-key-file supplied")

    resolution_path = root / args.resolution_dir / "publication_resolution.csv"
    if resolution_path.exists():
        run([
            python, str(root / "code/apply_publication_metadata_curation.py"),
            "--resolution", str(resolution_path),
        ], "human metadata curation", root)

    if not args.skip_reconciliation:
        run([
            python, str(root / "code/reconcile_publication_counts.py"),
            "--candidates", str(candidates_path),
        ], "publication-count reconciliation", root)

    print("\nPopulation pipeline complete.")


if __name__ == "__main__":
    main()
