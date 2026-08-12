# Roadmap

The roadmap lists evidence-driven work planned before the first JOSS
submission. Dates are tied to the actual public-repository date; completed work
is moved to the changelog.

## Submission-critical work

- Publish the repository and establish continuous integration on all supported
  Python versions and operating systems.
- Maintain the packaged analytic benchmark suite and archive its output for
  every release candidate.
- Add at least one openly reproducible real-material workflow with licensed
  inputs, fixed acceptance criteria, and independent diffraction comparison.
- Add an independent directional-elasticity comparison with explicit tensor
  basis and coordinate transformation.
- Obtain documented external use, review, or contribution through public
  issues or pull requests.
- Publish versioned releases, archive the submission release with a DOI, and
  connect the DOI to `CITATION.cff` and the manuscript.
- Run the Open Journals draft build and complete a line-by-line claim and
  citation audit before submission.

## Candidate enhancements

- Provider-independent adapters for additional open structure databases when
  their licenses and APIs permit reproducible retrieval.
- Explicit user-supplied rotation matrices for elastic tensors whose coordinate
  frame differs from the CIF Cartesian basis.
- Optional export schemas for workflow engines and institutional data
  repositories.
- Accessibility and localization improvements for the desktop interface.

## Out of scope for the JOSS submission

- automated experimental phase identification;
- Rietveld, Le Bail, or Pawley refinement;
- detector integration or instrument calibration;
- quantitative phase analysis;
- automatic extraction of numerical tensors from literature;
- inferred experimental validity from database or synthetic data alone.

Requests that cross these boundaries require a separate scientific design and
validation record.