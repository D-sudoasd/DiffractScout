# Source and license notice

DiffractScout integrates and restructures functionality developed in two MIT-licensed repositories:

1. `D-sudoasd/PhaseScout`, source snapshot `10e4cd4a7ae1317b4368ae4cce905e643d471584`.
2. `D-sudoasd/CIF2Peaks`, source snapshot `36e7e31419fa7ba2752e3e1bdf82e42b400e3b83`.

Both source repositories carry the following copyright notice:

> Copyright (c) 2026 D-sudoasd

Their MIT license permits use, modification, merging, publication, and distribution when the copyright and permission notice are retained. DiffractScout preserves that permission through its `LICENSE` file and records the detailed source-to-module mapping in `docs/SOURCE_LINEAGE.md`.

The implementation also depends on third-party packages distributed under their respective licenses. Packaged releases must include dependency metadata; binary redistributions must comply with each dependency's license terms.

The 2026-09-27 compatibility integration additionally includes the complete tracked
runtime modules from both repositories. Exact commits and original file hashes are
recorded in `docs/COMPAT_SOURCE_INVENTORY.json`. Original MIT license texts ship in
`diffractscout/compat/cif2peaks/LICENSE` and `diffractscout/compat/phasescout/LICENSE`.
PhaseScout imports and writable storage paths were adapted for package isolation.
Inherited CLI output is explicitly configured as UTF-8 for Windows pipe compatibility.
