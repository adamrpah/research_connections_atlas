import unittest

import pandas as pd

from build_faculty_impact_summary import build_summary, h_index


class FacultyImpactSummaryTests(unittest.TestCase):
    def test_h_index(self):
        self.assertEqual(h_index([10, 8, 5, 4, 3]), 4)
        self.assertEqual(h_index([]), 0)

    def test_aggregates_only_final_attributed_publications(self):
        attributions = pd.DataFrame([
            {"faculty_name": "Jane Scholar", "publication_id": "pub_1"},
            {"faculty_name": "Jane Scholar", "publication_id": "pub_2"},
            {"faculty_name": "Jane Scholar", "publication_id": "pub_2"},
        ])
        impact = pd.DataFrame([
            {"publication_id": "pub_1", "impact_observed_at": "2026-08-06T00:00:00Z",
             "cited_by_count": 12, "fwci": 2.0, "citation_percentile": 0.95,
             "is_top_10_percent": True, "is_top_1_percent": False,
             "citations_last_2_years": 5, "citations_last_5_years": 10},
            {"publication_id": "pub_2", "impact_observed_at": "2026-08-06T00:00:00Z",
             "cited_by_count": 0, "fwci": 0.2, "citation_percentile": 0.2,
             "is_top_10_percent": False, "is_top_1_percent": False,
             "citations_last_2_years": 0, "citations_last_5_years": 0},
            {"publication_id": "pub_not_attributed", "cited_by_count": 1000},
        ])
        registry = pd.DataFrame([{"faculty_id": "fac_jane", "faculty_name": "Jane Scholar"}])
        row = build_summary(attributions, impact, registry).iloc[0]
        self.assertEqual(row["attributed_publication_count"], 2)
        self.assertEqual(row["total_citations"], 12)
        self.assertEqual(row["median_citations"], 6.0)
        self.assertEqual(row["top_10_percent_share"], 0.5)
        self.assertEqual(row["corpus_h_index"], 1)
        self.assertEqual(row["corpus_i10_index"], 1)


if __name__ == "__main__":
    unittest.main()
