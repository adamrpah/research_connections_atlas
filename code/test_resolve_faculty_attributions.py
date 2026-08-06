import unittest

from resolve_faculty_attributions import (
    apply_attribution_overrides, faculty_active_in_years, merge_attribution_evidence,
)


class AttributionEvidenceTests(unittest.TestCase):
    def test_human_overrides_remove_and_add_attributions(self):
        found = {"Jane Scholar": {"basis": "openalex", "confidence": 0.99}}
        overrides = [
            {"publication_id": "pub_1", "action": "remove", "faculty_name": "Jane Scholar"},
            {"publication_id": "pub_1", "action": "add", "faculty_name": "John Writer",
             "decision_id": "review_1", "reason": "Reviewer correction"},
        ]
        updated = apply_attribution_overrides(
            found, overrides, "pub_1", {"Jane Scholar", "John Writer"}
        )
        self.assertEqual(set(updated), {"John Writer"})
        self.assertEqual(updated["John Writer"]["basis"], "human_review_override")

    def test_roster_matching_respects_report_years(self):
        self.assertTrue(faculty_active_in_years({"2023", "2024"}, {"2024"}))
        self.assertFalse(faculty_active_in_years({"2023", "2024"}, {"1997"}))
        self.assertTrue(faculty_active_in_years(set(), {"1997"}))

    def test_openalex_enriches_citation_evidence_and_rejects_unconfirmed_owner(self):
        provisional = {
            "Jane Scholar": {"basis": "digital_measures_resume_owner", "confidence": 0.9},
            "John Writer": {"basis": "citation_unique_surname_initial", "confidence": 0.96},
        }
        external = {
            "John Writer": {"basis": "openalex_author_disambiguation", "confidence": 0.99},
        }
        merged, rejected = merge_attribution_evidence(provisional, external, True)
        self.assertEqual(set(merged), {"John Writer"})
        self.assertEqual(merged["John Writer"]["basis"], "openalex_author_disambiguation")
        self.assertEqual(rejected, ["Jane Scholar"])

    def test_owner_is_retained_when_external_authorships_are_unavailable(self):
        provisional = {
            "Jane Scholar": {"basis": "digital_measures_resume_owner", "confidence": 0.9},
        }
        merged, rejected = merge_attribution_evidence(provisional, {}, False)
        self.assertEqual(set(merged), {"Jane Scholar"})
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
