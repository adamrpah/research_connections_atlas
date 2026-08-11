import tempfile
import unittest
import zipfile
from pathlib import Path

from extract_digitalmeasure_publications import (
    citation_category, extract_faculty_owners, extract_report, is_ongoing_work,
    report_paths, resolution_candidates,
)


DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="ReportHeader"/></w:pPr><w:r><w:t>Jane Q. Scholar</w:t></w:r></w:p>
    <w:p><w:r><w:t>Publications</w:t></w:r></w:p>
    <w:p><w:r><w:t>Refereed Journal Articles</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholar, J. Q. (2023). A useful article title. Journal of Examples, 4(2), 1-9.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholar, J. Q. (2023). An unfinished article. On-Going.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Book Chapters</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholar, J. Q. (2023). A useful chapter. In The Example Handbook. Sample Press.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Presentations</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholar, J. Q. (2023). “A useful presentation.” Annual Example Conference.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Teaching</w:t></w:r></w:p>
    <w:p><w:r><w:t>2023. This is a course, not a publication.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="ReportHeader"/></w:pPr><w:r><w:t>John R. Writer</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholarly Contributions</w:t></w:r></w:p>
    <w:p><w:r><w:t>Books</w:t></w:r></w:p>
    <w:p><w:r><w:t>Writer, J. R. 2023. “The Example Book.” Sample Press.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Professional Development-related Service</w:t></w:r></w:p>
    <w:p><w:r><w:t>Reviewer, Example Journal. (2023 - Present).</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="ReportHeader"/></w:pPr><w:r><w:t>No Work Faculty</w:t></w:r></w:p>
    <w:p><w:r><w:t>Teaching</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>"""


class DigitalMeasureExtractorTests(unittest.TestCase):
    def test_report_discovery_ignores_office_lock_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Digital Measures 2025.docx").touch()
            (root / "~$gital Measures 2025.docx").touch()
            self.assertEqual(
                [path.name for path in report_paths(root)],
                ["Digital Measures 2025.docx"],
            )

    def test_recognizes_ongoing_label_variants(self):
        for value in (
            "On-Going", "ongoing", "ON GOING", "Submitted", "Working Paper",
            "Reviewed - Not Accepted",
        ):
            with self.subTest(value=value):
                self.assertTrue(is_ongoing_work(f"Example work ({value})"))
        self.assertFalse(is_ongoing_work("Example work (Published)"))

    def test_refines_unfinished_other_works_as_articles(self):
        self.assertEqual(citation_category("other", "Example title. Submitted"), "article")
        self.assertEqual(citation_category("other", "Example title. Working Paper"), "article")
        self.assertEqual(citation_category("other", "Example report. Published"), "other")

    def test_extracts_publications_for_each_resume_and_stops_at_next_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Digital Measures 2023.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT)
            rows, summary = extract_report(path)
            owners = extract_faculty_owners(path)
        self.assertEqual(summary["year"], 2023)
        self.assertEqual(summary["people"], 2)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["faculty_heading"], "Jane Q. Scholar")
        self.assertEqual(
            rows[0]["title"],
            "Scholar, J. Q. (2023). A useful article title. Journal of Examples, 4(2), 1-9.",
        )
        self.assertEqual(rows[0]["category"], "article")
        self.assertFalse(rows[0]["is_ongoing"])
        self.assertEqual(rows[1]["category"], "article")
        self.assertTrue(rows[1]["is_ongoing"])
        self.assertEqual(rows[2]["category"], "book_chapter")
        self.assertEqual(rows[3]["category"], "presentation")
        self.assertEqual(rows[4]["faculty_heading"], "John R. Writer")
        self.assertEqual(rows[4]["title"], "Writer, J. R. 2023. “The Example Book.” Sample Press.")
        self.assertEqual(rows[4]["category"], "book")
        self.assertFalse(any("course" in row["raw_citation"].lower() for row in rows))
        self.assertFalse(any("reviewer" in row["raw_citation"].lower() for row in rows))
        self.assertEqual([owner["faculty_heading"] for owner in owners],
                         ["Jane Q. Scholar", "John R. Writer", "No Work Faculty"])
        forwarded = resolution_candidates(rows)
        self.assertEqual(
            [row["category"] for row in forwarded],
            ["article", "book_chapter", "book"],
        )

    def test_ongoing_variants_are_not_resolution_candidates(self):
        rows = [
            {"record_id": "hyphen", "category": "article", "is_ongoing": True},
            {"record_id": "space", "category": "book", "is_ongoing": "yes"},
            {"record_id": "ready", "category": "book_chapter", "is_ongoing": False},
            {"record_id": "presentation", "category": "presentation", "is_ongoing": False},
        ]
        self.assertEqual(
            [row["record_id"] for row in resolution_candidates(rows)],
            ["ready"],
        )


if __name__ == "__main__":
    unittest.main()
