---
title: 'DiffractScout: An auditable Python workflow for generating powder diffraction references'
tags:
  - Python
  - materials science
  - powder X-ray diffraction
  - crystallography
  - phase screening
  - research software
authors:
  - name: Delun Gong
    orcid: 0000-0001-7877-7707
    corresponding: true
    affiliation: '1'
affiliations:
  - name: Institute of Metal Research, Chinese Academy of Sciences, Shenyang 110016, China
    index: 1
date: 26 September 2026
bibliography: paper.bib
---

# Summary

Researchers compare measured powder X-ray diffraction (PXRD) patterns with reflections calculated from candidate crystal structures. Preparing these references requires the structure setting, radiation, and calculation parameters to remain linked. DiffractScout is an open-source Python package that converts composition queries or local Crystallographic Information Files (CIFs) into indexed theoretical reflections and display profiles [@diffractscout_software]. Its command-line, Python, and desktop interfaces write source structures, settings, data, diagnostics, and tables to a result bundle with a verifiable manifest. The formatted workbook presents an overview and can be previewed before saving. DiffractScout supports experimental planning and interpretation; it does not identify phases in measured patterns or refine experimental data.

# Statement of need

Powder-diffraction screening links candidate compositions and structures to expected reflection positions and intensities. Preparing references spans alloy parsing, database queries, CIF validation, diffraction calculations, optional tensor matching, and spreadsheet transfer. Across separate tools, candidate identifiers, structure settings, radiation, warnings, and calculation parameters can become detached from the final table.

DiffractScout connects these steps for materials researchers and students preparing references before or alongside experiments. Runs start from a composition, provider ID, or local CIF; the software records source structures and data interpretation, then exports machine-readable tables and a reviewable workbook in one bundle. Local-CIF processing needs no database credentials. This workflow makes theoretical references repeatable while leaving experimental interpretation to the researcher.

# State of the field

The Materials Project provides computed structures and properties [@jain2013], and pymatgen supplies materials-analysis objects and calculations [@ong2013]. Gemmi parses CIFs and performs crystallographic operations and structure-factor calculations [@wojdyr2022]; spglib offers an independent symmetry search [@togo2024]. Dans_Diffraction simulates diffraction from supplied structures [@porter2023], and Elasticipy analyzes linear elasticity and tensors [@depriester2025]. For measured data, GSAS-II supports reduction and refinement [@toby2013], while pyFAI provides detector calibration and azimuthal integration [@ashiotis2015].

DiffractScout introduces no new diffraction or elasticity algorithm. Instead, it adds an application layer that links database or local-CIF inputs, candidate identities, user-selected settings, calculations, diagnostics, and exports in one result bundle—relations that extend beyond any one numerical library. It restructures workflow components from PhaseScout and CIF2Peaks [@phasescout_2026; @cif2peaks_2026] around shared records and provenance. Database access is optional, so local-CIF analysis runs offline.

# Software design

A provider supplies normalized candidate records and their source artifacts. The Materials Project adapter records query context and source identifiers; the local-CIF path requires no network service. Candidates are deduplicated before download. Each structure record preserves the CIF hash, selected data block, cell, space-group resolution, occupancy state, and diagnostics. Conflicting space-group declarations and partial occupancies remain visible for review rather than being silently repaired [@hall1991].

The diffraction engine uses Gemmi to enumerate symmetry-related reflection families, apply systematic-absence rules, and calculate X-ray structure factors. Results include representative Miller indices, interplanar spacing, scattering-vector magnitude, multiplicity, and separately identified intensity channels with and without the stated Lorentz–polarization correction. A Gaussian, Lorentzian, or pseudo-Voigt profile is generated for display; it is not an instrument-response fit. Configured limits on profile-grid points and reciprocal-space candidate counts are checked before allocation.

Directional Young's moduli can be attached when an elastic tensor is uniquely associated with the CIF and its coordinate frame is usable. The Materials Project's elastic constants are computed data, not experimental measurements [@materialsproject_elasticity]. DiffractScout validates the matrix, unit, conditioning, and positive definiteness before evaluation along a reflection-plane normal. When a downloaded tensor lacks a verified transformation into the CIF Cartesian frame, the software retains its provenance and emits a frame-transformation status without a directional value. This fail-closed policy avoids making a numerically plausible but unsupported tensor-to-structure pairing.

The command-line and desktop interfaces call the same analysis pipeline. The command-line interface accepts reusable parameter presets and can inspect and verify an existing result bundle without rerunning the analysis. The desktop application offers separate result preview, workbook saving, and result-folder actions; versioned parameter presets exclude credentials and file paths. The Excel exporter formats existing result values rather than recalculating them. It adds an overview, readable number formats, filters, frozen phase-identity columns, and grouped technical fields while preserving the corresponding tabular records. CSV and JSON outputs remain available for scripted use.

Each run is first written to a staging directory. Before publication to the requested output path, a verifier checks the manifest's SHA-256 digests and file sizes, path safety, symbolic links, and unlisted files. Replacing an existing result requires explicit authorization and verification of that result. This design makes the completed directory a portable evidence bundle while keeping recovery behavior explicit.

An offline analytic benchmark tests simple-cubic, body-centered cubic, face-centered cubic, and NaCl selection rules, reflection geometry, structure factors, and cubic elasticity against closed-form expectations. A separate pymatgen XRDCalculator comparison [@ong2013] matched 40 d-spacing groups from four synthetic CIFs using Cu Kα (1.5406 Å) over 5–120° 2θ. Every group met the specified spacing ($10^{-6}$ Å) and angle ($10^{-5}\,^{\circ}$) tolerances, and all tested allowed and forbidden reflection rules passed. Directional moduli along [100], [110], and [111] for a synthetic cubic tensor passed the defined absolute and relative tolerances in the pymatgen compliance-tensor comparison [@ong2013]. The automated suite checks analysis and export contracts; continuous integration runs it on Linux for Python 3.10–3.13 and selected checks on Windows and macOS. These comparisons are reproducible without a database service.

![DiffractScout workflow from candidate request or local CIFs to a verified result bundle. Source identity, assumptions, diagnostics, and missing-data states are carried across the pipeline.](fig_workflow.png){#fig:workflow width="95%"}

![Analytic offline benchmark for the synthetic FCC fixture. The figure shows allowed reflection families and the selected geometry and bundle-integrity checks. The fixture is for software verification, not a measured material.](fig_validation.png){#fig:validation width="95%"}

# Research impact statement

The developer reports using DiffractScout in published materials-science research. Each result bundle preserves candidate identity, source structures, calculation settings, diagnostics, and file checksums, making calculated references traceable.

# AI usage disclosure

OpenAI GPT-5.6 Pro assisted earlier repository development, testing, documentation, figure production, and manuscript drafting from 30 July to 12 August 2026. In this revision, OpenAI Codex GPT-6 and cooperating assistant agents supported code changes, test scaffolding and review, documentation, citation discovery, manuscript restructuring, and automated verification. Software claims were checked against project source and scientific contracts, references against publisher or upstream records, and automated tests and the analytic benchmark were run. Human author review of the AI-assisted contributions remains pending.

# Acknowledgements

The author acknowledges the developers and maintainers of the open-source software and data services cited above.

# References
