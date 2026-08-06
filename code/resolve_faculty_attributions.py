#!/usr/bin/env python3
"""Resolve publications to faculty using local citation and OpenAlex evidence.

The Digital Measures faculty registry bounds the institutional population before
network resolution. Provisional citation-based links keep unmatched works usable;
OpenAlex authorships subsequently enrich and disambiguate those links.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from label_and_propagate_topics import ALIASES


def clean_name(value: Any) -> str:
    value = re.sub(r"\*+$", "", str(value or "")).strip()
    value = re.sub(r"^(?:professor|prof\.?|doctor|dr\.?)\s+", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value)


def name_key(value: Any) -> str:
    value = unicodedata.normalize("NFKD", clean_name(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def title_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def pub_id(doi: Any, title: Any) -> str:
    key = f"doi:{str(doi).strip().lower()}" if str(doi or "").strip() else f"title:{title_key(title)}"
    return "pub_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def split_values(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def openalex_authorships(value: Any) -> list[dict]:
    if not str(value or "").strip():
        return []
    try:
        records = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return records if isinstance(records, list) else []


def institutional_author_evidence(value: Any) -> list[dict]:
    if not str(value or "").strip():
        return []
    try:
        records = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return records if isinstance(records, list) else []


def tokens(value: str) -> list[str]:
    return name_key(value).split()


def compatible(author: str, faculty: str) -> bool:
    """Conservative full-name or surname+initial comparison."""
    a, f = tokens(author), tokens(faculty)
    if not a or not f or a[-1] != f[-1]:
        return False
    if name_key(author) == name_key(faculty):
        return True
    # A shared initial is sufficient only when one source actually abbreviates the
    # first name. Two different spelled-out first names must not collapse.
    if a[0][0] != f[0][0]:
        return False
    if a[0] != f[0] and len(a[0]) > 1 and len(f[0]) > 1:
        if min(len(a[0]), len(f[0])) < 3 or not (a[0].startswith(f[0]) or f[0].startswith(a[0])):
            return False
    author_core, faculty_core = a[:-1], f[:-1]
    if len(author_core) == 1 or len(faculty_core) == 1:
        return True
    return all(x[0] == y[0] for x, y in zip(author_core, faculty_core))


def name_similarity(left: str, right: str) -> float:
    """Similarity tuned for a small roster where middle-name omission is common."""
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    if name_key(left) == name_key(right):
        return 1.0
    surname_ratio = SequenceMatcher(None, a[-1], b[-1]).ratio()
    if surname_ratio < 0.88 or a[0][0] != b[0][0]:
        return 0.0
    if compatible(left, right):
        return 0.97
    first_ratio = SequenceMatcher(None, a[0], b[0]).ratio()
    if a[-1] == b[-1] and a[0] == b[0]:
        # Adam Pah / Adam R. Pah, or one source omitting additional given names.
        return 0.985
    if a[-1] == b[-1] and (len(a[0]) == 1 or len(b[0]) == 1):
        return 0.96
    full_ratio = SequenceMatcher(None, name_key(left), name_key(right)).ratio()
    return round(0.45 * surname_ratio + 0.25 * first_ratio + 0.30 * full_ratio, 4)


def institution_ids(authorship: dict) -> set[str]:
    return {
        str(item.get("id") or item.get("ror") or "").strip()
        for item in authorship.get("institutions") or []
        if str(item.get("id") or item.get("ror") or "").strip()
    }


def author_key(authorship: dict) -> tuple:
    return (
        str(authorship.get("author_id") or ""),
        name_key(authorship.get("display_name") or authorship.get("raw_author_name")),
        tuple(sorted(institution_ids(authorship))),
    )


def lexical_candidates(authorship: dict, alias_sets: dict[str, set[str]]) -> dict[str, float]:
    name = clean_name(authorship.get("display_name") or authorship.get("raw_author_name"))
    return {
        faculty: max(name_similarity(name, alias) for alias in aliases)
        for faculty, aliases in alias_sets.items()
    }


def resolve_authorship(authorship: dict, alias_sets: dict[str, set[str]], profiles: dict[str, dict]) -> tuple[str | None, dict]:
    name = clean_name(authorship.get("display_name") or authorship.get("raw_author_name"))
    author_id = str(authorship.get("author_id") or "")
    institutions = institution_ids(authorship)
    lexical = lexical_candidates(authorship, alias_sets)
    candidates = []
    for faculty, score in lexical.items():
        id_match = bool(author_id and author_id in profiles[faculty]["author_ids"])
        shared_institutions = sorted(institutions & profiles[faculty]["institution_ids"])
        rule, confidence = "", 0.0
        if score >= 0.96 and id_match and shared_institutions:
            rule, confidence = "name+openalex_id+institution", 0.995
        elif score >= 0.96 and id_match:
            rule, confidence = "name+openalex_id", 0.99
        elif score >= 0.96 and shared_institutions:
            rule, confidence = "name+institution", 0.985
        elif score >= 0.96:
            rule, confidence = "extremely_similar_name", min(0.98, score)
        elif id_match and score >= 0.82:
            # IDs are strong evidence, but never override a materially conflicting name.
            rule, confidence = "openalex_id+compatible_name", 0.98
        elif shared_institutions and score >= 0.90:
            rule, confidence = "institution+extremely_similar_name", 0.97
        if rule:
            candidates.append((confidence, score, faculty, rule, id_match, shared_institutions))
    candidates.sort(reverse=True)
    if not candidates:
        return None, {"status": "unmatched", "openalex_name": name, "author_id": author_id}
    best = candidates[0]
    if len(candidates) > 1 and best[0] - candidates[1][0] < 0.015:
        return None, {
            "status": "ambiguous", "openalex_name": name, "author_id": author_id,
            "candidates": [item[2] for item in candidates[:3]],
        }
    confidence, lexical_score, faculty, rule, id_match, shared = best
    return faculty, {
        "status": "matched", "rule": rule, "openalex_name": name,
        "openalex_author_id": author_id or None, "orcid": authorship.get("orcid") or None,
        "lexical_similarity": lexical_score, "id_match": id_match,
        "shared_institution_ids": shared,
        "institutions": authorship.get("institutions") or [], "confidence": confidence,
    }


def merge_attribution_evidence(
    provisional: dict[str, dict], openalex_found: dict[str, dict], has_openalex_authorships: bool,
) -> tuple[dict[str, dict], list[str]]:
    """Merge local evidence, withholding owner-only links contradicted by author data."""
    found = dict(openalex_found)
    rejected = []
    for faculty, evidence in provisional.items():
        owner_only = evidence["basis"] == "digital_measures_resume_owner"
        if owner_only and has_openalex_authorships and faculty not in openalex_found:
            rejected.append(faculty)
            continue
        previous = found.get(faculty)
        if previous is None or evidence["confidence"] > previous["confidence"]:
            found[faculty] = evidence
    return found, rejected


def faculty_active_in_years(active_years: set[str], publication_years: set[str]) -> bool:
    """Bound roster matching to years when both sources provide temporal evidence."""
    return not active_years or not publication_years or bool(active_years & publication_years)


def apply_attribution_overrides(
    found: dict[str, dict], overrides: list[dict], publication_id: str, roster: set[str],
) -> dict[str, dict]:
    """Apply reviewed add/remove decisions to one publication's attribution set."""
    updated = dict(found)
    for override in overrides:
        if str(override.get("publication_id", "")) != publication_id:
            continue
        faculty = clean_name(override.get("faculty_name"))
        if faculty not in roster:
            raise ValueError(f"Attribution override references unknown faculty: {faculty}")
        action = str(override.get("action", "")).casefold()
        if action == "remove":
            updated.pop(faculty, None)
        elif action == "add":
            evidence = {
                "basis": "human_review_override", "action": "add", "faculty_name": faculty,
                "decision_id": override.get("decision_id", ""),
                "feedback_id": override.get("feedback_id", ""),
                "reason": override.get("reason", ""),
            }
            updated[faculty] = {
                "basis": "human_review_override", "confidence": 1.0,
                "evidence": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            }
        else:
            raise ValueError(f"Unsupported attribution override action: {action}")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=Path("results/publication_candidates.csv"))
    parser.add_argument("--articles", type=Path, default=Path("results/topic_model_specter2/labeled_article_topics.csv"))
    parser.add_argument("--resolution", type=Path, default=Path("results/publication_resolution/publication_resolution.csv"))
    parser.add_argument("--faculty-registry", type=Path, default=Path("results/institutional_faculty_registry.csv"))
    parser.add_argument("--overrides", type=Path, default=Path("data/faculty_attribution_overrides.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/faculty_attribution"))
    parser.add_argument("--topic-dir", type=Path, default=Path("results/topic_model_specter2"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.topic_dir.mkdir(parents=True, exist_ok=True)

    candidates = pd.read_csv(args.candidates, dtype={"record_id": str}).fillna("")
    articles = pd.read_csv(args.articles, dtype={"record_id": str, "source_record_ids": str}).fillna("")
    resolution = pd.read_csv(args.resolution, dtype={"record_id": str}).fillna("")
    registry_input = pd.read_csv(args.faculty_registry).fillna("")
    override_rows = (
        pd.read_csv(args.overrides, dtype=str).fillna("").to_dict(orient="records")
        if args.overrides.exists() else []
    )
    candidate_lookup = candidates.set_index("record_id", drop=False).to_dict(orient="index")
    resolution_lookup = resolution.set_index("record_id", drop=False).to_dict(orient="index")

    # The registry defines who is faculty, independently of publication headings.
    roster: set[str] = set(registry_input["faculty_name"].map(clean_name))
    roster_years = {
        clean_name(row["faculty_name"]): set(split_values(row.get("report_years", "")))
        for row in registry_input.to_dict(orient="records")
    }
    alias_sets: dict[str, set[str]] = defaultdict(set)
    for row in registry_input.to_dict(orient="records"):
        faculty = clean_name(row["faculty_name"])
        alias_sets[faculty].add(faculty)
        alias_sets[faculty].update(clean_name(value) for value in split_values(row.get("aliases", "")))
    for alias, faculty in ALIASES.items():
        if faculty in roster:
            alias_sets[faculty].add(clean_name(alias))
    declared_alias_sets = {faculty: set(aliases) for faculty, aliases in alias_sets.items()}

    # Pass 1: learn stable OpenAlex IDs and institutions only from unique,
    # extremely close lexical matches to the bounded faculty roster.
    profiles = {
        faculty: {"author_ids": set(), "orcids": set(), "institution_ids": set(),
                  "institution_names": set(), "observed_names": set()}
        for faculty in roster
    }
    observations: dict[tuple, dict] = {}
    for row in resolution.to_dict(orient="records"):
        source = candidate_lookup.get(str(row.get("record_id", "")), {})
        years = {str(source.get("report_year", "")).strip()} - {""}
        for authorship in openalex_authorships(row.get("openalex_authorships", "")):
            observation = observations.setdefault(
                author_key(authorship), {"authorship": authorship, "report_years": set()}
            )
            observation["report_years"].update(years)
    for observation in observations.values():
        authorship = observation["authorship"]
        eligible_aliases = {
            faculty: aliases for faculty, aliases in alias_sets.items()
            if faculty_active_in_years(roster_years.get(faculty, set()), observation["report_years"])
        }
        scores = lexical_candidates(authorship, eligible_aliases)
        ranked = sorted(((score, faculty) for faculty, score in scores.items() if score >= 0.96), reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.015):
            continue
        _, faculty = ranked[0]
        profile = profiles[faculty]
        name = clean_name(authorship.get("display_name") or authorship.get("raw_author_name"))
        if name:
            profile["observed_names"].add(name)
            alias_sets[faculty].add(name)
        if authorship.get("author_id"):
            profile["author_ids"].add(str(authorship["author_id"]))
        if authorship.get("orcid"):
            profile["orcids"].add(str(authorship["orcid"]))
        profile["institution_ids"].update(institution_ids(authorship))
        profile["institution_names"].update(
            str(item.get("display_name") or "") for item in authorship.get("institutions") or []
            if item.get("display_name")
        )

    attribution_rows, audit_rows = [], []
    for article in articles.to_dict(orient="records"):
        source_ids = split_values(article["source_record_ids"])
        source_rows = [candidate_lookup[x] for x in source_ids if x in candidate_lookup]
        resolved_rows = [resolution_lookup[x] for x in source_ids if x in resolution_lookup]
        resolved_rows.sort(key=lambda row: len(str(row.get("authors", ""))), reverse=True)
        article_authorships: dict[tuple, dict] = {}
        for row in resolved_rows:
            for authorship in openalex_authorships(row.get("openalex_authorships", "")):
                article_authorships[author_key(authorship)] = authorship
        publication_id = pub_id(article.get("doi"), article.get("canonical_title"))
        source_years = {str(row.get("report_year", "")).strip() for row in source_rows} - {""}
        article_alias_sets = {
            faculty: aliases for faculty, aliases in alias_sets.items()
            if faculty_active_in_years(roster_years.get(faculty, set()), source_years)
        }
        article_profiles = {faculty: profiles[faculty] for faculty in article_alias_sets}
        provisional: dict[str, dict] = {}
        for source in source_rows:
            for evidence in institutional_author_evidence(source.get("institutional_author_evidence", "")):
                faculty = clean_name(evidence.get("faculty_name"))
                if faculty not in roster:
                    continue
                candidate = {
                    "basis": evidence.get("basis") or "pre_resolution_citation",
                    "confidence": float(evidence.get("confidence") or 0),
                    "evidence": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                }
                previous = provisional.get(faculty)
                if previous is None or candidate["confidence"] > previous["confidence"]:
                    provisional[faculty] = candidate

        openalex_found: dict[str, dict] = {}

        for authorship in article_authorships.values():
            faculty, evidence = resolve_authorship(authorship, article_alias_sets, article_profiles)
            audit_rows.append({
                "record_id": article["record_id"], "publication_id": publication_id,
                "canonical_title": article["canonical_title"], "faculty_name": faculty or "",
                "status": evidence["status"], "openalex_name": evidence.get("openalex_name", ""),
                "openalex_author_id": evidence.get("openalex_author_id") or evidence.get("author_id", ""),
                "rule": evidence.get("rule", ""), "lexical_similarity": evidence.get("lexical_similarity", ""),
                "shared_institution_ids": ";".join(evidence.get("shared_institution_ids", [])),
                "candidate_faculty": ";".join(evidence.get("candidates", [])),
            })
            if faculty:
                previous = openalex_found.get(faculty)
                if previous is None or evidence["confidence"] > previous["confidence"]:
                    openalex_found[faculty] = {
                        "basis": "openalex_author_disambiguation",
                        "confidence": evidence["confidence"],
                        "evidence": json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                    }

        found, rejected_owners = merge_attribution_evidence(
            provisional, openalex_found, bool(article_authorships)
        )
        for faculty in rejected_owners:
            audit_rows.append({
                "record_id": article["record_id"], "publication_id": publication_id,
                "canonical_title": article["canonical_title"], "faculty_name": faculty,
                "status": "provisional_owner_not_confirmed", "openalex_name": "",
                "openalex_author_id": "", "rule": provisional[faculty]["basis"],
                "lexical_similarity": "", "shared_institution_ids": "",
                "candidate_faculty": faculty,
            })

        found = apply_attribution_overrides(found, override_rows, publication_id, roster)

        years = sorted({int(float(row["report_year"])) for row in source_rows if str(row.get("report_year", "")).strip()})
        for faculty, evidence in found.items():
            attribution_rows.append({
                "faculty_name": faculty, "record_id": article["record_id"],
                "publication_id": publication_id, "source_record_ids": ";".join(source_ids),
                "report_years": ";".join(map(str, years)), "canonical_title": article["canonical_title"],
                "doi": article.get("doi", ""), "topic_id": int(article["topic_id"]),
                "topic_label": article["topic_label"], "topic_description": article["topic_description"],
                "topic_probability": float(article["topic_probability"]),
                "attribution_basis": evidence["basis"], "attribution_confidence": evidence["confidence"],
                "attribution_evidence": evidence["evidence"],
            })

    columns = ["faculty_name", "record_id", "publication_id", "source_record_ids", "report_years",
               "canonical_title", "doi", "topic_id", "topic_label", "topic_description",
               "topic_probability", "attribution_basis", "attribution_confidence", "attribution_evidence"]
    attributed = pd.DataFrame(attribution_rows, columns=columns).drop_duplicates(["faculty_name", "record_id"])
    attributed = attributed.sort_values(["faculty_name", "topic_id", "canonical_title"])
    attributed.to_csv(args.output_dir / "article_faculty_attributions.csv", index=False)
    attributed.to_csv(args.topic_dir / "faculty_topic_publications.csv", index=False)
    registry_ids = {
        clean_name(row["faculty_name"]): row.get("faculty_id", "")
        for row in registry_input.to_dict(orient="records")
    }
    registry = pd.DataFrame([
        {"faculty_id": registry_ids.get(name, ""), "faculty_name": name,
         "aliases": ";".join(sorted(declared_alias_sets[name], key=str.casefold))}
        for name in sorted(roster, key=str.casefold)
    ])
    registry.to_csv(args.output_dir / "faculty_registry.csv", index=False)
    pd.DataFrame(audit_rows).to_csv(args.output_dir / "author_disambiguation_audit.csv", index=False)
    profile_rows = []
    for faculty in sorted(roster, key=str.casefold):
        profile = profiles[faculty]
        profile_rows.append({
            "faculty_name": faculty,
            "openalex_author_ids": ";".join(sorted(profile["author_ids"])),
            "orcids": ";".join(sorted(profile["orcids"])),
            "observed_names": ";".join(sorted(profile["observed_names"], key=str.casefold)),
            "institution_ids": ";".join(sorted(profile["institution_ids"])),
            "institution_names": ";".join(sorted(profile["institution_names"], key=str.casefold)),
        })
    pd.DataFrame(profile_rows).to_csv(args.output_dir / "faculty_author_identity_profiles.csv", index=False)

    clustered = attributed[attributed["topic_id"] >= 0].copy()
    totals = attributed.groupby("faculty_name")["record_id"].nunique().rename("modeled_publications")
    clustered_totals = clustered.groupby("faculty_name")["record_id"].nunique().rename("clustered_publications")
    summary_rows = []
    for (faculty, topic_id), group in clustered.groupby(["faculty_name", "topic_id"], sort=True):
        titles = group.sort_values("topic_probability", ascending=False)["canonical_title"].drop_duplicates().head(3)
        summary_rows.append({
            "faculty_name": faculty, "topic_id": int(topic_id),
            "topic_label": group["topic_label"].iloc[0],
            "topic_description": group["topic_description"].iloc[0],
            "publication_count": group["record_id"].nunique(),
            "mean_topic_probability": round(float(group["topic_probability"].mean()), 4),
            "representative_titles": " | ".join(titles),
        })
    summary_columns = ["faculty_name", "topic_id", "topic_label", "topic_description", "publication_count",
                       "mean_topic_probability", "representative_titles"]
    summary = pd.DataFrame(summary_rows, columns=summary_columns)
    if not summary.empty:
        summary = summary.merge(totals, on="faculty_name").merge(clustered_totals, on="faculty_name")
        summary["share_of_faculty_clustered_publications"] = (summary["publication_count"] / summary["clustered_publications"]).round(4)
        summary = summary.sort_values(["faculty_name", "publication_count"], ascending=[True, False])
    summary.to_csv(args.topic_dir / "faculty_topic_summary.csv", index=False)
    matrix = clustered.pivot_table(index="faculty_name", columns="topic_label", values="record_id", aggfunc="nunique", fill_value=0).astype(int).reset_index()
    matrix.to_csv(args.topic_dir / "faculty_topic_matrix.csv", index=False)

    qa = {
        "modeled_publications": int(len(articles)), "attributed_publications": int(attributed["record_id"].nunique()),
        "faculty": int(attributed["faculty_name"].nunique()), "attribution_links": int(len(attributed)),
        "basis_counts": dict(Counter(attributed["attribution_basis"])),
        "attribution_policy": "pre_resolution_citation_then_openalex_enrichment",
        "identity_profiles_with_openalex_ids": sum(bool(profile["author_ids"]) for profile in profiles.values()),
        "identity_profiles_with_institutions": sum(bool(profile["institution_ids"]) for profile in profiles.values()),
        "disambiguation_rule_counts": dict(Counter(
            json.loads(value).get("rule") or json.loads(value).get("basis") or "unknown"
            for value in attributed["attribution_evidence"]
        )),
        "ambiguous_openalex_authorships": sum(row["status"] == "ambiguous" for row in audit_rows),
        "provisional_owners_not_confirmed": sum(
            row["status"] == "provisional_owner_not_confirmed" for row in audit_rows
        ),
    }
    (args.output_dir / "qa.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    print(json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
