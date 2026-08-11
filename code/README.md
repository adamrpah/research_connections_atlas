# Scholarly impact pipeline

## Stage 1: annual-report publication extraction

Run from the repository root:

```bash
python3 code/extract_publications.py
```

The script reads `data/Annual-Reports/*.pdf` and writes:

- `results/publication_candidates.csv` - review-friendly tabular data
- `results/publication_candidates.jsonl` - machine-friendly pipeline input

Digital Measures Word reports use a separate, resume-by-resume layout. After the
annual-report PDF extraction, append their publication records to the same OpenAlex
candidate CSV with:

```bash
python3 code/extract_digitalmeasure_publications.py
```

The report year is read from each `.docx` filename. The extractor tracks the current
faculty/staff name and publication subsection, preserves the complete citation as the
resolver query together with faculty attribution and provenance, and writes a separate
audit summary to `results/digitalmeasure_extraction_summary.json`. It also writes
`results/digitalmeasure_extracted_records.csv`, whose `category` column contains
`article`, `book`, `book_chapter`, `presentation`, or `other`. Every category is
retained for audit, and `is_ongoing` flags citations marked as ongoing, submitted,
working paper, or reviewed-not-accepted. Presentations and ongoing works are excluded
from the Crossref/OpenAlex candidate file; publication-ready articles, books, chapters,
and other works are forwarded for resolution. Reruns are idempotent by record ID.
The same extraction builds `results/institutional_faculty_registry.csv`, a stable-ID
roster. Digital Measures resume owners provide the canonical name when available;
annual-report headings add year-bounded historical-only people. Before any network
request, every PDF and Digital Measures candidate is annotated with matched
institutional faculty IDs, names, and JSON evidence. Conservative citation matching
can identify multiple local coauthors; ambiguous surname-and-initial forms are left
unmatched. Resume ownership is retained as provisional evidence when the citation
does not name the owner explicitly.
Use `--replace-digitalmeasure` after changing extraction logic to replace only prior
Digital Measures rows while preserving all PDF-derived candidates.
- `results/extraction_summary.json` - counts, page ranges, and QA statistics

The complete citation and its report/page provenance are retained. Rows without a
usable citation are discarded, and exact normalized-citation duplicates within a report
are removed. `needs_review` is true when a citation cannot be retained confidently.
Those rows should be reviewed before DOI resolution and publication downloading.

Known QA items:

- The 1999 report is image-only and requires an OCR dependency before extraction.
- The 1997 layout does not consistently separate citations in its text layer, so its
  rows should be manually compared with the report before downstream use.
- Candidate counts can exceed narrative publication counts because a single book
  record may mention multiple titled chapters and because extraction favors recall.

Planned downstream stages are: citation/DOI resolution, rights-aware PDF retrieval,
text extraction, research-theme embeddings or supervised classification, and an
interactive researcher-publication-topic network application.

## End-to-end data population harness

Run both report extractors, Crossref/OpenAlex resolution and legal OA downloads, and
publication-count reconciliation with one command:

```bash
python3 code/run_population_pipeline.py \
  --mode append \
  --openalex-api-key-file .secrets/openalex_api_key
```

`--mode append` preserves the candidate dataset and resolver cache, adds only unseen
report records, and resolves only uncached candidates. `--mode rebuild` replaces the
candidate CSV/JSONL from the current PDF and Word reports, prunes stale cache records,
and re-resolves every current candidate. Use `--dry-run` to inspect extraction and
merge counts without changing results or making network requests. Other useful flags
include `--no-download`, `--limit N`, `--skip-resolution`,
`--skip-openalex-fallback`, and `--skip-reconciliation`.

## Publication-count reconciliation

```bash
python3 code/reconcile_publication_counts.py
```

This compares `Scholarly Papers Published` in `data/Annual Report compilation.xlsx`
with annual candidate, parsed-title, high-confidence-title, and normalized unique-title
counts. The image-only 1999 report is excluded by default. Results are written to
`results/publication_count_reconciliation.csv` and JSON.

## Stage 2: metadata resolution and open-access PDF retrieval

Faculty attribution begins before this stage. Crossref and OpenAlex metadata enrich
the provisional local evidence with structured authorships, author IDs, ORCIDs, and
institutions. For resolved works, an unconfirmed resume-owner link is not treated as
authorship; explicit citation matches remain auditable alongside external evidence.

Test a small resumable batch:

```bash
export CROSSREF_MAILTO="you@example.edu"
export UNPAYWALL_EMAIL="you@example.edu"      # recommended for OA locations
export OPENALEX_API_KEY="..."                 # optional
python3 code/resolve_and_download_publications.py --limit 25
```

To keep the OpenAlex key out of the shell environment and tool output, place the raw
key in `.secrets/openalex_api_key` and run:

```bash
python3 code/resolve_and_download_publications.py \
  --openalex-api-key-file .secrets/openalex_api_key --limit 25
```

Continue the run by executing the same command without `--limit`. Resolved metadata,
scores, URLs, licenses, and download status are written under
`results/publication_resolution/`. Validated open-access PDFs are stored in
`data/publication_pdfs/`. Available abstracts are stored in the resolution CSV and as
plain-text files under `data/publication_abstracts/`. The cache makes interrupted runs
resumable.

### Human publication metadata curation

Reviewers can edit `data/publication_metadata_curation.xlsx` directly. The
`Publication Curation` sheet contains one row per resolved publication. Paste a missing
abstract into `abstract`, or correct `title`, `publication_year`, `doi`, `authors`, or
`landing_url`. Identity columns are protected, and optional `contributor` and `notes`
fields provide an audit trail.

The importer compares the visible values with the workbook's read-only reference sheet and
applies only changed cells, propagating a correction to every annual-report record for
the same work:

```bash
python3 code/apply_publication_metadata_curation.py
```

Both population and analytical refresh pipelines run this importer automatically, so
automated metadata resolution may be refreshed without losing human corrections.

Only titles with extraction confidence at least 0.75 are resolved by default. Only
PDF locations exposed as open access or accompanied by license metadata are downloaded;
the script does not bypass authentication or paywalls.

After the Crossref pass, directly search OpenAlex for cached unmatched records:

```bash
python3 code/resolve_and_download_publications.py \
  --openalex-api-key-file .secrets/openalex_api_key --openalex-fallback
```

The fallback requires a strong, unambiguous title match and uses publication year as
additional evidence. It enriches accepted matches with abstracts and OA PDFs. Accepted
fallback matches are also written to
`results/publication_resolution/openalex_fallback_matches.csv` for focused human review.

## Stage 3: abstract topic discovery

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r code/topic_model_requirements.txt
.venv/bin/python code/cluster_publications.py
```

The default pipeline embeds canonical titles plus abstracts with SPECTER2, reduces the
embedding space with UMAP, discovers topics with HDBSCAN, and extracts interpretable
c-TF-IDF terms. Outputs are written to `results/topic_model_specter2/`.

### Live abstract matching

The atlas's “Match an abstract” tab uses a small companion inference service so the
deployed edge app does not need to load the SPECTER2 model itself. Start it from the
repository root with `python code/serve_specter2_matcher.py`. Configure the website's
`SPECTER2_ENDPOINT_URL` as the public service URL ending in `/match`. If the service
sets `SPECTER2_API_TOKEN`, configure the website with the same secret. Abstracts are
processed in memory and are not stored by this service.

## Stage 4: web-app data build

After labeling and propagating topics, build the complete static data package:

```bash
python3 code/label_and_propagate_topics.py
python3 code/build_webapp_data.py
```

The builder writes validated entity, graph, search, provenance, and feedback-contract
artifacts under `results/webapp/`. Stable IDs are used for faculty, publications,
topics, and edges. `manifest.json` records schema and model versions, parameters,
counts, integrity checks, file sizes, and SHA-256 checksums.

Research-similarity edges combine faculty publication-embedding similarity with topic-
profile similarity. They represent possible intellectual overlap, not coauthorship.
`coauthor_edges.json` is intentionally empty until author identity resolution is run.

`feedback_config.json` defines valid targets and submission values for topic-quality,
attribution, and metadata feedback. The web app persists submissions in its hosted
database and exposes attribution complaints only through an administrator-protected
pipeline endpoint.

## Full analytical and app-data refresh

Run the complete topic, attribution, export, and application build pipeline with:

```bash
.venv/bin/python code/run_refresh_pipeline.py
```

The pipeline securely downloads attribution feedback, reruns SPECTER2 topic
clustering, applies the curated topic labels, resolves faculty attribution, rebuilds
the web-app graph/search data, copies the current artifacts into `webapp/public/data`,
and validates the production application build. Use `--skip-clustering` while
developing downstream stages to reuse the existing topic model.

Faculty resolution combines annual-report headings, resolved publication authors,
and citation-leading names. It rejects a heading only when the citation lead and
resolved author evidence identify a different known faculty member; incomplete
metadata alone does not remove an attribution. Approved corrections live in
`data/faculty_attribution_overrides.csv`, making feedback decisions auditable and
durable across reruns. Newly submitted complaints are exported to
`results/feedback/attribution_feedback_review.csv` and marked `needs_review` until
an approved override is added.

### Faculty-name and attribution review round trip

Generate the review workbook after building the institutional registry and running
faculty attribution:

```bash
node code/create_faculty_attribution_review_workbook.mjs
```

Upload `data/faculty_attribution_review.xlsx` to Google Sheets. Reviewers edit only
the yellow columns on `Canonical Faculty`, `Attribution Review`, and `Exceptions`.
Use `clear` to withdraw a previously imported decision for a row.
Download the reviewed file as `.xlsx` to the same local path, then validate and import:

```bash
.venv/bin/python code/import_faculty_attribution_review.py --dry-run
.venv/bin/python code/import_faculty_attribution_review.py
```

The importer upserts reviewer decisions into the tracked
`data/faculty_attribution_review_decisions.csv` and derives the tracked name and
publication-attribution override CSVs. The workbook itself is generated, ignored,
and never the authoritative record. Population rebuilds apply canonical-name
overrides before citation matching; analytical refreshes apply reviewed attribution
adds and removals after local/OpenAlex disambiguation.

### Curated faculty identifiers

Add faculty-provided or otherwise verified ORCIDs to `data/faculty_identifiers.csv`.
Join each identifier to the stable `faculty_id`; `faculty_name` is a human-readable
cross-check rather than the key. ORCIDs are normalized and checksum-validated, then
carried into the generated institutional registry and review workbook. An exact ORCID
on an OpenAlex authorship is treated as strong identity evidence, but the identifier
does not independently add unrelated publications to the corpus. Conflicting external
ORCIDs are retained in the author identity profile and flagged rather than replacing
the curated value.

```csv
faculty_id,faculty_name,orcid,source,verified_at,notes
fac_example1234567,Jane Q. Scholar,0000-0002-1825-0097,faculty_provided,2026-08-06,
```

Set `FEEDBACK_EXPORT_URL` (or pass `--url` directly to
`fetch_attribution_feedback.py`) for the deployed college-specific feedback endpoint.
The default source code intentionally contains no personal deployment URL.

## Publication and faculty impact

Refresh one OpenAlex impact record per matched publication with:

```bash
.venv/bin/python code/refresh_openalex_impact.py \
  --openalex-api-key-file .secrets/openalex-api-key.txt
```

This stage stores no individual citing works or citation edges. It writes the latest
publication measures to `results/impact/current_work_impact.csv` and appends successful
dated observations to `results/impact/work_impact_snapshots.csv`. Measures supplied by
OpenAlex include total and annual citation counts, FWCI, normalized citation percentile,
top-one/top-ten-percent flags, same-year percentile bounds, bibliography size, open-access
status, and retraction status. Locally calculated measures include publication age,
citations per year, recent one/two/five-year citations, recent citation share, active
citation years, years since the earliest citation in OpenAlex's reported ten-year
window, and uncited status. `impact_qa.json` records
coverage and failures while retaining the last successful current observation.

Faculty measures are deliberately calculated only after canonical-name matching,
OpenAlex author disambiguation, and reviewed attribution overrides:

```bash
.venv/bin/python code/build_faculty_impact_summary.py
```

`results/impact/faculty_impact_summary.csv` contains corpus-scoped citation totals,
coverage, means and medians, normalized-impact shares, recent citations, and explicitly
named `corpus_h_index` and `corpus_i10_index` values. These are derived only from works
accepted into this dataset; OpenAlex lifetime author totals are not used. The web-data
builder embeds available current work and faculty measures in `publications.json`,
`faculty.json`, and `faculty_profiles.json`.

Population runs refresh publication impact automatically when an OpenAlex key is
provided. Analytical refreshes reuse the current work file, calculate faculty measures
after attribution, and can also refresh OpenAlex first with:

```bash
.venv/bin/python code/run_refresh_pipeline.py \
  --refresh-openalex-impact \
  --openalex-api-key-file .secrets/openalex-api-key.txt
```
