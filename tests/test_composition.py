import pytest

from diffractscout.composition import chemsys_subsystems, parse_composition_text


def test_alloy_alias_is_element_set_only() -> None:
    parsed = parse_composition_text("Ti-6Al-4V")
    assert set(parsed.elements) == {"Ti", "Al", "V"}
    assert "alias_element_set_only:ti6al4v" in parsed.notes
    assert len(chemsys_subsystems(parsed.elements)) == 7


def test_standalone_alias_boundaries_are_recognized() -> None:
    expected = {
        "Ti64": {"Ti", "Al", "V"},
        "IN718": {"Ni", "Cr", "Fe", "Nb", "Mo", "Ti", "Al"},
        "304L": {"Fe", "Cr", "Ni"},
    }
    for text, elements in expected.items():
        parsed = parse_composition_text(text)
        assert set(parsed.elements) == elements
        assert any(note.endswith(text.lower()) for note in parsed.notes)


@pytest.mark.parametrize(
    "text",
    ["Ti640", "noti64grade", "Ti64extra", "IN7180", "304LX", "316Li"],
)
def test_alias_substrings_require_ascii_alphanumeric_boundaries(text: str) -> None:
    with pytest.raises(ValueError, match="non-standalone alias"):
        parse_composition_text(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("CO2", ("C", "O")), ("MnO2", ("Mn", "O")), ("MoS2", ("Mo", "S"))],
)
def test_alias_substrings_and_percent_pairs_do_not_inject_elements(
    text: str, expected: tuple[str, ...]
) -> None:
    parsed = parse_composition_text(text)
    assert parsed.elements == expected
    assert not parsed.notes


def test_parenthesized_decimal_formula_elements_are_complete() -> None:
    assert parse_composition_text("(Fe,Ni)3Al").elements == ("Fe", "Ni", "Al")
    assert parse_composition_text("Li(Ni0.8Co0.1Mn0.1)O2").elements == (
        "Li",
        "Ni",
        "Co",
        "Mn",
        "O",
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [("C60", ("C",)), ("O2", ("O",)), ("N2", ("N",)), ("Fe2", ("Fe",))],
)
def test_single_element_formula_tokens_are_complete(
    text: str, expected: tuple[str, ...]
) -> None:
    parsed = parse_composition_text(text)
    assert parsed.elements == expected


@pytest.mark.parametrize(
    "text",
    [
        "Fe 70 wt% Ni 30 wt%",
        "fe 70 wt% ni 30 wt%",
        "FE70WT% NI30WT%",
    ],
)
def test_percent_pairs_are_case_insensitive_without_formula_fallback(text: str) -> None:
    assert parse_composition_text(text).elements == ("Fe", "Ni")


def test_formula_and_mpids_can_coexist() -> None:
    parsed = parse_composition_text("Ni3Al plus mp-23, mp-149")
    assert set(parsed.elements) == {"Ni", "Al"}
    assert parsed.material_ids == ("mp-23", "mp-149")


@pytest.mark.parametrize("text", ["Fe+Ni", "Fe/Ni", "Fe with Ni", "Fe和Ni"])
def test_additive_composition_keeps_both_elements(text: str) -> None:
    assert parse_composition_text(text).elements == ("Fe", "Ni")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fe+Ni+Cr", ("Fe", "Ni", "Cr")),
        ("Fe with Ni with Cr", ("Fe", "Ni", "Cr")),
        ("Fe+Ni/Cr和Mn", ("Fe", "Ni", "Cr", "Mn")),
    ],
)
def test_additive_composition_keeps_chained_elements(
    text: str, expected: tuple[str, ...]
) -> None:
    assert parse_composition_text(text).elements == expected


def test_additive_composition_normalizes_and_deduplicates() -> None:
    assert parse_composition_text("fe+ni/fe").elements == ("Fe", "Ni")


@pytest.mark.parametrize(
    "text",
    [
        "in/to",
        "Fe/Xx",
        "Fe+Xx",
        "Fe with Xx",
        "Fe+Ni+Xx",
        "SS304 + Xx",
        "Fe50Ni50 + Xx",
        "foo+Fe",
        "foo with Fe",
        "foo和Fe",
        "foo加Fe",
        "foo/Fe",
        "phase/Fe",
        "Fe/",
        "Fe//Ni",
        "Fe/+Ni",
        "Fe +",
        "Fe with",
    ],
)
def test_invalid_additive_does_not_keep_partial_elements(text: str) -> None:
    with pytest.raises(ValueError, match="Explicit additive composition"):
        parse_composition_text(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SS304 + Mo", ("Fe", "Cr", "Ni", "Mo")),
        ("Fe50Ni50 + Cr", ("Fe", "Ni", "Cr")),
        ("Ti6Al4V + Cu", ("Ti", "Al", "V", "Cu")),
        ("Ti-6Al-4V + Cu", ("Ti", "Al", "V", "Cu")),
    ],
)
def test_additive_composition_keeps_right_side_after_complex_left(
    text: str, expected: tuple[str, ...]
) -> None:
    assert parse_composition_text(text).elements == expected


def test_common_unicode_dashes_and_lowercase_chemsys_are_normalized() -> None:
    alloy = parse_composition_text("Ti–10V–2Fe–3Al")
    assert set(alloy.elements) == {"Ti", "V", "Fe", "Al"}

    chemsys = parse_composition_text("ti-al-v")
    assert set(chemsys.elements) == {"Ti", "Al", "V"}

    material = parse_composition_text("MP‑149")
    assert material.material_ids == ("mp-149",)


def test_subsystem_order_limit() -> None:
    systems = chemsys_subsystems(["Ti", "Al", "V", "Cu"], max_order=2)
    assert len(systems) == 10
    assert "Al-Ti" in systems
    assert all(system.count("-") <= 1 for system in systems)
