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

`src/diffractscout/prototype_data/cod_1523304_ti_nb_cmcm.cif` is a copy of the
public-domain Crystallography Open Database entry 1523304 (Brown, Clark,
Eastabrook, and Jepson, Nature (London) 201 (1964) 914–915). `fetch-prototypes`
uses it as a Ti–20 at% Nb Cmcm symmetry scaffold. Its lattice parameters and
Nb occupancy remain those of that entry until a caller edits a derivative with
`adapt` and supplies the replacement values.

`prepare-cifs` additionally packages COD 1522498 (McHargue, Adair and Hammond,
1953, Ti–2.6 at% Nb hcp), with its public-domain header intact, and COD 9008554 /
AMCSD 0011232 (Wyckoff, *Crystal Structures* 1, 1963, pp. 7–83, beta Ti at
1173 K). The latter file retains its attribution requirement: use within the
scientific community requires proper attribution to the source work. Its
temperature and lattice are source conditions, not room-temperature values
for a target alloy. Original source files and citations remain in each initial
CIF bundle; generated CIFs explicitly identify their source and starting-model
status.
