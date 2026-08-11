# Research Connections Atlas

A reusable pipeline and web application for turning college publication records into an explorable map of faculty, publications, research themes, and potential intellectual connections.

The repository is designed so a new contributor can clone it, attach the folder to Codex, validate the machine, and begin work without copying another computer's virtual environment, credentials, caches, or chat history.

## Pipeline at a glance

```mermaid
flowchart TB
    classDef editable fill:#fff2cc,stroke:#9a6700,color:#24292f,stroke-width:2px
    classDef generated fill:#ddf4ff,stroke:#0969da,color:#24292f
    classDef published fill:#dafbe1,stroke:#1a7f37,color:#24292f

    subgraph inputs["Institutional inputs — local and editable"]
        reports["data/Annual-Reports/*.pdf<br/>data/DigitalMeasure-Reports/*.docx"]:::editable
        identity["data/faculty_identifiers.csv<br/>data/faculty_name_overrides.csv"]:::editable
        attribution_edits["data/faculty_attribution_overrides.csv<br/>data/faculty_attribution_review_decisions.csv"]:::editable
        metadata_edits["data/publication_metadata_curation.xlsx<br/>Generated metadata-review workbook; editable"]:::editable
    end

    extract["1. Extract and classify records<br/>presentations and ongoing work remain audit-only"]
    resolve["2. Resolve publication metadata<br/>Crossref + OpenAlex"]
    impact["3. Refresh publication impact<br/>OpenAlex measures + local calculations; no citation records"]
    model["4. Embed, cluster, and label topics"]
    attribute["5. Resolve faculty identity and attribution<br/>local evidence + curated ORCID + OpenAlex"]
    faculty_impact["6. Aggregate faculty impact<br/>only after reviewed attribution"]
    export["7. Build validated web dataset"]

    reports --> extract
    identity --> extract
    extract --> candidates
    candidates --> resolve
    metadata_edits -. "review corrections" .-> resolve
    resolution --> metadata_edits
    resolve --> resolution
    resolution --> impact
    resolution --> model
    candidates --> model
    model --> attribute
    identity --> attribute
    attribution_edits --> attribute
    attribute --> faculty_impact
    impact --> faculty_impact
    attribute --> export
    faculty_impact --> export
    impact --> export
    model --> export

    candidates["results/<br/>publication_candidates.csv + .jsonl<br/>extraction_summary.json<br/>digitalmeasure_extracted_records.csv<br/>digitalmeasure_extraction_summary.json<br/>institutional_faculty_registry.csv<br/>population_pipeline_summary.json<br/>publication_count_reconciliation.csv + .json"]:::generated

    resolution["results/publication_resolution/<br/>publication_resolution.csv<br/>resolution_cache.jsonl<br/>openalex_fallback_matches.csv<br/>resolution_summary.json<br/><br/>data/publication_pdfs/<br/>data/publication_abstracts/"]:::generated

    impact_outputs["results/impact/<br/>current_work_impact.csv<br/>work_impact_snapshots.csv<br/>impact_qa.json<br/>faculty_impact_summary.csv<br/>faculty_impact_qa.json"]:::generated
    impact --> impact_outputs
    faculty_impact --> impact_outputs

    model["4. Embed, cluster, and label topics<br/><br/>results/topic_model_specter2/<br/>embeddings.npy · coordinates_2d.npy<br/>article_topic_assignments.csv<br/>topics.csv + topics.json · metrics.json<br/>labeled_topics.csv + .json<br/>labeled_article_topics.csv<br/>faculty_topic_publications.csv<br/>unattributed_topic_publications.csv<br/>faculty_topic_summary.csv<br/>faculty_topic_matrix.csv<br/>faculty_topic_profiles.json<br/>faculty_topic_qa.json"]:::generated

    attribution_outputs["results/faculty_attribution/<br/>article_faculty_attributions.csv<br/>faculty_registry.csv<br/>faculty_author_identity_profiles.csv<br/>author_disambiguation_audit.csv<br/>qa.json"]:::generated
    attribute --> attribution_outputs

    feedback["results/feedback/<br/>attribution_feedback.json<br/>attribution_feedback_review.csv"]:::generated
    feedback -. "approved corrections" .-> attribution_edits

    review_book["data/faculty_attribution_review.xlsx<br/>Generated review interface; yellow columns are editable<br/>download/import decisions back into tracked CSVs"]:::editable
    attribution_outputs --> review_book
    google_review["Shared Google Sheet<br/>Optional public or restricted collaborative review copy<br/>reviewers edit the same yellow decision columns"]:::editable
    review_book -- "upload .xlsx" --> google_review
    google_review -- "download reviewed .xlsx" --> review_book
    review_book -. "review round trip" .-> attribution_edits

    webdata["results/webapp/<br/>faculty.json · topics.json · publications.json<br/>faculty_profiles.json · publication_provenance.json<br/>graph_nodes.json · graph_edges.json<br/>faculty_topic_edges.json · faculty_similarity_edges.json<br/>publication_faculty_edges.json · coauthor_edges.json<br/>search_documents.json · semantic_search_index.json<br/>semantic_search_embeddings.npy<br/>feedback_config.json · manifest.json"]:::generated
    export --> webdata
    published_data["webapp/public/data/<br/>faculty.json · topics.json · publications.json<br/>faculty_profiles.json · faculty_topic_edges.json<br/>faculty_similarity_edges.json · manifest.json"]:::published
    webdata --> published_data
    published_data --> app["Research Connections Atlas web application"]:::published
```

Yellow nodes are human-editable inputs or review interfaces. Blue nodes are reproducible local outputs and should not be edited directly. Green nodes are the generated assets copied into the web application for publication. Raw institutional inputs, downloaded content, review workbooks, and `results/` are ignored by Git; the curated CSV decision files are tracked.

## New-computer quick start

### 1. Clone and enter the repository

```bash
git clone <YOUR-REPOSITORY-URL> research-connections-atlas
cd research-connections-atlas
```

### 2. Install prerequisites

- Git
- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/) (recommended Python environment manager)
- Node.js 22.13 or newer and npm
- Poppler (`pdftotext`) for PDF annual-report extraction

Then run:

```bash
./scripts/bootstrap.sh
python3 scripts/doctor.py --strict
```

Windows PowerShell users can run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
python scripts/doctor.py --strict
```

The bootstrap installs the ordinary Python and web-development dependencies. Topic modeling is deliberately optional because PyTorch and SPECTER2 are large:

```bash
uv sync --extra topic
```

### 3. Open it in Codex

1. Open the ChatGPT desktop app and select **Codex**.
2. Add a local project and select this repository's root folder.
3. Make this folder the project's primary folder.
4. Trust the repository when prompted so Codex can load the checked-in project guidance.
5. Start a new chat with: `Read AGENTS.md and README.md, run the project doctor, and orient me to this repository.`

Codex will automatically use `AGENTS.md` as durable repository guidance. Local chat history is machine-specific; durable decisions belong in Git-tracked documentation, issues, and commits.

## Try the application

After bootstrapping:

```bash
npm --prefix webapp run dev
```

Open the local URL printed by the development server. A complete institutional dataset is generated by the pipeline and copied to `webapp/public/data/`; raw and generated data are intentionally not committed by default.

## Run the data workflow

1. Copy your PDF annual reports into `data/Annual-Reports/`.
2. Copy optional Digital Measures `.docx` exports into `data/DigitalMeasure-Reports/`.
3. Create the local files described in `.env.example` and `docs/DATA_AND_PRIVACY.md`.
4. Run a local, non-network extraction check:

```bash
.venv/bin/python code/run_population_pipeline.py \
  --dry-run --skip-resolution --skip-reconciliation
```

5. Follow [the pipeline guide](code/README.md) for resolution, curation, topic modeling, attribution, and application-data generation.

For a different institution, begin with [Adapting for your college](docs/ADAPTING_FOR_YOUR_COLLEGE.md).

## Common commands

```bash
# Machine and checkout validation
python3 scripts/doctor.py --strict

# Python tests
.venv/bin/python -m unittest discover -s code -p 'test_*.py'

# Web lint, test, build, and development server
npm --prefix webapp run lint
npm --prefix webapp test
npm --prefix webapp run build
npm --prefix webapp run dev
```

## What is and is not shared through Git

Git shares source code, configuration examples, documentation, tests, and reproducible environment definitions. It intentionally excludes credentials, source reports, downloaded publications, model caches, generated results, and local Codex chats.

See [Data and privacy](docs/DATA_AND_PRIVACY.md) before publishing a fork.

## Project status

This is a research workflow, not an authoritative faculty-evaluation system. Metadata resolution, entity attribution, and topic clustering require human review. Similarity connections indicate analytical overlap, not coauthorship, endorsement, or institutional recommendation.

## License

The source code and documentation in this repository are licensed under the
[Apache License 2.0](LICENSE). Institutional source records, publication content,
generated datasets, names, logos, and other third-party materials are not
automatically covered by that license.

## Documentation

- [Pipeline reference](code/README.md)
- [Adapting for your college](docs/ADAPTING_FOR_YOUR_COLLEGE.md)
- [Data and privacy](docs/DATA_AND_PRIVACY.md)
- [Contributing](CONTRIBUTING.md)
- [Codex project guidance](AGENTS.md)
