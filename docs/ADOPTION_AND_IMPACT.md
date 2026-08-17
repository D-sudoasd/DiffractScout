# Adoption and research-impact evidence

The JOSS manuscript may state only claims supported by traceable records. The
machine-readable index is `docs/evidence/impact_evidence.json`; this document
defines the evidence standard and the claim ledger used during final editing.

## Evidence categories

### Research use case

A use case should identify a scientific question, exact software version,
input provenance and license, settings, outputs, how the output affected a
research decision, and the applicable limitations. A usage statement without
an inspectable workflow supports awareness, not scientific impact.

### Independent validation

An independent comparison should use an analytic result, accepted standard,
or separately implemented software path. Acceptance criteria must be fixed
before the result is inspected. Record versions, conventions, units, absolute
and relative differences, and unresolved discrepancies.

### External engagement

Suitable records include an external issue, pull request, code review,
validation report, tutorial use, or documented user feedback. Attribution
requires consent. GitHub stars, repository views, and download counts may be
reported as reach metrics only; they do not establish scientific impact.

### Archived release

The entry must link a Git tag and an immutable archive DOI or equivalent
persistent identifier. The archived source must match the submission commit.
For JOSS, this record is completed after successful review when the editor asks
for the final tagged release and software archive. It is a `publication`-stage
gate, not a reason to mislabel an ordinary pre-submission GitHub Release as an
immutable archive.

## Claim ledger

Complete this table only as evidence becomes available.

| Proposed manuscript claim | Required evidence | Public record | Status |
|---|---|---|---|
| The software supports a reproducible candidate-to-diffraction workflow | versioned real-material case and verified result bundle | pending | not yet claimable |
| Indexed reflection geometry agrees with an independent implementation | comparison report with predeclared tolerance | pending | not yet claimable |
| Directional elastic output agrees with an independent tensor calculation | tensor, frame, rotation, equations, numerical comparison | pending | not yet claimable |
| Researchers outside the author's development environment can install and use the software | external issue/PR or archived user test | pending | not yet claimable |
| The software has contributed to a research decision, dataset, presentation, preprint, or paper | versioned workflow plus cited output | pending | not yet claimable |

Synthetic analytic benchmarks support correctness of declared contracts. They
do not support claims of experimental validity, adoption, productivity gain,
or research impact.
