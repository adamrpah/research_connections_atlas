#!/usr/bin/env python3
"""Build and apply a canonical institutional faculty-name registry.

Digital Measures resume owners provide canonical current names; annual-report owners
extend the roster historically. Candidate citations are annotated before external
metadata resolution so locally attributable works remain attributable even when
Crossref or OpenAlex cannot identify the work.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
NON_PERSON_NAME_KEYS = {
    "refereed journal articles", "journal articles", "book chapters", "books",
    "graduate student", "former graduate student", "publications", "presentations",
    "intellectual contributions", "scholarly contributions",
}


def clean_name(value: object) -> str:
    value = re.sub(r"\*+$", "", str(value or "")).strip()
    value = re.sub(r"^(?:professor|prof\.?|doctor|dr\.?)\s+", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" ,;:|")


def name_key(value: object) -> str:
    ascii_value = unicodedata.normalize("NFKD", clean_name(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def faculty_id(name: str) -> str:
    return "fac_" + hashlib.sha256(name_key(name).encode()).hexdigest()[:16]


def build_registry(records: Iterable[dict]) -> list[dict]:
    """Create deterministic canonical roster rows from Digital Measures owners."""
    grouped: dict[str, dict] = defaultdict(lambda: {
        "names": Counter(), "digital_measure_names": Counter(), "years": set(),
        "reports": set(), "source_types": set(), "source_occurrences": 0,
    })
    for record in records:
        display = clean_name(record.get("faculty_heading"))
        key = name_key(display)
        parts = key.split()
        if not key or key in NON_PERSON_NAME_KEYS or not 2 <= len(parts) <= 7:
            continue
        group = grouped[key]
        group["names"][display] += 1
        source_type = str(record.get("roster_source", "digital_measures")).strip()
        group["source_types"].add(source_type)
        if source_type == "digital_measures":
            group["digital_measure_names"][display] += 1
        if str(record.get("report_year", "")).strip():
            group["years"].add(str(record["report_year"]).strip())
        if str(record.get("report_file", "")).strip():
            group["reports"].add(str(record["report_file"]).strip())
        group["source_occurrences"] += 1

    rows = []
    for key, group in grouped.items():
        authority = group["digital_measure_names"] or group["names"]
        ranked_names = sorted(authority, key=lambda name: (-authority[name], name.casefold()))
        canonical = ranked_names[0]
        rows.append({
            "faculty_id": faculty_id(canonical),
            "faculty_name": canonical,
            "name_key": key,
            "aliases": ";".join(sorted(group["names"], key=str.casefold)),
            "report_years": ";".join(sorted(group["years"])),
            "source_reports": ";".join(sorted(group["reports"], key=str.casefold)),
            "source_types": ";".join(sorted(group["source_types"])),
            "canonical_authority": (
                "digital_measures" if group["digital_measure_names"] else "annual_report_heading"
            ),
            "source_occurrences": group["source_occurrences"],
        })
    return sorted(rows, key=lambda row: row["faculty_name"].casefold())


REGISTRY_FIELDS = [
    "faculty_id", "faculty_name", "name_key", "aliases", "report_years",
    "source_reports", "source_types", "canonical_authority", "source_occurrences",
]


def write_registry(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REGISTRY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_registry(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def apply_registry_overrides(registry: list[dict], overrides: Iterable[dict]) -> list[dict]:
    """Apply reviewed canonical-name changes without changing stable faculty IDs."""
    by_id = {row["faculty_id"]: dict(row) for row in registry}
    excluded = set()
    for override in overrides:
        faculty_id_value = str(override.get("faculty_id", "")).strip()
        action = str(override.get("action", "")).strip().casefold()
        value = clean_name(override.get("value"))
        if faculty_id_value not in by_id:
            raise ValueError(f"Faculty name override references unknown ID: {faculty_id_value}")
        row = by_id[faculty_id_value]
        aliases = aliases_for(row)
        if action == "rename":
            if not value:
                raise ValueError(f"Rename override has no value: {faculty_id_value}")
            aliases.add(row["faculty_name"])
            aliases.add(value)
            row["faculty_name"] = value
            row["name_key"] = name_key(value)
        elif action == "add_alias":
            if not value:
                raise ValueError(f"Alias override has no value: {faculty_id_value}")
            aliases.add(value)
        elif action == "exclude":
            excluded.add(faculty_id_value)
        else:
            raise ValueError(f"Unsupported faculty name override action: {action}")
        row["aliases"] = ";".join(sorted(aliases, key=str.casefold))
    updated = sorted(
        (row for faculty_id_value, row in by_id.items() if faculty_id_value not in excluded),
        key=lambda row: row["faculty_name"].casefold(),
    )
    keys = [name_key(row["faculty_name"]) for row in updated]
    if len(keys) != len(set(keys)):
        raise ValueError("Faculty name overrides create duplicate canonical names")
    return updated


def aliases_for(row: dict) -> set[str]:
    return {
        clean_name(value) for value in str(row.get("aliases", "")).split(";")
        if clean_name(value)
    } | {clean_name(row.get("faculty_name"))}


def _citation_author_zone(citation: str) -> str:
    """Return the portion most likely to contain a citation's author list."""
    match = YEAR_RE.search(citation)
    return citation[:match.start()] if match and match.start() >= 2 else citation


class FacultyMatcher:
    """Reusable token matcher compiled once for a canonical faculty registry."""

    def __init__(self, registry: list[dict]):
        self.by_key: dict[str, dict] = {}
        self.alias_rows: list[tuple[dict, str, list[str]]] = []
        self.signatures: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in registry:
            for alias in aliases_for(row):
                self.by_key[name_key(alias)] = row
                parts = name_key(alias).split()
                if len(parts) < 2:
                    continue
                self.alias_rows.append((row, alias, parts))
                self.signatures[(parts[-1], parts[0][0])].add(row["faculty_id"])

    @staticmethod
    def _contains(zone: str, value: str) -> bool:
        return f" {value} " in f" {zone} "

    def match(self, candidate: dict) -> list[dict]:
        found: dict[str, dict] = {}
        owner = self.by_key.get(name_key(candidate.get("faculty_heading")))
        if owner:
            found[owner["faculty_id"]] = {
                "faculty_id": owner["faculty_id"], "faculty_name": owner["faculty_name"],
                "basis": "digital_measures_resume_owner", "confidence": 0.9,
                "matched_text": clean_name(candidate.get("faculty_heading")),
            }

        candidate_year = str(candidate.get("report_year", "")).strip()
        zone = name_key(_citation_author_zone(str(candidate.get("raw_citation", ""))))
        for row, alias, parts in self.alias_rows:
            active_years = {value for value in str(row.get("report_years", "")).split(";") if value}
            if candidate_year and active_years and candidate_year not in active_years:
                continue
            full = " ".join(parts)
            reverse = " ".join([parts[-1], *parts[:-1]])
            basis, confidence = "citation_full_name", 0.99
            if not (self._contains(zone, full) or self._contains(zone, reverse)):
                surname, initial = parts[-1], parts[0][0]
                signature = (surname, initial)
                if len(self.signatures[signature]) != 1:
                    continue
                abbreviated = {
                    f"{initial} {surname}", f"{surname} {initial}",
                    f"{parts[0]} {surname}", f"{surname} {parts[0]}",
                }
                if len(parts) > 2:
                    abbreviated.update({
                        f"{initial} {parts[1][0]} {surname}",
                        f"{surname} {initial} {parts[1][0]}",
                    })
                if not any(self._contains(zone, value) for value in abbreviated):
                    continue
                basis, confidence = "citation_unique_surname_initial", 0.96
            previous = found.get(row["faculty_id"])
            evidence = {
                "faculty_id": row["faculty_id"], "faculty_name": row["faculty_name"],
                "basis": basis, "confidence": confidence, "matched_text": alias,
            }
            if previous is None or evidence["confidence"] > previous["confidence"]:
                found[row["faculty_id"]] = evidence
        return sorted(found.values(), key=lambda item: item["faculty_name"].casefold())


def match_candidate_authors(candidate: dict, registry: list[dict]) -> list[dict]:
    """Find institutional authors using owner provenance and citation-name forms."""
    return FacultyMatcher(registry).match(candidate)


def annotate_candidate(candidate: dict, registry: list[dict] | FacultyMatcher) -> dict:
    matcher = registry if isinstance(registry, FacultyMatcher) else FacultyMatcher(registry)
    matches = matcher.match(candidate)
    annotated = dict(candidate)
    annotated["institutional_faculty_ids"] = ";".join(item["faculty_id"] for item in matches)
    annotated["institutional_faculty_names"] = ";".join(item["faculty_name"] for item in matches)
    annotated["institutional_author_evidence"] = json.dumps(
        matches, ensure_ascii=False, separators=(",", ":")
    ) if matches else ""
    return annotated
