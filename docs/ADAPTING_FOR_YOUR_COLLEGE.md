# Adapting the workflow for another college

The reusable architecture is: **institutional reports → publication candidates → external metadata → human curation → topic model → faculty attribution → static atlas data → web application**.

## 1. Inventory your source records

Document which years and formats are available, who owns them, whether they may be processed externally, and whether the resulting metadata may be published. The current extractors support annual-report PDFs and Digital Measures-style Word exports; different layouts will usually need a new parser or a configurable adapter.

Keep original records outside Git. Place local working copies in the ignored `data/Annual-Reports/` and `data/DigitalMeasure-Reports/` directories.

## 2. Define institutional conventions

Copy `config/institution.example.json` to `config/institution.local.json`. Record branding, canonical faculty-name aliases, non-person headings, and the feedback endpoint. The example is a coordination template; some legacy pipeline constants still need to be moved behind this configuration before a new report layout can run without code changes.

When extending the pipeline, pass the configuration path explicitly and avoid embedding institution names or personal endpoints in source code.

## 3. Validate extraction before network enrichment

Run a dry extraction first:

```bash
.venv/bin/python code/run_population_pipeline.py \
  --dry-run --skip-resolution --skip-reconciliation
```

Review candidate counts, uncertain titles, faculty headings, page provenance, and duplicate behavior against a sample of source reports. Extraction favors recall and is not a substitute for review.

## 4. Resolve metadata responsibly

Set `CROSSREF_MAILTO` and `UNPAYWALL_EMAIL`; optionally create `.secrets/openalex_api_key`. Use small `--limit` runs first. The resolver only downloads locations identified as open access or accompanied by license metadata and does not bypass authentication.

## 5. Curate identities and metadata

Review the generated curation workbook and faculty-attribution audit files. Put approved, durable corrections in tracked configuration or curation inputs only after confirming that they are appropriate to publish. Do not silently treat a report heading as proof of authorship.

## 6. Model and interpret topics

Install the optional topic dependencies with `uv sync --extra topic`. Topic labels and similarity edges are analytical aids. Document the model, parameters, corpus coverage, review process, and known gaps for your audience.

## 7. Brand and deploy the application

Search the web application for `Research Connections Atlas` and replace visible branding through a configuration layer rather than a permanent one-off fork. Configure the optional SPECTER2 service and feedback database separately. Run the web lint, test, and production build before deploying.

The included `webapp/.openai/hosting.json` supports OpenAI Sites deployments. Other hosts can run the generated vinext application if their required runtime and bindings are configured.

## Recommended fork checklist

- [ ] Rights and privacy review completed for inputs and outputs.
- [ ] Source formats and expected counts documented.
- [ ] Institution-specific aliases and headings configured.
- [ ] Extraction sample manually validated.
- [ ] Metadata and attribution corrections reviewed.
- [ ] Topic-model limitations published.
- [ ] Branding, feedback endpoint, and deployment secrets replaced.
- [ ] Doctor, tests, lint, and production build pass.
