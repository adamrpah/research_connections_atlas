import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from apply_publication_metadata_curation import apply_curation


HEADERS = ["work_key", "source_record_ids", "title", "publication_year", "doi", "authors", "landing_url", "abstract", "contributor", "notes"]


class PublicationMetadataCurationTests(unittest.TestCase):
    def test_only_changed_cells_are_applied_to_all_source_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook_path = root / "curation.xlsx"
            resolution_path = root / "resolution.csv"
            workbook = Workbook()
            visible = workbook.active
            visible.title = "Publication Curation"
            baseline = workbook.create_sheet("Baseline - Do Not Edit")
            original = ["doi:10.1/example", "a;b", "Old title", "2020", "10.1/example", "A; B", "https://old", "", "", ""]
            edited = original.copy()
            edited[2] = "Correct title"
            edited[7] = "A newly supplied abstract."
            for sheet, row in ((visible, edited), (baseline, original)):
                sheet.append(HEADERS)
                sheet.append(row)
            baseline.sheet_state = "hidden"
            workbook.save(workbook_path)

            fields = ["record_id", "canonical_title", "publication_year", "doi", "authors", "landing_url", "abstract", "abstract_source", "local_abstract", "match_source"]
            with resolution_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for record_id in ("a", "b", "untouched"):
                    writer.writerow({"record_id": record_id, "canonical_title": "Old title", "match_source": "crossref"})

            summary = apply_curation(workbook_path, resolution_path)
            with resolution_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(summary["curated_works"], 1)
            self.assertEqual(summary["updated_resolution_records"], 2)
            self.assertEqual(rows[0]["canonical_title"], "Correct title")
            self.assertEqual(rows[1]["abstract"], "A newly supplied abstract.")
            self.assertEqual(rows[1]["abstract_source"], "human_curated")
            self.assertEqual(rows[2]["canonical_title"], "Old title")


if __name__ == "__main__":
    unittest.main()
