# CIF2Peaks → DiffractScout schema aliases

This document maps CIF2Peaks peak-table and intensity column names to DiffractScout
canonical export names. Prefer the DiffractScout names in new code and papers. Legacy
CIF2Peaks-compatible fields remain in exports where noted for interoperability.

Machine-readable peak columns are defined by `PEAK_HEADERS` in
`src/diffractscout/exporters.py`. Pattern columns are `PATTERN_HEADERS`.

## Intensity channels (critical)

| CIF2Peaks name | DiffractScout canonical name | Definition |
|---|---|---|
| `material_scattering_factor_R_hkl` | `volume_normalized_intensity_with_lp` | \(J_{hkl}^{\mathrm{with\,LP}} = I_{\mathrm{with\,LP}} / V_{\mathrm{cell}}^2\) |
| `material_scattering_factor_R_hkl_no_lp` | `volume_normalized_intensity_no_lp` | \(J_{hkl}^{\mathrm{no\,LP}} = I_{\mathrm{no\,LP}} / V_{\mathrm{cell}}^2\) |

### `R_hkl` is **not** a residual

In both projects, the historical field prefix `R_hkl` is a **project-defined
volume-normalized theoretical intensity** alias. It is **not**:

- a crystallographic residual factor (Rietveld \(R\), \(R_{\mathrm{wp}}\), \(R_{\mathrm{Bragg}}\), etc.);
- a standardized quantitative-phase-analysis scale factor or reference intensity ratio;
- an experimentally calibrated material scattering factor.

DiffractScout therefore:

1. exports preferred names `volume_normalized_intensity_with_lp` and
   `volume_normalized_intensity_no_lp`;
2. still writes the legacy names `material_scattering_factor_R_hkl` and
   `material_scattering_factor_R_hkl_no_lp` with **identical numeric values**;
3. ranks derived from those channels use `rank_by_R_hkl` /
   `rank_by_R_hkl_no_lp` as short legacy rank labels.

## Peak geometry and identity

| CIF2Peaks name | DiffractScout name | Notes |
|---|---|---|
| `phase_name` | `phase_name` | Same role |
| `cif_name` | `cif_name` | Same role |
| *(none / path only)* | `cif_sha256` | Always fingerprints the input CIF |
| `formula` | `formula` | Same role |
| `space_group` | `space_group` | Symbol string |
| `h`, `k`, `l` | `h`, `k`, `l` | Miller indices |
| `i` | `i` | Miller–Bravais basal index when used; blank for 3-index systems |
| `hkl` | `hkl` | Formatted plane label, e.g. `(1 1 0)` or `(1 0 -1 0)` |
| `family_label` | `family_label` | Symmetry-family display string |
| `multiplicity` | `multiplicity` | Family multiplicity from the Gemmi engine |
| `d_A` | `d_spacing_A` | \(d\)-spacing in Å |
| `theta_deg` | `theta_deg` | Bragg angle \(\theta\) |
| `two_theta_current_deg` / `two_theta_deg` | `two_theta_deg` | \(2\theta\) for the active wavelength |
| `two_theta_cu_ka_deg` | `two_theta_cu_ka_deg` | Convenience \(2\theta\) at Cu Kα (\(\lambda=1.5406\) Å) |
| `q_1_over_A` | `q_invA` | \(q = 2\pi / d\) |
| `g_1_over_A` | `g_invA` | \(g = 1 / d\) |

## Trig and form-factor helpers (exported)

| CIF2Peaks name | DiffractScout name |
|---|---|
| `sin_theta` | `sin_theta` |
| `cos_theta` | `cos_theta` |
| `sin_theta_over_lambda_1_over_A` | `sin_theta_over_lambda` |
| `sin2_theta_over_lambda2_1_over_A2` | `sin2_theta_over_lambda2` |
| `mean_structure_factor_sq_per_multiplicity` | `mean_structure_factor_sq_per_multiplicity` |
| `mean_structure_factor_abs_per_multiplicity` | `mean_structure_factor_abs_per_multiplicity` |
| `coincident_hkl_family_count` | `coincident_hkl_family_count` |
| `is_multi_family_peak` | `is_multi_family_peak` |

Note: DiffractScout marks coincident families by shared \(2\theta\) bins; it does not
merge multi-family peaks into a single intensity the way pymatgen sometimes does
(see `ENGINE_PARITY.md`).

## Raw and LP-separated intensities

| CIF2Peaks name | DiffractScout name | Notes |
|---|---|---|
| `theoretical_intensity_unscaled` | `intensity_with_lp` | Unscaled powder line with LP; engines differ |
| `multiplicity_structure_factor_sq` | `intensity_no_lp` | \(m_{hkl}\|F_{hkl}\|^2\) (no LP) |
| `lp_factor` | `lp_factor` | Lorentz–polarization factor |
| *(implicit)* | `structure_factor_sq` | \(\|F\|^2\) before multiplicity |
| `relative_intensity` | `normalized_intensity` | Phase-internal scale; max line → 100 |

## Volume-normalized helpers and ranks

| CIF2Peaks name | DiffractScout name |
|---|---|
| `inverse_material_scattering_factor_1_over_R_hkl` | `inverse_R_hkl` |
| `inverse_material_scattering_factor_1_over_R_hkl_no_lp` | `inverse_R_hkl_no_lp` |
| `phase_relative_R_hkl_pct` | `phase_relative_R_hkl_pct` |
| `phase_relative_R_hkl_no_lp_pct` | `phase_relative_R_hkl_no_lp_pct` |
| `phase_peak_rank_by_relative_intensity` | `rank_by_intensity` |
| `phase_peak_rank_by_R_hkl` | `rank_by_R_hkl` |
| `phase_peak_rank_by_R_hkl_no_lp` | `rank_by_R_hkl_no_lp` |
| `r_hkl_model_note` | `r_hkl_model_note` |

## Phase mass / density (peak + phase tables)

| CIF2Peaks name | DiffractScout name |
|---|---|
| `phase_density_g_cm3` | `density_g_cm3` |
| `phase_formula_weight_g_mol` | `formula_weight_g_mol` |
| `phase_cell_volume_A3` / `cell_volume_A3` | `cell_volume_A3` |

## Elasticity

| CIF2Peaks name | DiffractScout name | Notes |
|---|---|---|
| `young_modulus_hkl_normal_GPa` | `young_modulus_hkl_normal_GPa` | Plane-normal Young’s modulus from \(C_{ij}\) |
| `elastic_status` | `elastic_status` | Status string |
| `elastic_warning` / notes | `elastic_note` | Combined note channel |
| `elastic_hkl_used` | *(via plane normal)* | Three-index plane normal via `plane_hkl_for_normal` |
| `elastic_family_count` / `elastic_family_moduli_GPa` | partial | Coincident-family count is exported; multi-family modulus lists may differ |

## Pattern profile

| CIF2Peaks name | DiffractScout name |
|---|---|
| profile `two_theta_deg` | `two_theta_deg` |
| profile `d` | `d_A` |
| profile `q` / `g` | `q_invA` / `g_invA` |
| axis mode | `x_axis_mode` |
| selected abscissa | `x` |
| `relative_intensity` | `relative_intensity` |

When `AnalysisSettings.include_patterns` is false, `pattern_profiles.csv` and the
Excel `Patterns` sheet are omitted.

## Lab views (Excel only)

When `export_lab_views` is true (default):

| Sheet | Role |
|---|---|
| `推荐峰表` | Chinese beginner headers mapped from canonical peak rows |
| `使用说明` | Bilingual-oriented guide; states \(R_{hkl}\) is not a residual |
| `峰_<phase>` | Optional per-phase peak sheets (≤20 phases) |

## Not re-exported / intentional differences

| Topic | Status |
|---|---|
| Bit-identical intensities vs CIF2Peaks/pymatgen | **Not claimed** — Gemmi engine (see `ENGINE_PARITY.md`) |
| Experimental pattern overlay sheet | Deferred (CIF2Peaks draft, not productized) |
| Portable Windows EXE | Optional packaging path; not a schema column |

## Chinese beginner sheet header map

See `BEGINNER_PEAK_HEADERS_ZH` in `src/diffractscout/export_views.py` for the
exact Chinese → canonical key mapping used by `推荐峰表`.
