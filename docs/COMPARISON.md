# State of the field and build-vs-contribute rationale

DiffractScout uses established libraries and services while addressing a workflow boundary that they do not expose as one traceable research object.

| Software/service | Primary role | Relationship to DiffractScout |
|---|---|---|
| Materials Project | Computed structures and properties | Optional source provider. DiffractScout records query context, downloads exact source artifacts and carries them into a reproducible diffraction bundle. |
| mp-api / pymatgen | Materials Project client and general materials-analysis objects | Optional acquisition layer. DiffractScout does not replace their data models; it adds candidate deduplication, source-to-output traceability, fail-closed property pairing and a stable result schema. |
| Gemmi | CIF and crystallographic computation library | Offline crystallographic engine for CIF parsing, space-group operations, Miller enumeration and X-ray structure factors. |
| spglib | Crystal-symmetry search | Optional independent cross-check of the CIF-declared space group. |
| GSAS-II and related refinement suites | Broad experimental diffraction reduction and refinement | Appropriate for calibration, integration, fitting and structure refinement. DiffractScout stops at candidate references and does not duplicate experimental refinement. |
| PhaseScout | Candidate phase and CIF/Cij acquisition | Source project whose discovery and provenance behavior has been restructured behind a provider interface. |
| CIF2Peaks | Batch CIF-to-peak tables and elasticity coupling | Source project whose diffraction, elasticity and export behavior has been incorporated into the unified data model. |

## Why a separate package is justified

Contributing individual features to a general crystallography or materials library would not create the required end-to-end contract. The research problem is the preservation of identity and assumptions across several independently valid operations:

1. interpretation of an alloy or chemical-system request;
2. enumeration and deduplication of database candidates;
3. preservation of database record identity and database version;
4. download of a precise CIF setting and optional tensor;
5. validation of the structure and tensor relationship;
6. calculation of indexed theoretical reference lines;
7. export of both LP and no-LP channels;
8. production of one verifiable bundle for later experimental use.

Gemmi, pymatgen, mp-api and spglib remain the appropriate upstream locations for general crystallographic, data-client and symmetry algorithms. DiffractScout contributes workflow semantics, provenance enforcement, cross-domain coupling, output schemas and safety boundaries. Bugs or broadly useful algorithms discovered in upstream dependencies should still be reported or contributed upstream.

## Scope distinction

DiffractScout should be compared with candidate-screening and reference-generation workflows. Performance claims against Rietveld or integration packages would be inappropriate because those packages solve experimental inverse problems outside DiffractScout's scope.
