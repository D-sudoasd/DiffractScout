# JOSS evidence ledger

`impact_evidence.json` is the machine-readable index used by
`scripts/joss_readiness.py`. Add an entry only after the underlying record is
publicly accessible or retained in a stable institutional repository.

Each entry should contain, where applicable:

- `date`: ISO date;
- `title`: concise description;
- `url`: public issue, pull request, release, DOI, dataset, protocol, preprint,
  presentation, or archived report;
- `software_version`: exact DiffractScout version or commit;
- `people`: contributors or validators who consent to attribution;
- `claim_supported`: the precise manuscript statement supported by the record;
- `validation_type`: required for independent validations; use `diffraction`
  or `elasticity` so both submission gates can be audited separately;
- `notes`: limitations, unresolved discrepancies, or access restrictions.

Completed research-use and independent-validation entries must also bind to a
version-controlled report under `validation_cases/` through `report_path` and
`report_sha256`. Research-use records require frozen input and result-manifest
hashes, a lawful input license, the actual research decision, and limitations.
Diffraction validations require the reference implementation/version,
predeclared tolerance basis, frozen input hash, radiation and scan range;
elasticity validations additionally require tensor source/frame, Voigt
convention and `[100]`, `[110]`, `[111]` directions. External engagement must
record the tested artifact, commands, verification result, concrete outcome,
limitations, and whether attribution consent was obtained. Consent must be true
when `people` names anyone; an unattributed public record may explicitly use
false. A merely non-empty array cannot satisfy the submission gate.

`public_development_activity` records only meaningful, publicly visible work in
the canonical GitHub repository: commits, issues, pull requests, or releases
that document real maintenance, validation, dependency, documentation, or user
work. The submission gate counts distinct calendar months from these URLs. It
does not treat local commit timestamps, empty issues, scheduled CI, stars, or
download counts as proof of distributed public development.

Evidence must reflect real activity. Empty arrays are preferable to inferred,
private, duplicated, or retrospective records. Personal correspondence may be
summarized only with the other person's permission and should be replaced by a
public issue or archived validation report when possible.

`submission_metadata` contains explicit human confirmations and public URLs for
the selected remote CI run and official Open Journals paper build, plus the
exact 40-character commit tested by each. Both commits must equal the current
submission commit. Leave these
values false or empty until the submitting author has checked them. After the
official build and page review, record the SHA-256 values reported by readiness
for the paper inputs and PDF; this prevents a stale tracked PDF from passing in
a fresh checkout. An archived
software release DOI belongs to the post-review `publication` stage, not the
initial `submission` stage.
