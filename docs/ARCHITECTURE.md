# Architecture

## Design objective

DiffractScout represents candidate discovery, source acquisition, structural validation, theoretical diffraction, optional elasticity, diagnostics, and export as one traceable pipeline. Every numerical output is connected to an input artifact, calculation setting, definition, software version, and integrity record.

## Layers

```text
CLI / Tk GUI / Python API
          │
          ▼
pipeline.py — orchestration, diagnostics, staged output, rollback
          │
   ┌──────┴─────────┐
   ▼                ▼
selection.py      providers/
subsystems        Materials Project adapter
ranking           provider protocol
validation        source acquisition status
   │                │
   └───────┬────────┘
           ▼
structure.py — CIF block, hash, cell, space group, occupancy, symmetry cross-check
           │
           ├──────────────► elasticity.py — sidecar identity, 6×6 validation, E(hkl normal)
           ▼
diffraction.py — absences, multiplicity, d/2θ/q/g, |F|², LP, resource guards, profile
           │
           ▼
exporters.py — CSV/XLSX/provenance/diagnostics/SHA-256 manifest
           │
           ▼
validation.py — strict independent bundle verification
```

The GUI contains no separate numerical implementation. It creates `AnalysisSettings` and `DiscoverySettings`, calls the pipeline API, and renders returned diagnostics.

## Provider boundary

The discovery layer depends on the `PhaseProvider` protocol. Materials Project is one optional implementation. A provider supplies:

- candidate records for one chemical subsystem or explicit provider IDs;
- structure and optional property artifacts for selected candidates;
- acquisition status and error semantics for each artifact;
- provider metadata, including database version when available.

The base package performs local CIF analysis without `mp-api` or pymatgen. The optional Materials Project adapter imports those dependencies only when requested. Tests use a deterministic offline provider to exercise discovery, download, analysis, export, and verification without a network call or API key.

## Unified data contracts

The source projects previously exchanged files through naming conventions. DiffractScout promotes relevant concepts into typed records and versioned output schemas:

- `CandidateRecord` stores provider identity, stability metadata, query subsystem, space group, structure tag, and source URL.
- `DownloadArtifact` separates CIF status from elastic-query status and preserves both errors.
- `StructureRecord` stores the exact CIF hash, selected data block, unit cell, resolved space group, occupancy state, diagnostics, and source metadata.
- `ElasticTensor` stores the 6×6 matrix, unit, source, data nature, coordinate frame, validation status, and original sidecar path.
- `ReflectionRecord` stores geometry, structure-factor terms, LP and no-LP channels, ranks, and optional directional modulus.
- `DiagnosticRecord` stores stage, item, severity, and message for failures that do not need to abort the whole batch.
- `manifest.json` stores a SHA-256 digest and byte size for every bundle file.

This separation permits independent testing and supports future providers or export formats without replacing the diffraction engine.

## Structural validation

CIF loading is fail-closed for missing cell parameters, invalid cell geometry, zero/negative volume, missing atom sites, and unreadable structure blocks. Space-group resolution follows a recorded order:

1. explicit CIF symbol;
2. explicit International Tables number;
3. Gemmi inference from a small structure;
4. an explicit P1 fallback accompanied by a warning.

Conflicting declarations produce diagnostics. spglib supplies an independent symmetry cross-check. The source structure used for validation remains separate from the Gemmi copy whose occupancies are converted to crystallographic occupancies for structure-factor calculation.

## Diffraction engine and resource guards

The indexed reflection table is the primary result. The continuous pseudo-Voigt profile is a display product with explicit width and mixing settings.

Before large arrays or Miller-index lists are allocated, the engine checks:

- requested profile-grid point count;
- a conservative reciprocal-space candidate estimate based on cell volume and minimum accessible spacing;
- the actual generated Miller-candidate count.

These limits are configurable in the API, CLI, and GUI and are recorded in analysis metadata.

## Elastic-tensor contract

Automatic sidecar pairing requires an explicit, unique relation to the CIF filename or material identifier. A sidecar that declares a different paired CIF is rejected. Multiple plausible sidecars are reported as ambiguous. Malformed matrices remain explicit invalid records; missing tensors remain absent.

For Materials Project acquisition, the adapter requests conventional-standard cells by default. The raw/POSCAR-format tensor is retained numerically and paired with the downloaded CIF for provenance, but the adapter does not persist enough of the upstream `ElasticityDoc.structure` orientation to verify a transform into the Cartesian basis emitted by Pymatgen CIF serialization. Raw/POSCAR and IEEE-format values therefore receive `frame_transform_required`, `usable_for_hkl_modulus=false`, and no directional values are emitted. Primitive-cell download is rejected while automatic elasticity coupling is enabled.

## Transactional result writing

The output path is validated before work begins. Input and output trees must be disjoint, output symlinks are rejected, and unrelated non-empty directories are never overwritten.

A run writes into a unique sibling staging directory:

```text
query / copy / calculate
        ↓
write all CSV, XLSX, JSON, documentation
        ↓
create manifest
        ↓
verify hashes, sizes, paths, symlinks, unlisted files
        ↓
atomically move staged directory to requested target
```

When replacing an existing bundle, the current bundle must first pass integrity verification. The old directory is moved to a temporary backup, the verified staging directory is moved into place, and the backup is removed only after success. A failed query, calculation, export, verification, or final move retains or restores the previous valid bundle.

## Export and integrity boundaries

CSV and workbook writes use temporary files followed by atomic replacement. Text originating from external providers or CIF metadata is escaped when it begins with spreadsheet formula-control characters. Large profile tables remain available in CSV even when omitted from the workbook to respect the Excel row budget.

`verify_bundle` rejects:

- missing or modified files;
- malformed SHA-256 or size entries;
- duplicate, absolute, parent-traversal, empty, or manifest-self paths;
- symbolic links;
- paths escaping the bundle root;
- files present on disk but absent from the manifest.

## Extension points

A new provider implements `PhaseProvider`. A new calculation can consume `StructureRecord` and add fields to a versioned schema. New scientific definitions require tests, documentation, changelog entries, and review by a contributor with relevant domain expertise. An incompatible output-schema change requires an explicit migration plan and a major version increment after 1.0.
