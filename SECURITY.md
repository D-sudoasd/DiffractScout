# Security policy

## Supported versions

Security fixes are applied to the latest released minor version. Pre-release development branches may change without compatibility guarantees.

## Reporting

Report suspected vulnerabilities privately to `dlgong17s@imr.ac.cn`. Include the affected version, operating system, reproduction steps, impact, and any proposed mitigation. Do not open a public issue before a fix or disclosure plan is agreed.

## Sensitive data boundaries

- Materials Project API keys are read from command arguments or `MP_API_KEY` and are not written to result bundles.
- DiffractScout does not upload local CIF files or result bundles.
- Output directories are not overwritten unless they contain a recognized DiffractScout manifest and the user explicitly enables overwrite.
- Manifest verification checks file integrity; it does not provide cryptographic authenticity or digital signatures.
