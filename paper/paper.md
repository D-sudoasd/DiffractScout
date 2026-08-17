---
title: 'DiffractScout: An auditable workflow from candidate phases to indexed powder diffraction and elasticity references'
tags:
  - Python
  - materials science
  - powder diffraction
  - crystallography
  - phase screening
  - elasticity
authors:
  - name: Delun Gong
    orcid: 0000-0001-7877-7707
    corresponding: true
    affiliation: '1'
affiliations:
  - name: Institute of Metal Research, Chinese Academy of Sciences, Shenyang 110016, China
    index: 1
date: 12 August 2026
bibliography: paper.bib
---

# Summary

Materials researchers often need a trustworthy set of calculated powder-diffraction peaks before they can plan measurements or interpret an unfamiliar pattern. `DiffractScout` makes that preparatory workflow reproducible. From an alloy name, element set, database identifier, or local crystal-structure file, it can assemble candidate structures, check that they are usable, calculate indexed theoretical reflections, and, when compatible elastic data exist, attach the Young's modulus normal to each reflecting plane. Instead of returning an isolated spreadsheet, the software records the exact structures, calculation settings, data sources, warnings, software versions, and file hashes behind every result. It packages these records with tables, diagnostics, plots, and a verifiable manifest. `DiffractScout` is available as a command-line tool, Python API, and desktop application, with a deterministic offline example that reviewers can run without database credentials. It builds auditable theoretical references; it does not identify phases automatically or refine experimental diffraction data.

# Statement of need

Candidate-phase screening in alloy and diffraction research commonly spans several independent tools. A researcher may translate an engineering alloy name into an element set, enumerate chemical subsystems, query a computed-materials database, download CIF records, inspect stability and symmetry metadata, calculate theoretical peaks, locate an elastic tensor, and then transfer selected values into a spreadsheet. Each individual operation is well supported, yet the hand-offs can separate a result from the structure setting, query conditions, radiation definition, tensor basis, warnings, or software version that produced it. This creates practical risks: duplicated candidates, ambiguous CIF-to-tensor pairing, coordinate-frame errors in directional properties, service failures recorded as missing data, and theoretical intensities compared with experimental peak areas under incompatible corrections.

`DiffractScout` addresses this workflow-level problem for materials researchers, beamline users, and students who need auditable theoretical references before experimental phase identification or refinement. The package preserves CIF identity [@hall1991], labels Materials Project structures and elastic tensors as computed records [@jain2013], and carries missing or unusable quantities forward as explicit states. Its scientific scope is deliberately bounded. Database candidates are hypotheses for evaluation, not experimentally confirmed phases. The diffraction output is a kinematic theoretical reference and does not perform Rietveld, Le Bail, or Pawley refinement, quantitative phase analysis, instrument calibration, background modelling, or preferred-orientation correction. This boundary allows the software to support experimental planning and interpretation without presenting a reference-generation workflow as an experimental inverse solution.

# State of the field

The Materials Project provides computed structures and materials properties [@jain2013], and pymatgen supplies general materials-analysis objects and diffraction utilities [@ong2013]. Gemmi provides CIF handling, crystallographic symmetry operations, and structure-factor calculations [@wojdyr2022], while spglib provides an independent symmetry-search implementation [@togo2024]. `Dans_Diffraction` offers broad crystal-property and diffraction simulation capabilities from CIF files [@porter2023]. Elasticipy provides general linear-elasticity and tensor analysis, including directional properties [@depriester2025]. Experimental diffraction reduction and refinement are addressed by packages such as GSAS-II [@toby2013], and pyFAI specializes in detector geometry and azimuthal integration [@ashiotis2015].

`DiffractScout` uses these projects as data sources, numerical foundations, comparison tools, or downstream environments. Its contribution is the cross-stage contract that joins composition interpretation, subsystem queries, candidate deduplication, source acquisition, CIF identity, tensor pairing, theoretical reflection calculation, diagnostics, and export in one versioned research object. Direct diffraction simulators generally begin with a structure already selected by the user. Elasticity packages generally begin with a tensor whose coordinate basis is already known. Database clients return records without defining how a later diffraction table, directional modulus, and exported spreadsheet remain bound to the same cell setting. Refinement suites solve a different experimental problem.

General crystallographic, symmetry, database-client, and tensor algorithms remain in their established upstream projects. `DiffractScout` implements the workflow semantics that span those projects: fail-closed property pairing, explicit data states, stable output schemas, bounded numerical work, and non-destructive bundle creation. This separation provides a clear build-versus-contribute rationale while retaining upstream libraries for the domain algorithms they already implement well.

# Software design

The package separates source providers, typed domain records, numerical calculation, orchestration, and export (Figure 1). A provider protocol returns normalized candidate records and source artifacts. The optional Materials Project adapter records query context and requests conventional-standard unit cells. Local CIF analysis remains available without a database client or network connection. This architecture keeps the offline scientific core deterministic and allows additional structure providers to be added without changing the diffraction engine.

![DiffractScout converts a composition request or local CIF collection into a verified evidence bundle. Each stage preserves identity, source, assumptions, warnings, and missing-data states.](fig_workflow.png){#fig:workflow width="100%"}

CIF validation requires finite positive cell geometry and atomic sites. The software records whether a space-group assignment came from an explicit symbol, an International Tables number, Gemmi inference, or a warned fallback; spglib can provide an independent cross-check. Gemmi expands unit-cell sites, evaluates systematic absences, enumerates unique Miller-index families, and calculates X-ray structure factors. A dedicated structure-factor copy receives Gemmi's crystallographic-occupancy conversion so that special-position multiplicity is not counted twice. The indexed table reports $hkl$, $d$, $2\theta$, $q=2\pi/d$, multiplicity, $|F|^2$, and separate intensity channels with and without the explicitly defined Lorentz-polarization factor. A pseudo-Voigt profile is generated for visualization only. Profile-grid size and a conservative reciprocal-space search estimate are checked before large allocations.

Elasticity records contain a finite $6\times6$ stiffness matrix in GPa, source identity, nature-of-data label, and coordinate-frame declaration. Matrices are checked for symmetry, invertibility, conditioning, and positive definiteness. Under the engineering-shear Voigt convention, the directional modulus is

$$
E(n)=\left[q(n)^T S q(n)\right]^{-1}, \qquad S=C^{-1},
$$

where $n$ is the reciprocal-lattice normal of the reflection. Automatic sidecar pairing requires a unique CIF or material identifier. For Materials Project downloads, directional coupling uses the raw/POSCAR-format tensor paired with the conventional-standard CIF [@materialsproject_elasticity]. IEEE-only records are retained with a `frame_transform_required` state and produce no directional modulus until a verified rotation is supplied.

The output directory is treated as a verifiable research bundle. A run writes into a sibling staging directory, generates all tables and metadata, creates a manifest, and verifies file hashes, byte sizes, safe paths, symbolic-link absence, and unlisted files before moving the bundle into place. Replacement of an existing bundle requires explicit authorization and a successful integrity check of the current bundle. A failed export or verification leaves the previous valid result untouched. Structured diagnostics preserve phase-specific failures while allowing independent phases to complete.

# Research impact statement

The repository provides executable evidence for the package's current scholarly significance and reviewer readiness. A packaged analytic suite performs 45 checks using simple-cubic, BCC, FCC, NaCl, and cubic-elasticity fixtures with closed-form selection rules, multiplicities, plane spacings, lattice structure factors, and directional moduli. The complete offline workflow uses a self-identifying synthetic $Fm\bar{3}m$ cell with $a=4$ Å and an isotropic cubic test tensor. For Cu K$\alpha$ radiation over $5$--$120^\circ$, it produces eight allowed reflection families, excludes the forbidden FCC $(100)$ and $(110)$ families, verifies $d$ spacings, multiplicities, $q=2\pi/d$, and $|F_{111}|^2=(4f_{\mathrm{Al}})^2$, and returns $E(hkl)=110$ GPa for every direction. It writes a 5751-point profile and a 12-artifact bundle protected by independent SHA-256 entries (Figure 2). The fixtures are explicitly labelled as synthetic and carry no experimental material-property claim.

![Offline verification output distributed with DiffractScout. (a) The indexed Cu K$\alpha$ powder profile for the synthetic FCC fixture, with all eight allowed reflection families labelled. (b) Selected invariants and bundle-integrity results checked by the automated suite.](fig_validation.png){#fig:validation width="100%"}

The pytest suite covers composition parsing, candidate selection, CIF and tensor validation, systematic absences, structure factors, intensity definitions, coordinate-frame boundaries, resource limits, transactional replacement, spreadsheet safety, and manifest tamper detection; its collected-test count is recorded by continuous integration rather than copied into the paper. CI targets Python 3.10--3.13, Windows, macOS, a Linux graphical-interface smoke test, wheel installation, and Open Journals draft compilation. These materials let reviewers reproduce the declared numerical and provenance contracts without database credentials. They do not establish experimental accuracy, realized research impact, or external adoption. The project therefore requires a public multiphase research-use case, independent diffraction and elasticity comparisons, and external installation or use evidence before submission. The final Research impact statement will include only claims indexed by the machine-readable public evidence ledger.

# AI usage disclosure

OpenAI GPT-5.6 Pro assisted integration planning, test scaffolding, documentation, figure production, and manuscript editing. The human author directed the scientific scope and retains responsibility for the architecture, numerical definitions, licensing, references, and manuscript claims. AI-assisted outputs were checked through source inspection, cited primary documentation, analytic fixtures, automated tests, bundle-integrity verification, and rendered-PDF review. Final submission requires the author's explicit confirmation of complete human review.

# Acknowledgements

The author acknowledges the maintainers and contributors of the Materials Project, pymatgen, Gemmi, spglib, GSAS-II, pyFAI, Dans_Diffraction, and Elasticipy projects, whose software and documentation support this workflow.

# References
