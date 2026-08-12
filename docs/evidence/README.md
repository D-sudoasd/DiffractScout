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
- `notes`: limitations, unresolved discrepancies, or access restrictions.

Evidence must reflect real activity. Empty arrays are preferable to inferred,
private, duplicated, or retrospective records. Personal correspondence may be
summarized only with the other person's permission and should be replaced by a
public issue or archived validation report when possible.