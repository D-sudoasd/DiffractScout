import unittest

from diffractscout.compat.phasescout.mp_client import (
    CifNameMeta,
    MaterialSummary,
    PhaseCandidate,
    build_cif_filename,
    format_ehull_token,
    parse_spacegroup_display,
    sanitize_filename_part,
)
from diffractscout.compat.phasescout.structure_type import infer_structure_type, infer_structure_type_detailed


class CifFilenameTests(unittest.TestCase):
    def test_scheme_b_stable_al(self):
        name = build_cif_filename(
            "mp-134",
            "Al",
            space_group="Fm-3m",
            space_group_number=225,
            energy_above_hull=0.0,
            is_stable=True,
        )
        self.assertEqual(name, "mp-134_Al_FCC_sg225_Fm-3m_ehull0_stable.cif")

    def test_scheme_b_hcp_co(self):
        name = build_cif_filename(
            "mp-54",
            "Co",
            space_group="P6_3/mmc",
            space_group_number=194,
            energy_above_hull=0.025,
            is_stable=False,
        )
        self.assertEqual(name, "mp-54_Co_HCP_sg194_P6_3_mmc_ehull0p025.cif")

    def test_infer_structure_types_detailed(self):
        cases = [
            ("Al", "Fm-3m", 225, "FCC"),
            ("Fe", "Im-3m", 229, "BCC"),
            ("Co", "P6_3/mmc", 194, "HCP"),
            ("Ni3Al", "Pm-3m", 221, "L12"),
            ("FeAl", "Pm-3m", 221, "B2"),
            ("Fe3Al", "Fm-3m", 225, "DO3"),
            ("FeNi3", "Fm-3m", 225, "DO3"),  # 3:1 @225 → DO3; not L12
            ("Co3Ni", "P6_3/mmc", 194, "D019"),
            ("MgZn2", "P6_3/mmc", 194, "C14"),
            ("MgCu2", "Fd-3m", 227, "C15"),
            ("Nb3Sn", "Pm-3n", 223, "A15"),
            ("FeCr", "P4_2/mnm", 136, "SIGMA"),
            ("SiO2", "P2_1/c", 14, ""),
        ]
        for formula, sg, num, expect in cases:
            got = infer_structure_type(formula, sg, num)
            self.assertEqual(got, expect, msg=f"{formula} {sg} {num}")

    def test_structure_type_rule_populated(self):
        st = infer_structure_type_detailed("Ni3Al", "Pm-3m", 221)
        self.assertEqual(st.type, "L12")
        self.assertIn("L12", st.rule)

    def test_l12_filename(self):
        name = build_cif_filename(
            "mp-2593",
            "AlNi3",
            space_group="Pm-3m",
            space_group_number=221,
            energy_above_hull=0.0,
            is_stable=True,
        )
        self.assertEqual(name, "mp-2593_AlNi3_L12_sg221_Pm-3m_ehull0_stable.cif")

    def test_minimal_mpid_formula_only(self):
        name = build_cif_filename("mp-149", "Si")
        self.assertEqual(name, "mp-149_Si.cif")

    def test_ehull_token(self):
        self.assertEqual(format_ehull_token(0.0), "ehull0")
        self.assertEqual(format_ehull_token(1.982934), "ehull1p983")

    def test_parse_spacegroup_display(self):
        self.assertEqual(parse_spacegroup_display("Fm-3m (225)"), ("Fm-3m", 225))
        self.assertEqual(parse_spacegroup_display("P6_3/mmc"), ("P6_3/mmc", None))

    def test_from_phase_candidate(self):
        cand = PhaseCandidate(
            material_id="mp-72",
            formula="Ti",
            energy_above_hull=0.0,
            is_stable=True,
            theoretical=False,
            space_group="P6/mmm",
            space_group_number=191,
            crystal_system="hexagonal",
        )
        meta = CifNameMeta.from_phase_candidate(cand)
        name = build_cif_filename(
            cand.material_id,
            meta.formula,
            space_group=meta.space_group,
            space_group_number=meta.space_group_number,
            energy_above_hull=meta.energy_above_hull,
            is_stable=meta.is_stable,
            structure_type=meta.structure_type,
        )
        self.assertEqual(name, "mp-72_Ti_sg191_P6_mmm_ehull0_stable.cif")

    def test_from_material_summary(self):
        summary = MaterialSummary(
            material_id="mp-134",
            formula="Al",
            energy_above_hull=0.0,
            band_gap=0.0,
            crystal_system="cubic",
            spacegroup="Fm-3m (225)",
        )
        meta = CifNameMeta.from_material_summary(summary)
        self.assertEqual(meta.space_group, "Fm-3m")
        self.assertEqual(meta.space_group_number, 225)
        self.assertTrue(meta.is_stable)
        self.assertEqual(meta.structure_type, "FCC")

    def test_sanitize_collapses_underscores(self):
        self.assertEqual(sanitize_filename_part("P6_3//mmc", "x"), "P6_3_mmc")


if __name__ == "__main__":
    unittest.main()
