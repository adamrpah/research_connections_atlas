#!/usr/bin/env python3
"""Run topic, attribution, web-data, and application refresh stages in order."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


WEBAPP_FILES = [
    "faculty.json", "topics.json", "faculty_profiles.json", "faculty_similarity_edges.json",
    "faculty_topic_edges.json", "publications.json", "manifest.json",
]


def run(command: list[str], label: str, cwd: Path | None = None) -> None:
    print(f"\n[{label}]", flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-clustering", action="store_true", help="Reuse current topic assignments and embeddings")
    parser.add_argument("--skip-feedback-fetch", action="store_true", help="Do not retrieve new submitted attribution feedback")
    parser.add_argument("--skip-attribution-review-import", action="store_true", help="Do not import the local reviewed attribution workbook")
    parser.add_argument("--skip-app-build", action="store_true", help="Refresh app data without running its production build")
    parser.add_argument("--refresh-openalex-impact", action="store_true",
                        help="Refresh publication-level citation measures before aggregation")
    parser.add_argument("--openalex-api-key-file", type=Path)
    parser.add_argument("--device", choices=["auto", "cpu", "mps", "cuda"], default="auto")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    python = sys.executable

    if not args.skip_feedback_fetch:
        run([python, str(root / "code/fetch_attribution_feedback.py")], "feedback export")
    review_workbook = root / "data/faculty_attribution_review.xlsx"
    if review_workbook.exists() and not args.skip_attribution_review_import:
        run([python, str(root / "code/import_faculty_attribution_review.py")], "faculty attribution review import")
    run([python, str(root / "code/apply_publication_metadata_curation.py")], "human metadata curation")
    if args.refresh_openalex_impact:
        if not args.openalex_api_key_file:
            raise SystemExit("--refresh-openalex-impact requires --openalex-api-key-file")
        run([
            python, str(root / "code/refresh_openalex_impact.py"),
            "--openalex-api-key-file", str(root / args.openalex_api_key_file),
        ], "OpenAlex publication impact refresh")
    if not args.skip_clustering:
        run([python, str(root / "code/cluster_publications.py"), "--device", args.device], "topic clustering")
    run([python, str(root / "code/label_and_propagate_topics.py"), "--labels-only"], "topic labeling")
    run([python, str(root / "code/resolve_faculty_attributions.py")], "faculty attribution")
    run([python, str(root / "code/build_faculty_impact_summary.py")],
        "post-disambiguation faculty impact summary")
    run([python, str(root / "code/build_webapp_data.py")], "web-app data build")

    source, destination = root / "results/webapp", root / "webapp/public/data"
    destination.mkdir(parents=True, exist_ok=True)
    for filename in WEBAPP_FILES:
        shutil.copy2(source / filename, destination / filename)
    print(f"\n[app data] refreshed {len(WEBAPP_FILES)} files in {destination.relative_to(root)}", flush=True)
    if not args.skip_app_build:
        run(["npm", "run", "build"], "web-app production build", cwd=root / "webapp")
    print("\nPipeline refresh complete.", flush=True)


if __name__ == "__main__":
    main()
