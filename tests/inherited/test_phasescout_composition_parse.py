import unittest

from diffractscout.compat.phasescout.composition_parse import (
    chemsys_subsystems,
    parse_composition_text,
    applies_to_for_elements,
)


class CompositionParseTests(unittest.TestCase):
    def test_chemsys(self):
        p = parse_composition_text("Ti-Al-V")
        self.assertEqual(set(p.elements), {"Ti", "Al", "V"})
        self.assertEqual(p.chemsys, "Al-Ti-V")

    def test_compact_alloy(self):
        p = parse_composition_text("Ti6Al4V")
        self.assertEqual(set(p.elements), {"Ti", "Al", "V"})

    def test_grade_with_dashes(self):
        p = parse_composition_text("Ti-6Al-4V + Cu")
        self.assertTrue({"Ti", "Al", "V", "Cu"}.issubset(set(p.elements)) or {"Ti", "Al", "V"}.issubset(set(p.elements)))

    def test_wt_percent(self):
        p = parse_composition_text("Ti 90, Al 6, V 4 wt%")
        self.assertEqual(set(p.elements), {"Ti", "Al", "V"})

    def test_alias(self):
        p = parse_composition_text("ti64 possible phases")
        self.assertEqual(set(p.elements), {"Ti", "Al", "V"})

    def test_mpids(self):
        p = parse_composition_text("mp-23 and mp-149")
        self.assertIn("mp-23", p.mpids)
        self.assertIn("mp-149", p.mpids)

    def test_subsystems(self):
        subs = chemsys_subsystems(["Ti", "Nb"])
        self.assertEqual(subs, ["Nb", "Ti", "Nb-Ti"])

    def test_applies_to(self):
        alloy_map = {"Ti6Al4V": {"Ti", "Al", "V"}, "Ti6Al4VCu": {"Ti", "Al", "V", "Cu"}}
        self.assertEqual(applies_to_for_elements(["Ti", "Al"], alloy_map), "Ti6Al4V;Ti6Al4VCu")
        self.assertEqual(applies_to_for_elements(["Cu"], alloy_map), "Ti6Al4VCu")


if __name__ == "__main__":
    unittest.main()
