# Validation-case registry

This directory is reserved for compact, redistributable validation cases that
support scientific claims made in releases or the JOSS paper. Generated output
bundles should normally be attached to GitHub releases or deposited in a
persistent archive; the repository stores the inputs, acceptance criteria,
commands, summaries, and archive links.

A validation case must include:

1. a stable case identifier and exact DiffractScout version or commit;
2. lawful input provenance and redistribution terms;
3. predeclared quantities, units, conventions, and tolerances;
4. the exact command or Python call;
5. an independent reference method or analytic result;
6. a result summary including unresolved discrepancies;
7. hashes or a link to the archived result bundle;
8. a statement of what the case does not validate.

Use `docs/VALIDATION_CASE_TEMPLATE.md` for real-material or independent-package
comparisons. Public records are indexed only after completion in
`docs/evidence/impact_evidence.json`.

Available numerical cases:

- [Analytic reference suite](analytic_reference_v1/README.md): closed-form
  crystallographic and cubic-elasticity expectations.
- [Independent pymatgen comparison](independent_engines/README.md): the same
  synthetic structures evaluated by separate diffraction and tensor
  implementations, with versioned numerical reports.

`real_multiphase_case/README.md` is an intake scaffold. Its presence is not
research-use evidence and its pending fields must never be cited in the paper.
