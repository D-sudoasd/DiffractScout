# Validation strategy

## Automated suite

The default test suite is offline and deterministic:

```bash
pytest -q
```

It verifies:

- alloy/formula/Materials Project ID parsing and subsystem enumeration;
- CIF block selection, cell parsing, space group and symmetry expansion;
- FCC systematic absences and reflection-family multiplicities;
- the analytic monoatomic-FCC structure factor $|F_{111}|^2=(4f_{\mathrm{Al}})^2$, including
  Gemmi's crystallographic-occupancy conversion for a special-position site;
- Bragg geometry, $q=2\pi/d$, intensity normalization and profile normalization;
- 6×6 tensor rejection, symmetrization and inversion;
- direction-independent $E=110$ GPa for a deliberately isotropic cubic synthetic tensor;
- candidate deduplication and deterministic ranking;
- complete discovery → download → CIF validation → diffraction → export using an offline provider;
- workbook sheet creation;
- SHA-256 bundle verification and tamper detection;
- refusal to overwrite unrelated user directories.

## Synthetic reference fixture

The offline demo uses:

- a synthetic `Fm-3m` cell with $a=4$ Å and one aluminium site in the asymmetric unit;
- a synthetic cubic tensor with $C_{11}=200$, $C_{12}=120$ and $C_{44}=40$ GPa.

The tensor satisfies the isotropic relation $C_{44}=(C_{11}-C_{12})/2$, yielding $E=110$ GPa for every direction. These values are constructed for verification and are labeled `synthetic_test_fixture`; they are not experimental aluminium properties.

Run the public smoke test:

```bash
diffractscout demo -o outputs/demo
diffractscout verify outputs/demo
```

Expected first five families in the 5–100° Cu Kα window:

```text
(111), (200), (220), (311), (222)
```

The forbidden FCC families `(100)` and `(110)` must be absent.

## Packaging validation

Before release:

```bash
python -m compileall -q src
python -m pip install -e ".[test]"
pytest -q
python -m pip wheel . --no-deps -w dist
```

A release candidate must also be installed into a clean environment and the offline demo must pass from the installed command.

## Validation still required before JOSS submission

Automated numerical tests establish defined software contracts. They do not establish experimental validity. The submission record should add:

1. comparison of a representative set of CIF peak positions and relative intensities against an independent crystallography package;
2. at least one real synchrotron or laboratory XRD planning case with preserved input and expected output;
3. an elastic-tensor case checked against an independent tensor-analysis package or an analytic crystal class;
4. documented use by the author's research workflow and preferably an external user group;
5. issue or pull-request records showing feedback-driven refinement.

Results from those studies should be placed in a versioned `validation_cases/` directory or a separately archived reproducibility repository.
