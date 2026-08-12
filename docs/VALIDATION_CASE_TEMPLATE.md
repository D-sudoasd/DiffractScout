# Scientific validation case template

Copy this file for each independent comparison. Store small, openly licensed
inputs in the repository; archive larger inputs and outputs in a stable data
repository and record checksums here.

## Identity

- Case title:
- Validation date:
- DiffractScout version and commit:
- Validator(s) and affiliation, with consent:
- Independent reviewer:
- Related public issue or pull request:

## Scientific question

State the exact numerical or workflow claim under test. Include the expected
applicability and the conditions under which the result would not be valid.

## Inputs and provenance

| Item | Source and license | Version or identifier | SHA-256 | Notes |
|---|---|---|---|---|
| CIF or structure |  |  |  |  |
| Elastic tensor |  |  |  |  |
| Reference result |  |  |  |  |

Do not include restricted, proprietary, or unpublished data without permission.

## Conventions and settings

- radiation definition, wavelength or energy:
- angular interval and units:
- CIF cell setting and space group:
- structure-factor and occupancy convention:
- Lorentz–polarization handling:
- elastic Voigt order and engineering-shear convention:
- tensor coordinate frame and any rotation matrix:
- reference software, version, and command:

## Predeclared acceptance criteria

Define absolute and relative tolerances before running the comparison. State
the rationale for each tolerance and distinguish exact selection rules from
floating-point comparisons.

## Results

| Quantity | DiffractScout | Independent reference | Difference | Tolerance | Pass/Fail |
|---|---:|---:|---:|---:|:---:|
|  |  |  |  |  |  |

Attach machine-readable results and logs. Record every discrepancy, including
those within tolerance.

## Interpretation

Classify differences as implementation defect, convention difference, model
scope, input mismatch, reference uncertainty, or unresolved. Provide evidence
for the classification.

## Resolution and manuscript relevance

- code or documentation change:
- regression test added:
- release containing the resolution:
- precise manuscript claim supported:
- remaining limitation: