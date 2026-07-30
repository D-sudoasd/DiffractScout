from diffractscout.structure_types import infer_structure_type


def test_conservative_structure_tags() -> None:
    assert infer_structure_type("Al", "F m -3 m", 225).name == "FCC"
    assert infer_structure_type("Fe", "I m -3 m", 229).name == "BCC"
    assert infer_structure_type("Ni3Al", "P m -3 m", 221).name == "L12"
    assert infer_structure_type("TiAl", "P 4/m m m", 123).name == "L10"
    assert infer_structure_type("Ti2Cr", "F d -3 m", 227).name == "C15"
    assert infer_structure_type("Unknown", "P 1", 1).name == ""
