# Roadmap

The roadmap lists evidence-driven work planned before the first JOSS
submission. Dates are tied to the actual public-repository date; completed work
is moved to the changelog.

## Completed public baseline work

- Public repository created on 12 August 2026 with CI on supported Python
  versions and operating systems.
- Maintain the packaged analytic benchmark suite and archive its output for
  every release candidate.

## Submission-critical work

- Complete and publish the v0.4.0 release baseline after local and remote
  acceptance; do not move the existing v0.3.0 tag.
- Add at least one openly reproducible real-material workflow with licensed
  inputs, fixed acceptance criteria, and independent diffraction comparison.
- Add an independent directional-elasticity comparison with explicit tensor
  basis and coordinate transformation.
- Obtain documented external use, review, or contribution through public
  issues or pull requests.
- Publish versioned releases throughout the public-development period. After
  successful JOSS review, archive the final release and connect its software
  DOI to `CITATION.cff`, the bibliography, GitHub Release, and review issue.
- Run the Open Journals draft build and complete a line-by-line claim and
  citation audit before submission.
- Submit no earlier than 15 February 2027 and only when the strict submission
  gate passes.

## Candidate enhancements

- Provider-independent adapters for additional open structure databases when
  their licenses and APIs permit reproducible retrieval.
- Explicit user-supplied rotation matrices for elastic tensors whose coordinate
  frame differs from the CIF Cartesian basis.
- Optional export schemas for workflow engines and institutional data
  repositories.
- Accessibility and localization improvements for the desktop interface.
- Split desktop view/layout and controller/worker responsibilities after real
  user feedback establishes a safe seam; keep pipeline behavior and public
  entry points compatible.

## Out of scope for the JOSS submission

- automated experimental phase identification;
- Rietveld, Le Bail, or Pawley refinement;
- detector integration or instrument calibration;
- quantitative phase analysis;
- automatic extraction of numerical tensors from literature;
- inferred experimental validity from database or synthetic data alone.

Requests that cross these boundaries require a separate scientific design and
validation record.
