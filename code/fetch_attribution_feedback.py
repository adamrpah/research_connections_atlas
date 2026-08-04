#!/usr/bin/env python3
"""Securely export attribution feedback and flag complaints awaiting review."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("FEEDBACK_EXPORT_URL"),
        help="Attribution-feedback export URL (or set FEEDBACK_EXPORT_URL)",
    )
    parser.add_argument("--key-file", type=Path, default=Path(".secrets/feedback_admin_key"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/feedback"))
    parser.add_argument("--overrides", type=Path, default=Path("data/faculty_attribution_overrides.csv"))
    args = parser.parse_args()
    if not args.url:
        raise SystemExit("Feedback export URL required: pass --url or set FEEDBACK_EXPORT_URL")
    key = args.key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"Empty feedback administrator key: {args.key_file}")
    request = urllib.request.Request(args.url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "attribution_feedback.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    feedback = pd.DataFrame(payload.get("feedback", []))
    approved_ids: set[str] = set()
    if args.overrides.exists():
        approved_ids = set(pd.read_csv(args.overrides, dtype=str).fillna("")["feedback_id"])
    if not feedback.empty:
        feedback["review_status"] = feedback["id"].map(lambda value: "approved" if value in approved_ids else "needs_review")
    feedback.to_csv(args.output_dir / "attribution_feedback_review.csv", index=False)
    pending = int((feedback.get("review_status", pd.Series(dtype=str)) == "needs_review").sum())
    print(json.dumps({"downloaded": len(feedback), "approved": len(feedback) - pending, "needs_review": pending}, indent=2))


if __name__ == "__main__":
    main()
