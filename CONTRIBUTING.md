# Contributing

## Set up a checkout

Follow the new-computer quick start in `README.md`, then run:

```bash
python3 scripts/doctor.py --strict
.venv/bin/python -m unittest discover -s code -p 'test_*.py'
npm --prefix webapp run lint
npm --prefix webapp test
```

## Make changes safely

- Create a branch for each focused change.
- Do not commit credentials, raw institutional exports, downloaded publications, or generated results.
- Keep institution-specific values in configuration or local files rather than source constants.
- Add or update tests when transformation behavior changes.
- Document schema changes and preserve source provenance.
- Inspect `git status` and the staged diff before every commit.

## Proposing an institutional adaptation

Describe the source-report formats, fields, privacy constraints, and expected outputs. Prefer adding a configurable parser or adapter instead of changing defaults solely for one college.

## Pull-request checklist

- [ ] The project doctor passes.
- [ ] Relevant Python and/or web tests pass.
- [ ] No credentials or private institutional data are included.
- [ ] Documentation and configuration examples match the change.
- [ ] Generated files are excluded unless they are intentional, reviewed fixtures.
