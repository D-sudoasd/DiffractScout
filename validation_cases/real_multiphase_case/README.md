# Real multiphase-alloy case intake

Status: **awaiting author-supplied research material; not evidence yet**.

This directory reserves the submission-critical real-material case. Do not add
it to `docs/evidence/impact_evidence.json` until every required item below is
complete and publicly auditable.

## Required author input

- Material or alloy name:
- Local absolute path or public source URL:
- Research decision actually supported by the workflow:
- Permission or license to redistribute the input:
- Any experimental or unpublished material that must remain excluded:

## Required frozen record

- DiffractScout version and commit:
- Retrieval date, provider query, provider/library versions, and candidate limits:
- Radiation, angular interval, profile, elasticity, and export settings:
- Selected CIF identifiers, source URLs, licenses, and SHA-256 hashes:
- Frozen CIF files when redistribution is permitted; otherwise a lawful retrieval procedure:
- Candidate table, selected-structure list, diagnostics, result summary, manifest, and bundle hash:
- Exact research decision and the limits of that decision:

Online discovery may change as external databases evolve. The scientific
comparison must therefore run from the frozen, hashed CIF set; the online query
is provenance for candidate discovery, not a deterministic numeric fixture.

## Independent diffraction protocol

Before inspecting DiffractScout output, copy
`docs/VALIDATION_CASE_TEMPLATE.md` into this directory and declare:

- independent software and exact version;
- identical CIF, wavelength, and angular interval;
- exact allowed/forbidden reflection expectations;
- tolerances for `d_spacing_A` and `two_theta_deg`, with rationale;
- the normalized ratio or top-N comparison, if intensity ranking is assessed.

Absolute Gemmi and pymatgen intensities are not required to be equal. All
differences, including those within tolerance, must be retained.

## Claim boundary

This case may support candidate screening, theoretical peak selection,
experimental-window planning, or interpretation only when that use actually
occurred. It must not describe a database candidate as an experimentally
confirmed phase, and it must not claim refinement or quantitative phase
analysis.
