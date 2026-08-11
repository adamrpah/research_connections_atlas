import json
import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from refresh_openalex_impact import extract_impact, publication_id, read_csv, refresh


class OpenAlexImpactTests(unittest.TestCase):
    def test_extracts_openalex_and_calculated_work_measures(self):
        work = {
            "id": "https://openalex.org/W123", "publication_year": 2020,
            "publication_date": "2020-01-01", "updated_date": "2026-07-01T00:00:00Z",
            "cited_by_count": 20, "counts_by_year": [
                {"year": 2022, "cited_by_count": 2},
                {"year": 2025, "cited_by_count": 6},
                {"year": 2026, "cited_by_count": 4},
            ],
            "fwci": 1.8,
            "citation_normalized_percentile": {
                "value": 0.94, "is_in_top_10_percent": True,
                "is_in_top_1_percent": False,
            },
            "cited_by_percentile_year": {"min": 90, "max": 95},
            "referenced_works_count": 31,
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "is_retracted": False,
        }
        source = {"doi": "10.1/example", "canonical_title": "An Example", "publication_year": 2020}
        row = extract_impact(work, source, datetime(2026, 8, 6, tzinfo=timezone.utc))
        self.assertEqual(row["publication_id"], publication_id("10.1/example", "An Example"))
        self.assertEqual(row["citations_last_2_years"], 10)
        self.assertEqual(row["citations_last_5_years"], 12)
        self.assertEqual(row["citation_active_years"], 3)
        self.assertEqual(row["years_since_earliest_reported_citation"], 4)
        self.assertEqual(row["recent_citation_share"], 0.5)
        self.assertTrue(row["is_top_10_percent"])
        self.assertEqual(json.loads(row["citations_by_year"])[0]["year"], 2022)

    def test_uncited_work_has_zero_rate_and_no_first_citation(self):
        row = extract_impact(
            {"id": "https://openalex.org/W1", "publication_year": 2026,
             "cited_by_count": 0, "counts_by_year": []},
            {"canonical_title": "New Work"}, datetime(2026, 8, 6, tzinfo=timezone.utc),
        )
        self.assertTrue(row["is_uncited"])
        self.assertEqual(row["citations_per_year"], 0.0)
        self.assertEqual(row["years_since_earliest_reported_citation"], "")

    def test_refresh_writes_current_and_dated_publication_snapshots_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolution = root / "resolution.csv"
            with resolution.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "record_id", "match_status", "openalex_work_id", "doi",
                    "canonical_title", "publication_year",
                ])
                writer.writeheader()
                writer.writerows([
                    {"record_id": "one", "match_status": "matched",
                     "openalex_work_id": "https://openalex.org/W123", "doi": "10.1/example",
                     "canonical_title": "Example", "publication_year": 2020},
                    {"record_id": "duplicate", "match_status": "matched",
                     "openalex_work_id": "https://openalex.org/W123", "doi": "10.1/example",
                     "canonical_title": "Example", "publication_year": 2020},
                ])
            response = {"id": "https://openalex.org/W123", "publication_year": 2020,
                        "cited_by_count": 3, "counts_by_year": []}
            with patch("refresh_openalex_impact.request_json", return_value=response):
                refresh(resolution, root / "impact", "key",
                        datetime(2026, 8, 6, tzinfo=timezone.utc), delay=0)
                response["cited_by_count"] = 4
                refresh(resolution, root / "impact", "key",
                        datetime(2026, 8, 7, tzinfo=timezone.utc), delay=0)

            current = read_csv(root / "impact/current_work_impact.csv")
            snapshots = read_csv(root / "impact/work_impact_snapshots.csv")
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["cited_by_count"], "4")
            self.assertEqual(len(snapshots), 2)
            self.assertFalse((root / "impact/citation_edges.csv").exists())


if __name__ == "__main__":
    unittest.main()
