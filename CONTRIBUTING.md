# Contributing

Contributions are welcome through GitHub issues and pull requests.

## Before opening a change

1. Search existing issues and pull requests.
2. Describe the scientific or software problem and the expected behavior.
3. State whether the proposal changes a numerical definition, data schema, provider contract, or output file.
4. Do not include API keys, unpublished experimental data, proprietary CIF files, or restricted literature.

## Development setup

Windows / PowerShell:

```powershell
git clone https://github.com/D-sudoasd/DiffractScout.git
cd DiffractScout
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_gui.py
```

Bash:

```bash
git clone https://github.com/D-sudoasd/DiffractScout.git
cd DiffractScout
python -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pytest -q --ignore=tests/test_gui.py
```

Use that same environment for subsequent commands below. GUI interaction
tests need a working Tk display; see the [GUI guide](docs/GUI.md).

Normal development and test work only needs `.[test]`. Before running the
complete local release preflight, install the additional release tooling with:

```bash
python -m pip install -e ".[test,release]"
```

Materials Project development additionally requires:

```bash
python -m pip install -e ".[mp,test]"
```

Tests must not depend on a live Materials Project API unless they are explicitly marked as integration tests and excluded from the default CI suite.

## Pull-request requirements

- Use change-specific local checks from the [workflow guide](docs/AGENT_WORKFLOW.md).
  Documentation-only changes normally need `python scripts/check_docs.py`
  and `git diff --check`; code changes need the affected tests and lint checks.
- Add or update meaningful tests for changed numerical behavior or contracts.
- Update `docs/SCIENTIFIC_CONTRACTS.md` when a definition or assumption changes.
- Update the schema version when a machine-readable output contract changes incompatibly.
- Preserve missing values; do not replace absent scientific data with guessed numbers.
- Add source and unit metadata for new numerical fields.
- Run the analytic benchmark for scientific-core changes, using a fresh output
  directory; record settings, tolerances and any changed result. Do not
  overwrite earlier evidence merely to rerun a check.
- Required CI checks remain the PR gate. Broaden local checks for shared
  interfaces, dependencies or packaging. Use the complete
  `python scripts/check_release.py` for release candidates; `--skip-wheel`
  still runs the full tests, demo and benchmark and is not a routine shortcut.
- Update `docs/evidence/impact_evidence.json` only for completed, traceable public records; never infer impact from private or prospective activity.
- For GUI changes, exercise affected interactions with a working Tk display;
  Linux contributors can use the Xvfb commands in `docs/GUI.md`. Record any
  unavailable GUI checks and update reference screenshots when layout changes.
- Explain any result differences in the pull-request description.

## Validation and evidence contributions

Real-material, independent-software, or external-installation reports should use `docs/VALIDATION_CASE_TEMPLATE.md` and the issue forms in `.github/ISSUE_TEMPLATE/`. Public evidence must identify the software version, inputs, settings, units, tolerances, reference method, result, and limitations. Attribution requires contributor consent.

## Scientific review

A change involving structure factors, systematic absences, tensor conventions, coordinate transforms, elastic moduli, database semantics, or uncertainty handling requires review by a contributor with relevant domain expertise.

Complete the authorized implementation and numerical evidence before requesting
that review. Documentation corrections that do not change these meanings do
not automatically require scientific review. Synthetic benchmarks and passing
tests do not establish experimental validity.

## Working with coding agents

Project instructions are in [AGENTS.md](AGENTS.md); task-specific documents are
listed in the [documentation guide](docs/README.md). The repository skill
[$diffractscout-cif-reference](.agents/skills/diffractscout-cif-reference/SKILL.md)
handles local CIF peak-table exports. Load skills when their workflow applies,
preserve existing user changes, and continue through appropriate verification
when implementation has been requested. A read-only review request remains
read-only.

## Release process

The maintainer updates the changelog and version, runs the complete tests, analytic benchmark, demo, readiness audit, and package validation, creates an annotated Git tag, publishes release notes, and archives the tagged source with Zenodo or an equivalent repository. See `docs/RELEASE.md`.
