## Purpose

Describe the research or software problem addressed by this pull request.

## Changes

List the files, numerical contracts, data schemas, providers, or user workflows changed.

## Scientific evidence

Provide analytical checks, independent comparisons, public/synthetic fixtures, units, tolerances, and interpretation of any changed result.

## Validation

- [ ] `ruff check src tests scripts`
- [ ] `python -m compileall -q src tests scripts`
- [ ] `pytest --cov=diffractscout --cov-fail-under=65`
- [ ] `diffractscout demo -o outputs/pr_demo`
- [ ] `diffractscout verify outputs/pr_demo`
- [ ] Documentation and changelog updated when applicable
- [ ] No API keys, restricted data, build artifacts, or local paths committed

## Compatibility and provenance

State whether this changes an output schema, equation, coordinate convention, dependency, source attribution, or backward-compatible behavior.
