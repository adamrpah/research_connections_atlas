#!/usr/bin/env python3
"""Generate topic metadata and propagate article topics to report faculty.

Labels are derived deterministically from each clustering run's c-TF-IDF terms, so
the stage supports any number of topics and does not assume stable cluster IDs.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


NOISE_LABEL = "Unclustered / Cross-Cutting Research"
NOISE_DESCRIPTION = "Research not assigned to a sufficiently dense topic cluster; these works may be interdisciplinary, niche, or underrepresented in this corpus."

NON_PERSON_HEADINGS = {
    "refereed journal articles", "journal articles", "book chapters",
    "graduate student", "former graduate student",
}

ALIASES = {
    "greg streib": "Gregory Streib",
    "tina smith": "Tina Anderson Smith",
    "jameson boex": "Jameson Boex",
    "vjollca sadiraj": "Vjollca Sadiraj",
    "gary cornia": "Gary Cornia",
    "mark rider": "Mark Rider",
    "benno torgler": "Benno Torgler",
    "grant black": "Grant Black",
    "david rein": "David Rein",
    "sri mulyani indrawati": "Sri Mulyani Indrawati",
    "chiara franzoni": "Chiara Franzoni",
    "resul cesur": "Resul Cesur",
    "wasseem mina": "Wasseem Mina",
    "shiferaw girmu": "Shiferaw Gurmu",
    "klara sabiranova peter": "Klara Sabirianova Peter",
    "jonathan rork": "Jon Rork",
    "professor andrew feltenstein": "Andrew Feltenstein",
    "glen ross": "Glenwood Ross",
}

GENERIC_LABEL_TERMS = {
    "analysis", "data", "effect", "effects", "evidence", "model", "models",
    "policy", "research", "study", "theory", "using", "countries", "program",
}
ACRONYMS = {"aca", "bmi", "chip", "covid", "iq", "lgb", "lgbtq", "medicaid", "ppe", "sat", "scd", "snap"}


def display_term(term: str) -> str:
    return " ".join(word.upper() if word.casefold() in ACRONYMS else word.capitalize() for word in term.split())


def topic_metadata(topics: pd.DataFrame) -> dict[int, tuple[str, str]]:
    """Build stable, human-readable labels from the terms produced in this run."""
    metadata: dict[int, tuple[str, str]] = {}
    used_labels: Counter[str] = Counter()
    for row in topics.sort_values("topic_id").to_dict(orient="records"):
        topic_id = int(row["topic_id"])
        terms = [term.strip() for term in str(row.get("top_terms", "")).split(";") if term.strip()]
        distinctive: list[str] = []
        for term in terms:
            normalized = term.casefold()
            if normalized in GENERIC_LABEL_TERMS:
                continue
            tokens = set(normalized.split())
            if any(tokens <= set(existing.casefold().split()) or set(existing.casefold().split()) <= tokens
                   for existing in distinctive):
                continue
            distinctive.append(term)
            if len(distinctive) == 3:
                break
        if not distinctive:
            distinctive = terms[:3] or [f"Topic {topic_id}"]
        label = " • ".join(display_term(term) for term in distinctive)
        used_labels[label] += 1
        if used_labels[label] > 1:
            label = f"{label} ({topic_id})"
        detail_terms = terms[:8] or distinctive
        description = "Research cluster characterized by " + ", ".join(detail_terms) + "."
        metadata[topic_id] = (label, description)
    return metadata


def normalize_faculty(value: object) -> tuple[str | None, str]:
    """Return normalized display name and an attribution status."""
    if pd.isna(value) or not str(value).strip():
        return None, "missing_heading"
    raw = re.sub(r"\s+", " ", str(value)).strip()
    cleaned = re.sub(r"\*+$", "", raw).strip()
    key = cleaned.casefold()
    if key in NON_PERSON_HEADINGS:
        return None, "non_person_heading"
    return ALIASES.get(key, cleaned), "attributed"


def split_ids(value: object) -> list[str]:
    return [x.strip() for x in str(value).split(";") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--model-dir", type=Path, default=Path("results/topic_model_specter2"))
    parser.add_argument("--labels-only", action="store_true", help="Write topic labels without heading-based faculty propagation")
    args = parser.parse_args()

    topic_path = args.model_dir / "topics.csv"
    assignment_path = args.model_dir / "article_topic_assignments.csv"
    candidates = pd.read_csv(args.candidates, dtype={"record_id": str})
    topics = pd.read_csv(topic_path)
    articles = pd.read_csv(assignment_path, dtype={"record_id": str, "source_record_ids": str})

    labels = topic_metadata(topics)

    labeled_topics = topics.copy()
    labeled_topics["topic_label"] = labeled_topics["topic_id"].map(lambda x: labels[int(x)][0])
    labeled_topics["topic_description"] = labeled_topics["topic_id"].map(lambda x: labels[int(x)][1])
    labeled_topics = labeled_topics[["topic_id", "topic_label", "topic_description", "size", "top_terms", "representative_titles"]]
    labeled_topics.to_csv(args.model_dir / "labeled_topics.csv", index=False)
    (args.model_dir / "labeled_topics.json").write_text(
        json.dumps(labeled_topics.to_dict(orient="records"), indent=2), encoding="utf-8"
    )

    articles["topic_label"] = articles["topic_id"].map(
        lambda x: NOISE_LABEL if int(x) == -1 else labels[int(x)][0]
    )
    articles["topic_description"] = articles["topic_id"].map(
        lambda x: NOISE_DESCRIPTION if int(x) == -1 else labels[int(x)][1]
    )
    articles.to_csv(args.model_dir / "labeled_article_topics.csv", index=False)

    if args.labels_only:
        print(json.dumps({
            "topic_count": int(len(labeled_topics)),
            "unique_modeled_works": int(len(articles)),
            "faculty_attribution": "deferred_to_openalex_metadata_resolver",
        }, indent=2))
        return

    candidate_lookup = candidates.set_index("record_id", drop=False).to_dict(orient="index")
    faculty_work_rows: list[dict] = []
    unattributed_rows: list[dict] = []
    status_counts: Counter[str] = Counter()

    for article in articles.to_dict(orient="records"):
        faculty_sources: dict[str, list[dict]] = {}
        for source_id in split_ids(article["source_record_ids"]):
            source = candidate_lookup.get(source_id)
            if source is None:
                status_counts["source_record_not_found"] += 1
                unattributed_rows.append({
                    "record_id": article["record_id"], "source_record_id": source_id,
                    "reason": "source_record_not_found", "faculty_heading": "",
                    "canonical_title": article["canonical_title"], "topic_id": article["topic_id"],
                    "topic_label": article["topic_label"],
                })
                continue
            faculty, status = normalize_faculty(source.get("faculty_heading"))
            status_counts[status] += 1
            if faculty is None:
                unattributed_rows.append({
                    "record_id": article["record_id"], "source_record_id": source_id,
                    "reason": status, "faculty_heading": source.get("faculty_heading", ""),
                    "canonical_title": article["canonical_title"], "topic_id": article["topic_id"],
                    "topic_label": article["topic_label"],
                })
                continue
            faculty_sources.setdefault(faculty, []).append(source)

        for faculty, sources in faculty_sources.items():
            years = sorted({int(s["report_year"]) for s in sources if pd.notna(s.get("report_year"))})
            faculty_work_rows.append({
                "faculty_name": faculty,
                "record_id": article["record_id"],
                "source_record_ids": ";".join(str(s["record_id"]) for s in sources),
                "report_years": ";".join(map(str, years)),
                "canonical_title": article["canonical_title"],
                "doi": article.get("doi", ""),
                "topic_id": int(article["topic_id"]),
                "topic_label": article["topic_label"],
                "topic_description": article["topic_description"],
                "topic_probability": article["topic_probability"],
            })

    faculty_works = pd.DataFrame(faculty_work_rows).sort_values(["faculty_name", "topic_id", "canonical_title"])
    faculty_works.to_csv(args.model_dir / "faculty_topic_publications.csv", index=False)
    pd.DataFrame(unattributed_rows).to_csv(args.model_dir / "unattributed_topic_publications.csv", index=False)

    clustered = faculty_works[faculty_works["topic_id"] >= 0].copy()
    totals = faculty_works.groupby("faculty_name")["record_id"].nunique().rename("modeled_publications")
    clustered_totals = clustered.groupby("faculty_name")["record_id"].nunique().rename("clustered_publications")
    summary_rows = []
    for (faculty, topic_id), group in clustered.groupby(["faculty_name", "topic_id"], sort=True):
        titles = group.sort_values("topic_probability", ascending=False)["canonical_title"].drop_duplicates().head(3)
        summary_rows.append({
            "faculty_name": faculty,
            "topic_id": int(topic_id),
            "topic_label": labels[int(topic_id)][0],
            "topic_description": labels[int(topic_id)][1],
            "publication_count": group["record_id"].nunique(),
            "mean_topic_probability": round(float(group["topic_probability"].mean()), 4),
            "representative_titles": " | ".join(titles),
        })
    summary = pd.DataFrame(summary_rows)
    summary = summary.merge(totals, on="faculty_name").merge(clustered_totals, on="faculty_name")
    summary["share_of_faculty_clustered_publications"] = (
        summary["publication_count"] / summary["clustered_publications"]
    ).round(4)
    summary = summary.sort_values(["faculty_name", "publication_count", "topic_id"], ascending=[True, False, True])
    summary.to_csv(args.model_dir / "faculty_topic_summary.csv", index=False)

    matrix = clustered.pivot_table(
        index="faculty_name", columns="topic_label", values="record_id", aggfunc="nunique", fill_value=0
    ).astype(int).reset_index()
    matrix.to_csv(args.model_dir / "faculty_topic_matrix.csv", index=False)

    profiles = []
    for faculty, group in summary.groupby("faculty_name", sort=True):
        profiles.append({
            "faculty_name": faculty,
            "modeled_publications": int(group["modeled_publications"].iloc[0]),
            "clustered_publications": int(group["clustered_publications"].iloc[0]),
            "topics": group[["topic_id", "topic_label", "topic_description", "publication_count",
                             "mean_topic_probability", "share_of_faculty_clustered_publications",
                             "representative_titles"]].to_dict(orient="records"),
        })
    (args.model_dir / "faculty_topic_profiles.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")

    qa = {
        "topic_count": len(labels),
        "unique_modeled_works": int(len(articles)),
        "clustered_works": int((articles["topic_id"] >= 0).sum()),
        "faculty_names": int(faculty_works["faculty_name"].nunique()),
        "faculty_work_links": int(len(faculty_works)),
        "attributed_unique_works": int(faculty_works["record_id"].nunique()),
        "unattributed_unique_works": int(articles.loc[~articles["record_id"].isin(faculty_works["record_id"]), "record_id"].nunique()),
        "source_attribution_status_counts": dict(status_counts),
        "note": "Faculty attribution comes from annual-report faculty headings. It identifies the faculty member under whom a work was listed, not necessarily every AYS coauthor.",
    }
    (args.model_dir / "faculty_topic_qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
