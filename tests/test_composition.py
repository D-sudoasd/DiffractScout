from diffractscout.composition import chemsys_subsystems, parse_composition_text


def test_alloy_alias_is_element_set_only() -> None:
    parsed = parse_composition_text("Ti-6Al-4V")
    assert set(parsed.elements) == {"Ti", "Al", "V"}
    assert "alias_element_set_only:ti6al4v" in parsed.notes
    assert len(chemsys_subsystems(parsed.elements)) == 7


def test_formula_and_mpids_can_coexist() -> None:
    parsed = parse_composition_text("Ni3Al plus mp-23, mp-149")
    assert set(parsed.elements) == {"Ni", "Al"}
    assert parsed.material_ids == ("mp-23", "mp-149")


def test_subsystem_order_limit() -> None:
    systems = chemsys_subsystems(["Ti", "Al", "V", "Cu"], max_order=2)
    assert len(systems) == 10
    assert "Al-Ti" in systems
    assert all(system.count("-") <= 1 for system in systems)
