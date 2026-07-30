# Architecture

## Design objective

DiffractScout represents candidate discovery, source acquisition, structural validation, theoretical diffraction, optional elasticity, and export as one traceable pipeline. The principal design constraint is that every numerical output can be connected to an input artifact, a calculation setting, a definition, and a software version.

## Layers

```text
CLI / Tk GUI / Python API
          │
          ▼
pipeline.py — orchestration and non-destructive output handling
          │
   ┌──────┴────────┐
   ▼               ▼
selection.py     providers/
subsystems       Materials Project adapter
ranking          provider protocol
   │               │
   └──────┬────────┘
          ▼
structure.py — CIF selection, parsing, hash, cell/space-group/occupancy checks
          │
          ├──────────────► elasticity.py — 6×6 validation and E(hkl normal)
          ▼
diffraction.py — systematic absences, multiplicity, d/2θ/q/g, |F|², LP, profile
          │
          ▼
exporters.py — CSV/XLSX/provenance JSON/SHA-256 manifest
          │
          ▼
validation.py — independent bundle integrity verification
```

## Provider boundary

The discovery layer depends on the `PhaseProvider` protocol. Materials Project is one optional implementation. A provider supplies:

- candidate records for one chemical subsystem;
- structure and optional property artifacts for selected candidates;
- provider metadata, including database version when available.

The base package therefore performs local CIF analysis without `mp-api` or `pymatgen`. The optional Materials Project adapter imports those dependencies only when requested. Tests use a deterministic offline provider, which exercises the complete discovery-to-export path without a network call or API key.

## Unified data contracts

The two source projects previously exchanged files through naming conventions. DiffractScout promotes those conventions into explicit dataclasses and machine-readable schemas:

- `CandidateRecord` stores database identity, stability metadata, query subsystem, space group and source URL.
- `StructureRecord` stores the exact CIF hash, selected data block, cell, space group, occupancy state and warnings.
- `ElasticTensor` stores the 6×6 matrix, unit, source, nature of data and coordinate frame.
- `ReflectionRecord` stores geometry, structure-factor terms, both LP channels, ranks and optional directional modulus.
- `manifest.json` stores a hash and size for every bundle file.

This separation permits each layer to be unit-tested and allows new database providers or export formats without changing the diffraction engine.

## Important design choices

### Gemmi as the offline crystallographic engine

Gemmi reads CIF, expands unit-cell sites, supplies space-group operations, identifies systematic absences, enumerates unique Miller indices and calculates X-ray structure factors. This keeps the base installation compact and enables a complete offline validation example. Optional spglib support provides an independent space-group cross-check when installed.

### Conventional-cell contract for Materials Project elasticity

The Materials Project adapter requests conventional-standard unit cells by default. Automatic directional coupling selects the raw/POSCAR-format tensor documented as consistent with that CIF setting and declares `materials_project_conventional_cif_cartesian`. The IEEE-format tensor remains in the sidecar for provenance. If the raw tensor is absent, the sidecar is marked `frame_transform_required`, and directional modulus values remain empty. Primitive-cell download is rejected while automatic elasticity coupling is enabled. Every usable 6×6 matrix must also pass finiteness, symmetry, invertibility, conditioning and positive-definiteness checks.

### Discrete reflections as the scientific result

The indexed line table is the primary diffraction result. The continuous pseudo-Voigt curve is a display product with explicit width and mixing parameters. This prevents a smooth plotted profile from being mistaken for an instrument model or fitted experiment.

### Fail-closed output handling

DiffractScout refuses to overwrite a non-empty directory unless it contains a recognized DiffractScout manifest and the user explicitly authorizes overwrite. Large Materials Project downloads require an explicit authorization flag once the candidate count exceeds a configurable threshold.

## Extension points

A new provider implements `PhaseProvider`. A new calculation can consume `StructureRecord` and add fields to a versioned output schema. An incompatible schema change requires a major version increment after version 1.0. New numerical definitions require tests, documentation and a migration note.
