import unittest

from run_population_pipeline import merge_candidates


class PopulationPipelineTests(unittest.TestCase):
    def test_append_preserves_existing_and_adds_only_unseen_records(self):
        existing = [{"record_id": "old", "title": "Original"}]
        extracted = [
            {"record_id": "old", "title": "Re-extracted"},
            {"record_id": "new", "title": "New"},
        ]
        rows, added = merge_candidates(existing, extracted, "append")
        self.assertEqual(added, 1)
        self.assertEqual([row["title"] for row in rows], ["Original", "New"])

    def test_rebuild_uses_only_fresh_extraction(self):
        existing = [{"record_id": "obsolete", "title": "Obsolete"}]
        extracted = [{"record_id": "new", "title": "New"}]
        rows, added = merge_candidates(existing, extracted, "rebuild")
        self.assertEqual(added, 1)
        self.assertEqual(rows, extracted)


if __name__ == "__main__":
    unittest.main()
