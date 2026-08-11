#!/usr/bin/env python3
"""Aggregate publication impact only after final reviewed faculty attribution."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


FIELDS = [
    "faculty_id", "faculty_name", "impact_observed_at", "attributed_publication_count",
    "publications_with_openalex_metrics", "impact_coverage_share", "total_citations",
    "mean_citations", "median_citations", "uncited_publication_count",
    "uncited_publication_share", "mean_fwci", "median_fwci", "top_10_percent_count",
    "top_10_percent_share", "top_1_percent_count", "top_1_percent_share",
    "citations_last_2_years", "citations_last_5_years", "corpus_h_index",
    "corpus_i10_index",
]


def finite(values: pd.Series) -> pd.Series:
    result = pd.to_numeric(values, errors="coerce")
    return result[result.map(math.isfinite)]


def h_index(citations: list[int]) -> int:
    return max((rank for rank, value in enumerate(sorted(citations, reverse=True), 1) if value >= rank), default=0)


def build_summary(attributions: pd.DataFrame, impact: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    attribution_pairs = attributions[["faculty_name", "publication_id"]].drop_duplicates()
    joined = attribution_pairs.merge(impact, on="publication_id", how="left", indicator=True)
    faculty_ids = dict(zip(registry["faculty_name"], registry["faculty_id"]))
    rows = []
    for faculty, group in joined.groupby("faculty_name", sort=True):
        measured = group[group["_merge"] == "both"].copy()
        citations = finite(measured.get("cited_by_count", pd.Series(dtype=float))).astype(int).tolist()
        fwci = finite(measured.get("fwci", pd.Series(dtype=float)))
        normalized = measured[pd.to_numeric(measured.get("citation_percentile"), errors="coerce").notna()]
        total = len(group)
        measured_count = len(measured)
        rows.append({
            "faculty_id": faculty_ids.get(faculty, ""), "faculty_name": faculty,
            "impact_observed_at": max(measured.get("impact_observed_at", pd.Series([""])).astype(str), default=""),
            "attributed_publication_count": total,
            "publications_with_openalex_metrics": measured_count,
            "impact_coverage_share": round(measured_count / total, 4) if total else 0,
            "total_citations": sum(citations),
            "mean_citations": round(float(pd.Series(citations).mean()), 4) if citations else "",
            "median_citations": round(float(pd.Series(citations).median()), 4) if citations else "",
            "uncited_publication_count": sum(value == 0 for value in citations),
            "uncited_publication_share": round(sum(value == 0 for value in citations) / len(citations), 4) if citations else "",
            "mean_fwci": round(float(fwci.mean()), 4) if len(fwci) else "",
            "median_fwci": round(float(fwci.median()), 4) if len(fwci) else "",
            "top_10_percent_count": int(normalized.get("is_top_10_percent", pd.Series(dtype=bool)).astype(str).str.lower().eq("true").sum()),
            "top_10_percent_share": round(normalized.get("is_top_10_percent", pd.Series(dtype=bool)).astype(str).str.lower().eq("true").sum() / len(normalized), 4) if len(normalized) else "",
            "top_1_percent_count": int(normalized.get("is_top_1_percent", pd.Series(dtype=bool)).astype(str).str.lower().eq("true").sum()),
            "top_1_percent_share": round(normalized.get("is_top_1_percent", pd.Series(dtype=bool)).astype(str).str.lower().eq("true").sum() / len(normalized), 4) if len(normalized) else "",
            "citations_last_2_years": int(finite(measured.get("citations_last_2_years", pd.Series(dtype=float))).sum()),
            "citations_last_5_years": int(finite(measured.get("citations_last_5_years", pd.Series(dtype=float))).sum()),
            "corpus_h_index": h_index(citations),
            "corpus_i10_index": sum(value >= 10 for value in citations),
        })
    return pd.DataFrame(rows, columns=FIELDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attributions", type=Path,
                        default=Path("results/faculty_attribution/article_faculty_attributions.csv"))
    parser.add_argument("--impact", type=Path, default=Path("results/impact/current_work_impact.csv"))
    parser.add_argument("--registry", type=Path,
                        default=Path("results/faculty_attribution/faculty_registry.csv"))
    parser.add_argument("--output", type=Path, default=Path("results/impact/faculty_impact_summary.csv"))
    parser.add_argument("--qa", type=Path, default=Path("results/impact/faculty_impact_qa.json"))
    args = parser.parse_args()
    if not args.impact.exists():
        print(f"Work impact file not found; faculty impact skipped: {args.impact}")
        return
    summary = build_summary(
        pd.read_csv(args.attributions).fillna(""), pd.read_csv(args.impact).fillna(""),
        pd.read_csv(args.registry).fillna(""),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.output, index=False)
    qa = {
        "faculty": len(summary),
        "attributed_publications": int(summary["attributed_publication_count"].sum()) if len(summary) else 0,
        "faculty_publications_with_metrics": int(summary["publications_with_openalex_metrics"].sum()) if len(summary) else 0,
        "author_metrics_run_after_final_attribution": True,
    }
    args.qa.write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
