#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) values[argv[index]] = argv[index + 1];
  return values;
}

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
  const headers = rows.shift() ?? [];
  return rows.filter((values) => values.some(Boolean)).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
  );
}

function literal(value) {
  if (typeof value === "number") return value;
  const text = String(value ?? "").replace(/[\r\n\t]+/g, " ").trim();
  return text.startsWith("=") ? `'${text}` : text;
}

const args = parseArgs(process.argv.slice(2));
const root = process.cwd();
const registryPath = args["--registry"] ?? path.join(root, "results/institutional_faculty_registry.csv");
const attributionPath = args["--attributions"] ?? path.join(root, "results/faculty_attribution/article_faculty_attributions.csv");
const auditPath = args["--audit"] ?? path.join(root, "results/faculty_attribution/author_disambiguation_audit.csv");
const outputPath = args["--output"] ?? path.join(root, "data/faculty_attribution_review.xlsx");
const previewDir = args["--preview-dir"] ?? path.join(root, ".tmp-attribution-review", "previews");

const registry = parseCsv(await fs.readFile(registryPath, "utf8"));
const attributions = parseCsv(await fs.readFile(attributionPath, "utf8"));
const audit = parseCsv(await fs.readFile(auditPath, "utf8"));
const exceptions = audit.filter((row) => ["ambiguous", "provisional_owner_not_confirmed"].includes(row.status));

const canonicalHeaders = [
  "review_action", "canonical_name_override", "alias_to_add", "reviewer", "reviewed_at",
  "reviewer_notes", "faculty_id", "faculty_name", "aliases", "report_years",
  "canonical_authority", "source_types", "source_occurrences", "orcid", "orcid_source",
  "orcid_verified_at",
];
const canonicalRows = registry.map((row) => [
  "", "", "", "", "", "", row.faculty_id, row.faculty_name, row.aliases, row.report_years,
  row.canonical_authority, row.source_types, Number(row.source_occurrences || 0), row.orcid,
  row.orcid_source, row.orcid_verified_at,
].map(literal));

const attributionHeaders = [
  "review_action", "replacement_faculty_name", "reviewer", "reviewed_at", "reviewer_notes",
  "publication_id", "canonical_title", "faculty_name", "attribution_basis",
  "attribution_confidence", "report_years", "doi",
];
const attributionRows = attributions.map((row) => [
  "", "", "", "", "", row.publication_id, row.canonical_title, row.faculty_name,
  row.attribution_basis, Number(row.attribution_confidence || 0), row.report_years, row.doi,
].map(literal));

const exceptionHeaders = [
  "review_action", "replacement_faculty_name", "reviewer", "reviewed_at", "reviewer_notes",
  "publication_id", "canonical_title", "proposed_faculty_name", "status", "rule", "candidate_faculty",
];
const exceptionRows = exceptions.map((row) => [
  "", "", "", "", "", row.publication_id, row.canonical_title, row.faculty_name,
  row.status, row.rule, row.candidate_faculty,
].map(literal));

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("Instructions");
const canonical = workbook.worksheets.add("Canonical Faculty");
const attribution = workbook.worksheets.add("Attribution Review");
const exceptionSheet = workbook.worksheets.add("Exceptions");

instructions.showGridLines = false;
instructions.getRange("A1:H1").merge();
instructions.getRange("A1").values = [["Research Connections Atlas — Faculty Attribution Review"]];
instructions.getRange("A1:H1").format = {
  fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 18 }, verticalAlignment: "center",
};
instructions.getRange("A1:H1").format.rowHeight = 36;
instructions.getRange("A3:H3").merge();
instructions.getRange("A3").values = [["Edit only the yellow review columns. Download the completed workbook as .xlsx, then run the Python importer. Blank review_action cells are ignored."]];
instructions.getRange("A3:H3").format = { fill: "#FFF2CC", wrapText: true, verticalAlignment: "center" };
instructions.getRange("A3:H3").format.rowHeight = 42;
instructions.getRange("A5:C13").values = [
  ["Sheet", "Allowed review_action", "Meaning"],
  ["Canonical Faculty", "approve", "Name and aliases are acceptable; records the review only."],
  ["Canonical Faculty", "rename", "Use canonical_name_override as the preferred display name."],
  ["Canonical Faculty", "add_alias", "Use alias_to_add as an additional name form."],
  ["Canonical Faculty", "exclude", "Remove a non-person or out-of-scope roster entry."],
  ["Attribution Review", "approve / remove / replace", "Keep, remove, or replace an existing faculty-publication link."],
  ["Exceptions", "approve_add / reject / replace", "Add the proposal, keep it excluded, or replace it."],
  ["All sheets", "clear", "Remove a previously imported decision for this row."],
  ["All sheets", "reviewer + reviewed_at", "Recommended for provenance; use ISO date YYYY-MM-DD."],
];
instructions.getRange("A5:C5").format = { fill: "#4472C4", font: { bold: true, color: "#FFFFFF" } };
instructions.getRange("A5:C13").format.wrapText = true;
instructions.getRange("A:A").format.columnWidth = 24;
instructions.getRange("B:B").format.columnWidth = 30;
instructions.getRange("C:C").format.columnWidth = 72;

function buildReviewSheet(sheet, headers, rows, tableName, actions, widths) {
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
  const used = sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length);
  used.format.font = { name: "Aptos", size: 10 };
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
    fill: "#4472C4", font: { bold: true, color: "#FFFFFF" }, wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format.rowHeight = 32;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(2);
  if (rows.length) {
    sheet.getRangeByIndexes(1, 0, rows.length, Math.min(6, headers.length)).format.fill = "#FFF9E6";
    sheet.getRangeByIndexes(1, 0, rows.length, 1).dataValidation = { rule: { type: "list", values: actions } };
    sheet.getRangeByIndexes(1, 0, rows.length, headers.length).format.wrapText = true;
  }
  widths.forEach((width, index) => { sheet.getRangeByIndexes(0, index, rows.length + 1, 1).format.columnWidth = width; });
  sheet.tables.add(`A1:${String.fromCharCode(64 + headers.length)}${rows.length + 1}`, true, tableName);
}

buildReviewSheet(canonical, canonicalHeaders, canonicalRows, "CanonicalFacultyReview", ["approve", "rename", "add_alias", "exclude", "clear"], [18, 28, 28, 18, 14, 40, 24, 28, 38, 18, 22, 24, 16, 22, 20, 18]);
buildReviewSheet(attribution, attributionHeaders, attributionRows, "AttributionReview", ["approve", "remove", "replace", "clear"], [18, 28, 18, 14, 40, 24, 52, 28, 30, 16, 18, 24]);
buildReviewSheet(exceptionSheet, exceptionHeaders, exceptionRows, "AttributionExceptions", ["approve_add", "reject", "replace", "clear"], [18, 28, 18, 14, 40, 24, 52, 28, 30, 28, 36]);

const check = await workbook.inspect({
  kind: "table", range: "Canonical Faculty!A1:P6", include: "values,formulas",
  tableMaxRows: 6, tableMaxCols: 16,
});
console.log(check.ndjson);
const errors = await workbook.inspect({
  kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 }, summary: "formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, fileName] of [
  ["Instructions", "A1:H13", "instructions.png"],
  ["Canonical Faculty", "A1:P7", "canonical.png"],
  ["Attribution Review", "A1:L7", "attribution.png"],
  ["Exceptions", "A1:K7", "exceptions.png"],
]) {
  const rendered = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await rendered.arrayBuffer()));
}
console.log(JSON.stringify({ outputPath, registry: registry.length, attributions: attributions.length, exceptions: exceptions.length }));
