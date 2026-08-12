# Governance

DiffractScout is maintained as an open research-software project. Scientific
correctness, traceable data handling, and reproducible review take precedence
over feature volume.

## Roles

- **Maintainer:** Delun Gong. The maintainer manages releases, security
  reports, repository administration, and final merge decisions.
- **Contributors:** anyone submitting issues, validation evidence,
  documentation, tests, or code under the repository license and contribution
  rules.
- **Scientific reviewers:** contributors with relevant diffraction,
  crystallography, elasticity, or research-software expertise who review
  changes to numerical definitions or scientific boundaries.

Roles are based on documented work. They do not imply employment, affiliation,
or authorship on a paper.

## Decision process

Routine fixes may be merged after automated checks and maintainer review.
Changes to equations, units, tensor conventions, coordinate transforms,
selection rules, provider semantics, or machine-readable schemas require:

1. a public issue describing the scientific question;
2. a test or independent comparison with an acceptance criterion stated before
   the result is inspected;
3. an update to `docs/SCIENTIFIC_CONTRACTS.md` when behavior changes;
4. review by at least one person with relevant domain knowledge when available;
5. a changelog entry and migration note for user-visible changes.

Unresolved scientific disagreement is recorded in the issue and release notes.
The software retains missing or disputed values instead of selecting an
unsupported result.

## Authorship and credit

Software contributions are credited in release notes and, with consent, in
`AUTHORS.md`. JOSS authorship follows substantive scholarly contribution and
the journal's authorship requirements. Filing an issue, testing one build, or
using the software does not automatically establish paper authorship.

## Conflicts of interest

Reviewers should disclose relationships that could affect judgment. The
maintainer may request another reviewer for a disputed scientific change.

## Continuity

If the maintainer cannot continue, stewardship may be transferred to a
qualified contributor or research-software organization. A transfer must be
announced publicly, preserve the license and history, and update citation and
security contacts.