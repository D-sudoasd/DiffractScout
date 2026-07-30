# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Before opening a change

1. Search existing issues and pull requests.
2. Describe the scientific or software problem and the expected behavior.
3. State whether the proposal changes a numerical definition, data schema, provider contract, or output file.
4. Do not include API keys, unpublished experimental data, proprietary CIF files, or restricted literature.

## Development setup

```bash
git clone https://github.com/D-sudoasd/DiffractScout.git
cd DiffractScout
python -m venv .venv
python -m pip install -e ".[test]"
pytest -q
```

Materials Project development additionally requires:

```bash
python -m pip install -e ".[mp,test]"
```

Tests must not depend on a live Materials Project API unless they are explicitly marked as integration tests and excluded from the default CI suite.

## Pull-request requirements

- Add or update tests for changed numerical behavior.
- Update `docs/SCIENTIFIC_CONTRACTS.md` when a definition or assumption changes.
- Update the schema version when a machine-readable output contract changes incompatibly.
- Preserve missing values; do not replace absent scientific data with guessed numbers.
- Add source and unit metadata for new numerical fields.
- Run `python scripts/check_release.py --skip-wheel`; use the full release check before a tagged release.
- For GUI changes, run the Xvfb smoke command in `docs/GUI.md` and update reference screenshots when the layout changes.
- Explain any result differences in the pull-request description.

## Scientific review

A change involving structure factors, systematic absences, tensor conventions, coordinate transforms, elastic moduli, database semantics, or uncertainty handling requires review by a contributor with relevant domain expertise.

## Release process

The maintainer updates the changelog and version, runs the complete test and demo validation, creates a signed or annotated Git tag, publishes release notes, and archives the tagged source with Zenodo or an equivalent repository. See `docs/RELEASE.md`.
