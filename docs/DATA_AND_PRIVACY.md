# Data, credentials, and publication guidance

## Never commit

- API keys, admin keys, access tokens, or `.env` files containing real values
- raw annual reports or Digital Measures exports unless publication is explicitly authorized
- downloaded article PDFs
- private feedback exports
- model caches, dependency folders, or generated pipeline results
- local Codex authentication or chat-history files

The root `.gitignore` excludes these categories by default. Before pushing any branch, inspect both `git status` and `git diff --cached`.

## Data categories

| Category | Default location | Git policy |
| --- | --- | --- |
| Shareable source code and docs | `code/`, `webapp/`, `docs/` | Track |
| Configuration template | `config/institution.example.json` | Track |
| Local institutional configuration | `config/institution.local.json` | Ignore if it contains sensitive details |
| Source reports and exports | `data/Annual-Reports/`, `data/DigitalMeasure-Reports/` | Ignore |
| Credentials | `.secrets/`, `.env` | Ignore |
| Downloaded PDFs and abstracts | `data/publication_*` | Ignore |
| Generated analysis | `results/` | Ignore or publish through a separately reviewed release/data repository |
| Public atlas dataset | `webapp/public/data/` | Generate locally; publish only after review |

## Sharing a reproducible dataset

Large or institution-specific datasets should be versioned separately from the code repository—for example in a reviewed data release, institutional repository, or object store—with a schema, checksum manifest, license, and provenance statement. Do not use Git LFS as a substitute for a privacy and rights review.

The repository's Apache-2.0 license applies to its source code and documentation.
It does not automatically grant rights to annual reports, publication content,
institutional branding, personal data, or generated datasets assembled from
third-party sources.

## Credentials

Prefer a secret manager in production. For local pipeline use, place raw single-value keys in `.secrets/` and pass the corresponding `--*-key-file` option. Never paste a key into a Codex prompt, command output, issue, or commit.

## Human review

External metadata services and automated entity resolution can be wrong. Keep provenance, make overrides auditable, and provide a correction path. Similarity and topic outputs must not be presented as faculty performance evaluation or verified collaboration.
