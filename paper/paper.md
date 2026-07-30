---
title: 'DiffractScout: Provenance-first phase scouting and indexed powder diffraction references'
tags:
  - Python
  - materials science
  - powder diffraction
  - crystallography
  - phase screening
  - elasticity
authors:
  - name: Delun Gong
    affiliation: 1
affiliations:
  - name: Institute of Metal Research, Chinese Academy of Sciences, Shenyang 110016, China
    index: 1
date: 30 July 2026
bibliography: paper.bib
---

# Summary

`DiffractScout` is an open-source Python package that connects candidate-phase discovery to traceable theoretical powder X-ray diffraction references. A user can supply an alloy grade, a chemical system, Materials Project identifiers, or local Crystallographic Information Files (CIFs). The software expands chemical subsystems when required, normalizes and ranks candidate records, downloads conventional crystal structures and optional computed elastic tensors, validates each source artifact, calculates indexed powder reflections, and writes one self-contained evidence bundle. The reflection table contains $hkl$, $d$, $2\theta$, $q$, reciprocal spacing, multiplicity, X-ray structure-factor terms, explicit Lorentz-polarization channels, and an optional Young's modulus along the reciprocal-lattice normal of each reflection. Every bundle includes calculation settings, source metadata, software versions, input hashes, warnings, CSV and spreadsheet tables, and a SHA-256 inventory. The package provides a command-line interface, a Python API, a small desktop interface, and a fully offline synthetic verification workflow.

# Statement of need

Candidate-phase assessment in alloy and diffraction research often spans several disconnected operations. Researchers translate a grade name into an element set, enumerate binary and higher-order subsystems, search computed-materials databases, download CIF records, inspect space-group and stability metadata, generate theoretical peak positions, locate elastic constants, and transfer results into spreadsheets or plotting programs. The individual calculations are widely available, yet ad hoc pipelines frequently lose the relationship between the database record, the exact CIF setting, the tensor basis, the radiation definition, and the exported table. This can lead to duplicated candidates, untraceable values, coordinate-frame errors, or theoretical intensities being compared with experimental peak areas under inconsistent corrections.

`DiffractScout` addresses this workflow-level problem for materials researchers who need auditable candidate references before experimental phase identification, refinement, or mechanical interpretation. It preserves the CIF standard [@hall1991], treats Materials Project structures and elastic tensors as computed records [@jain2013], and keeps missing properties explicit. A database candidate is not reported as an experimentally confirmed phase. A missing elastic tensor is not replaced by a value inferred from literature text. Continuous profiles are labeled as display products, while the indexed line table remains the primary scientific output.

# State of the field

The Materials Project provides open access to computed structures and properties [@jain2013], and `mp-api`/`pymatgen` supply general data-access and materials-analysis objects [@ong2013]. Gemmi provides efficient CIF and crystallographic operations [@wojdyr2022], while spglib provides independent crystal-symmetry identification [@togo2024]. Comprehensive diffraction packages such as GSAS-II address experimental data reduction, structure solution, and refinement [@toby2013], and pyFAI addresses detector geometry and azimuthal integration [@ashiotis2015]. These packages serve as upstream dependencies or downstream analysis environments and lie outside the replacement scope.

The distinct contribution of `DiffractScout` is the contract across these domains: composition interpretation, subsystem queries, candidate deduplication, source acquisition, CIF identity, optional tensor pairing, theoretical reflection calculation, and export are represented in one versioned data flow. Contributing a peak-table writer to a general materials library would not establish this cross-stage provenance contract. Adding database search to a refinement package would mix candidate-reference generation with experimental inverse analysis. `DiffractScout` therefore uses established libraries for crystallographic and database algorithms and concentrates its own implementation on workflow semantics, validation gates, traceable coupling, safety boundaries, and reusable output schemas.

# Software design

The package separates provider access, domain records, numerical calculation, orchestration, and export. A provider protocol returns normalized candidate records and source artifacts. The optional Materials Project implementation records query metadata and requests conventional unit cells. Local CIF analysis remains available in the base installation without a database client. This separation permits deterministic offline testing and allows other structure databases to be added without modifying the diffraction engine.

Gemmi is used to select a structure-bearing CIF block, expand unit-cell sites, interpret space-group operations, reject systematically absent reflections, enumerate unique Miller indices, and calculate X-ray structure factors. The software reports both $m|F|^2$ and a channel multiplied by an explicit unpolarized Lorentz-polarization factor. A pseudo-Voigt curve is generated only for visualization; its width and mixing parameter are stored in provenance. No instrument response, background, preferred orientation, absorption, microstructure broadening, or experimental phase fraction is inferred.

Elasticity is represented by a numerical $6\times6$ stiffness matrix in GPa, a source record, a nature-of-data label, and a coordinate-frame declaration. The matrix is checked for finiteness, symmetry, invertibility, conditioning, and positive definiteness. Under engineering-shear Voigt convention, the directional modulus is calculated from $E(n)=[q(n)^T S q(n)]^{-1}$, where $S=C^{-1}$ and the direction $n$ is the orthogonalized reciprocal-lattice normal of `hkl`. For Materials Project downloads, automatic coupling uses the raw/POSCAR-format tensor documented as consistent with the conventional-standard CIF [@materialsproject_elasticity]. IEEE-format tensors are retained in provenance; an IEEE-only record is marked `frame_transform_required` and does not produce a directional modulus without an explicit rotation into the CIF Cartesian frame.

![DiffractScout joins candidate discovery, source acquisition, structural validation, theoretical diffraction, optional hkl-normal elasticity, and traceable export in one data flow.](fig_workflow.png){#fig:workflow width="100%"}

The output directory is treated as an immutable research bundle. Local inputs are copied and left unmodified. Existing unrelated directories are not overwritten. Each generated file is hashed, and an independent `verify` command detects missing or modified files. Large database downloads require explicit authorization above a configurable threshold.

# Research impact statement

The current pre-submission evidence is a reproducible validation package. The automated suite checks analytic FCC $d$ spacings and systematic absences, reflection-family multiplicities, the identity $q=2\pi/d$, a direction-independent $E=110$ GPa for a deliberately isotropic synthetic tensor, complete offline discovery-to-export execution, workbook generation, overwrite protection, and manifest tamper detection. These tests demonstrate the defined numerical and provenance contracts without presenting synthetic values as material-property data.

Before formal submission, this section must be updated with archived evidence of real research use, such as a representative alloy candidate-screening case linked to an experimental diffraction workflow, independent comparisons for diffraction and elasticity, and documented use or feedback beyond the initial developer. The repository's readiness checklist tracks these requirements so that aspirational statements are not substituted for impact evidence.

# AI usage disclosure

OpenAI GPT-5.6 Pro assisted the initial integration architecture, code and test scaffolding, documentation drafting, and preparation of this manuscript draft. The source repositories were inspected as read-only inputs, and their MIT license notices were retained. Before submission, the human author must review and validate every generated or modified component, including numerical definitions, tests, references, source attribution, licensing, documentation, and manuscript claims, and must confirm that primary scientific and architectural decisions reflect human judgment.

# Acknowledgements

Funding, facility acknowledgements, contributors, external validation partners, and the software archive DOI require author confirmation before submission.

# References
