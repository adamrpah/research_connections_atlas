#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const inputPath = path.join(root, "results/publication_resolution/publication_resolution.csv");
const outputPath = path.join(root, "data/publication_metadata_curation.xlsx");

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { cell += '"'; i += 1; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(cell); cell = ""; }
    else if (char === '\n') { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
    else cell += char;
  }
  if (cell || row.length) { row.push(cell.replace(/\r$/, "")); rows.push(row); }
  const headers = rows.shift();
  return rows.filter((values) => values.some(Boolean)).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
  );
}

function normalizedTitle(row) {
  return (row.canonical_title || row.original_title || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function workKey(row) {
  return row.doi.trim() ? `doi:${row.doi.trim().toLowerCase()}` : `title:${normalizedTitle(row)}`;
}

function excelLiteral(value) {
  return typeof value === "string" && value.startsWith("=") ? `'${value}` : value;
}

const sourceRows = parseCsv(await fs.readFile(inputPath, "utf8"))
  .filter((row) => row.match_status === "matched");
const groups = new Map();
for (const row of sourceRows) {
  const key = workKey(row);
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(row);
}

const headers = [
  "work_key", "source_record_ids", "title", "publication_year", "doi", "authors",
  "landing_url", "abstract", "contributor", "notes",
];
const records = [...groups.entries()].map(([key, rows]) => {
  rows.sort((a, b) => b.abstract.trim().length - a.abstract.trim().length);
  const best = rows[0];
  return [
    key,
    rows.map((row) => row.record_id).sort().join(";"),
    best.canonical_title || best.original_title,
    best.publication_year ? Number(best.publication_year) : null,
    best.doi,
    best.authors,
    best.landing_url,
    excelLiteral(best.abstract),
    "",
    "",
  ];
}).sort((a, b) => {
  const missingAbstract = Number(!b[7]) - Number(!a[7]);
  return missingAbstract || String(a[2]).localeCompare(String(b[2]));
});

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("Instructions");
const curation = workbook.worksheets.add("Publication Curation");
const baseline = workbook.worksheets.add("Baseline - Do Not Edit");

instructions.showGridLines = false;
instructions.getRange("A1:H1").merge();
instructions.getRange("A1").values = [["Publication Metadata Curation"]];
instructions.getRange("A1:H1").format = {
  fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 18 },
  verticalAlignment: "center",
};
instructions.getRange("A1:H1").format.rowHeight = 34;
instructions.getRange("A3:H3").merge();
instructions.getRange("A3").values = [["Paste an abstract or correct publication details in the yellow cells on the Publication Curation sheet. The next pipeline refresh will use only the cells that differ from the baseline."]];
instructions.getRange("A3:H3").format = { fill: "#FFF2CC", font: { color: "#3F3F3F" }, wrapText: true, verticalAlignment: "center" };
instructions.getRange("A3:H3").format.rowHeight = 48;
instructions.getRange("A5:B10").values = [
  ["What to edit", "How it is used"],
  ["abstract", "Paste the publication abstract as plain text."],
  ["title / year / DOI", "Correct bibliographic details when the automated match is wrong."],
  ["authors / landing_url", "Use semicolons between authors; provide the publication landing page URL."],
  ["contributor", "Optional: identify the person making the edit."],
  ["notes", "Optional: record evidence, uncertainty, or a source URL."],
];
instructions.getRange("A5:B5").format = { fill: "#4472C4", font: { bold: true, color: "#FFFFFF" } };
instructions.getRange("A6:B10").format.wrapText = true;
instructions.getRange("A5:B10").format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
instructions.getRange("A12:H12").merge();
instructions.getRange("A12").values = [["Do not edit work_key, source_record_ids, or the Baseline sheet. Missing abstracts are listed first. Filters are enabled so work can be divided by title, year, contributor, or abstract status."]];
instructions.getRange("A12:H12").format = { fill: "#E2F0D9", wrapText: true };
instructions.getRange("A12:H12").format.rowHeight = 38;
instructions.getRange("A:B").format.columnWidth = 36;

for (const sheet of [curation, baseline]) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, records.length + 1, headers.length).values = [headers, ...records];
  sheet.getRange(`A1:J${records.length + 1}`).format.font = { name: "Aptos", size: 10 };
  sheet.getRange("A1:J1").format = {
    fill: sheet === curation ? "#4472C4" : "#7F8C8D",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange("A1:J1").format.rowHeight = 32;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  sheet.getRange(`A2:B${records.length + 1}`).format = { fill: "#E7E6E6", font: { color: "#666666" } };
  sheet.getRange(`C2:J${records.length + 1}`).format.wrapText = true;
  sheet.getRange("A:A").format.columnWidth = 22;
  sheet.getRange("B:B").format.columnWidth = 26;
  sheet.getRange("C:C").format.columnWidth = 42;
  sheet.getRange("D:D").format.columnWidth = 13;
  sheet.getRange("E:E").format.columnWidth = 20;
  sheet.getRange("F:F").format.columnWidth = 32;
  sheet.getRange("G:G").format.columnWidth = 34;
  sheet.getRange("H:H").format.columnWidth = 70;
  sheet.getRange("I:I").format.columnWidth = 18;
  sheet.getRange("J:J").format.columnWidth = 34;
  sheet.getRange(`D2:D${records.length + 1}`).setNumberFormat("0");
  sheet.tables.add(`A1:J${records.length + 1}`, true, sheet === curation ? "PublicationCurationTable" : "PublicationBaselineTable");
}

curation.getRange(`C2:J${records.length + 1}`).format.fill = "#FFF9E6";
curation.getRange(`H2:H${records.length + 1}`).conditionalFormats.add("containsBlanks", { format: { fill: "#FCE4D6" } });
baseline.getRange(`A2:J${records.length + 1}`).format = { fill: "#F2F2F2", font: { color: "#666666" }, wrapText: true };

const keyCheck = await workbook.inspect({
  kind: "table", range: "Publication Curation!A1:J6", include: "values,formulas",
  tableMaxRows: 6, tableMaxCols: 10,
});
console.log(keyCheck.ndjson);
const errors = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 }, summary: "formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const previewDir = path.join(root, ".tmp-curation-workbook", "previews");
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, fileName] of [
  ["Instructions", "A1:H12", "instructions.png"],
  ["Publication Curation", "A1:J8", "curation.png"],
  ["Baseline - Do Not Edit", "A1:J6", "baseline.png"],
]) {
  const rendered = await workbook.render({ sheetName, range, scale: 1.25, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await rendered.arrayBuffer()));
}
console.log(`Created ${outputPath} with ${records.length} unique matched publications.`);
