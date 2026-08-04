import tempfile
import unittest
import zipfile
from pathlib import Path

from extract_digitalmeasure_publications import extract_report


DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="ReportHeader"/></w:pPr><w:r><w:t>Jane Q. Scholar</w:t></w:r></w:p>
    <w:p><w:r><w:t>Publications</w:t></w:r></w:p>
    <w:p><w:r><w:t>Refereed Journal Articles</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholar, J. Q. (2023). A useful article title. Journal of Examples, 4(2), 1-9.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Teaching</w:t></w:r></w:p>
    <w:p><w:r><w:t>2023. This is a course, not a publication.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="ReportHeader"/></w:pPr><w:r><w:t>John R. Writer</w:t></w:r></w:p>
    <w:p><w:r><w:t>Scholarly Contributions</w:t></w:r></w:p>
    <w:p><w:r><w:t>Books</w:t></w:r></w:p>
    <w:p><w:r><w:t>Writer, J. R. 2023. “The Example Book.” Sample Press.</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>"""


class DigitalMeasureExtractorTests(unittest.TestCase):
    def test_extracts_publications_for_each_resume_and_stops_at_next_section(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Digital Measures 2023.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", DOCUMENT)
            rows, summary = extract_report(path)
        self.assertEqual(summary["year"], 2023)
        self.assertEqual(summary["people"], 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["faculty_heading"], "Jane Q. Scholar")
        self.assertEqual(rows[0]["title"], "A useful article title")
        self.assertEqual(rows[1]["faculty_heading"], "John R. Writer")
        self.assertEqual(rows[1]["title"], "The Example Book")
        self.assertFalse(any("course" in row["raw_citation"].lower() for row in rows))


if __name__ == "__main__":
    unittest.main()
