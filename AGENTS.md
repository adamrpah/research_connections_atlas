# Repository guidance for Codex

## Mission

This repository turns institutional publication reports into a reproducible research-connections atlas. Keep the workflow reusable by colleges other than the original institution: avoid hard-coded names, URLs, credentials, or local absolute paths.

## Start here

1. Read `README.md` and `docs/ADAPTING_FOR_YOUR_COLLEGE.md`.
2. Run `python3 scripts/doctor.py` before changing code.
3. Install dependencies with `./scripts/bootstrap.sh` on macOS/Linux or `powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1` on Windows.
4. Never read, print, commit, or modify files in `.secrets/` unless the user explicitly asks.

## Repository map

- `code/`: Python extraction, resolution, topic-modeling, attribution, and export pipeline.
- `webapp/`: TypeScript/React atlas application.
- `huggingface_space/`: optional SPECTER2 matching service.
- `config/`: shareable institutional configuration examples.
- `data/`: local source records and curation inputs; sensitive/raw files are ignored.
- `results/`: generated pipeline artifacts; ignored and reproducible.
- `docs/`: onboarding, data, and institutional adaptation guidance.

## Working rules

- Run commands from the repository root unless documentation says otherwise.
- Treat annual reports, Digital Measures exports, spreadsheets, generated datasets, and feedback exports as potentially sensitive institutional data.
- Put credentials only in `.secrets/` or environment variables. Commit examples containing placeholders only.
- Prefer configuration and command-line arguments over institution-specific constants.
- Preserve provenance fields and deterministic IDs in all transformations.
- Do not imply that similarity edges are coauthorship or institutional recommendations.
- Do not commit model caches, downloaded PDFs, generated results, build outputs, or dependency folders.

## Verification

For Python-only changes:

```bash
.venv/bin/python -m unittest discover -s code -p 'test_*.py'
```

For web changes:

```bash
npm --prefix webapp run lint
npm --prefix webapp test
```

For onboarding/configuration changes:

```bash
python3 scripts/doctor.py --strict
```

Do not run the full population or SPECTER2 pipelines unless required: they use network services, substantial compute, and local institutional inputs.
