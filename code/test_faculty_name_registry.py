import json
import unittest

from faculty_name_registry import (
    annotate_candidate, apply_faculty_identifiers, apply_registry_overrides, build_registry,
    match_candidate_authors, normalize_orcid,
)


class FacultyNameRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry([
            {"faculty_heading": "Jane Q. Scholar", "report_year": 2023,
             "report_file": "dm-2023.docx", "roster_source": "digital_measures"},
            {"faculty_heading": "Jane Q. Scholar", "report_year": 2024,
             "report_file": "dm-2024.docx", "roster_source": "digital_measures"},
            {"faculty_heading": "John R. Writer", "report_year": 2024,
             "report_file": "dm-2024.docx", "roster_source": "digital_measures"},
        ])

    def test_builds_deterministic_canonical_registry(self):
        self.assertEqual([row["faculty_name"] for row in self.registry],
                         ["Jane Q. Scholar", "John R. Writer"])
        self.assertTrue(all(row["faculty_id"].startswith("fac_") for row in self.registry))
        self.assertEqual(self.registry[0]["report_years"], "2023;2024")
        self.assertEqual(self.registry[0]["source_occurrences"], 2)
        self.assertEqual(self.registry[0]["canonical_authority"], "digital_measures")

    def test_digital_measures_name_has_priority_over_historical_display_form(self):
        registry = build_registry([
            {"faculty_heading": "JANE Q SCHOLAR", "roster_source": "annual_report_heading"},
            {"faculty_heading": "Jane Q Scholar", "roster_source": "digital_measures"},
        ])
        self.assertEqual(registry[0]["faculty_name"], "Jane Q Scholar")

    def test_reviewed_name_override_preserves_id_and_adds_old_name_as_alias(self):
        faculty_id = self.registry[0]["faculty_id"]
        updated = apply_registry_overrides(self.registry, [{
            "faculty_id": faculty_id, "action": "rename", "value": "Jane Quinn Scholar",
        }])
        self.assertEqual(updated[0]["faculty_id"], faculty_id)
        self.assertEqual(updated[0]["faculty_name"], "Jane Quinn Scholar")
        self.assertIn("Jane Q. Scholar", updated[0]["aliases"])

    def test_curated_orcid_is_validated_and_attached_by_stable_id(self):
        updated = apply_faculty_identifiers(self.registry, [{
            "faculty_id": self.registry[0]["faculty_id"],
            "faculty_name": "Jane Q. Scholar",
            "orcid": "https://orcid.org/0000-0002-1825-0097",
            "source": "faculty_provided", "verified_at": "2026-08-06",
        }])
        self.assertEqual(updated[0]["orcid"], "0000-0002-1825-0097")
        self.assertEqual(updated[0]["orcid_source"], "faculty_provided")
        with self.assertRaisesRegex(ValueError, "checksum"):
            normalize_orcid("0000-0002-1825-0098")

    def test_rejects_duplicate_orcid_assignments(self):
        with self.assertRaisesRegex(ValueError, "multiple faculty IDs"):
            apply_faculty_identifiers(self.registry, [
                {"faculty_id": row["faculty_id"], "orcid": "0000-0002-1825-0097"}
                for row in self.registry
            ])

    def test_matches_owner_and_peer_coauthor_before_resolution(self):
        candidate = {
            "faculty_heading": "Jane Q. Scholar",
            "report_year": 2024,
            "raw_citation": "Scholar, J. Q.; Writer, J. R. (2024). Shared research. Example Journal.",
        }
        matches = match_candidate_authors(candidate, self.registry)
        self.assertEqual({row["faculty_name"] for row in matches},
                         {"Jane Q. Scholar", "John R. Writer"})
        self.assertEqual({row["basis"] for row in matches},
                         {"citation_unique_surname_initial"})

        annotated = annotate_candidate(candidate, self.registry)
        self.assertEqual(annotated["institutional_faculty_names"],
                         "Jane Q. Scholar;John R. Writer")
        self.assertEqual(len(json.loads(annotated["institutional_author_evidence"])), 2)

    def test_peer_matching_is_bounded_to_roster_year(self):
        matches = match_candidate_authors({
            "faculty_heading": "", "report_year": 1997,
            "raw_citation": "Writer, J. R. (1997). Earlier research. Example Journal.",
        }, self.registry)
        self.assertEqual(matches, [])

    def test_does_not_guess_ambiguous_surname_and_initial(self):
        registry = build_registry([
            {"faculty_heading": "Jane Q. Smith"},
            {"faculty_heading": "John R. Smith"},
        ])
        matches = match_candidate_authors(
            {"faculty_heading": "", "raw_citation": "Smith, J. (2024). A title."},
            registry,
        )
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
