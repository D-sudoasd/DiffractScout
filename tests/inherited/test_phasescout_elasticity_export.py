import csv
import json
import tempfile
import unittest
from pathlib import Path

from diffractscout.compat.phasescout import mp_client


class FakeComposition:
    def __init__(self, reduced_formula):
        self.reduced_formula = reduced_formula


class FakeStructure:
    def __init__(self, formula):
        self.composition = FakeComposition(formula)

    def to(self, fmt, filename):
        if fmt != "cif":
            raise ValueError("unexpected format")
        Path(filename).write_text("# fake cif\n", encoding="utf-8")


class FakeElasticTensor:
    raw = [
        [160.0, 60.0, 50.0, 0.0, 0.0, 0.0],
        [60.0, 160.0, 50.0, 0.0, 0.0, 0.0],
        [50.0, 50.0, 150.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 80.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 80.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 75.0],
    ]
    ieee_format = [
        [165.7, 63.9, 63.9, 0.0, 0.0, 0.0],
        [63.9, 165.7, 63.9, 0.0, 0.0, 0.0],
        [63.9, 63.9, 165.7, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 79.6, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 79.6, 0.0],
        [0.0, 0.0, 0.0, 0.0, 0.0, 79.6],
    ]


class FakeModulus:
    voigt = 98.0
    reuss = 95.0
    vrh = 96.5


class FakeElasticityDoc:
    material_id = "mp-149"
    formula_pretty = "Si"
    elastic_tensor = FakeElasticTensor()
    bulk_modulus = FakeModulus()
    shear_modulus = FakeModulus()
    homogeneous_poisson = 0.22
    universal_anisotropy = 0.01
    fitting_method = "pseudoinverse"
    state = "successful"


class FakeElasticityRester:
    def search(self, material_ids, fields=None, all_fields=False, chunk_size=1000, num_chunks=None):
        self.material_ids = material_ids
        self.fields = fields
        return [FakeElasticityDoc()]


class FakeMaterials:
    def __init__(self):
        self.elasticity = FakeElasticityRester()


class FakeMPRester:
    def __init__(self, api_key):
        self.api_key = api_key
        self.materials = FakeMaterials()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_structure_by_material_id(self, material_id, final=True, conventional_unit_cell=True):
        formulas = {"mp-149": "Si", "mp-404": "Missing"}
        return FakeStructure(formulas[material_id])


class ElasticityExportTests(unittest.TestCase):
    def setUp(self):
        self.original_mprester = mp_client.MPRester
        mp_client.MPRester = FakeMPRester

    def tearDown(self):
        mp_client.MPRester = self.original_mprester

    def test_download_cifs_can_export_paired_elasticity_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = mp_client.MaterialsProjectService("x" * 32)

            results = service.download_cifs(
                ["mp-149", "mp-404"],
                Path(tmp),
                conventional_unit_cell=True,
                include_elasticity=True,
            )

            # Structure-only path (no name_meta): formula + SG from structure when available.
            # FakeStructure has no SG analyzer → mp-id_formula.cif
            self.assertTrue((Path(tmp) / "mp-149_Si.cif").exists())
            self.assertTrue((Path(tmp) / "mp-404_Missing.cif").exists())
            self.assertEqual([result.ok for result in results], [True, True])
            self.assertIs(results[0].elasticity_found, True)
            self.assertIs(results[1].elasticity_found, False)

            index_path = Path(tmp) / "elasticity_index.csv"
            self.assertTrue(index_path.exists())
            with index_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["material_id"], "mp-149")
            self.assertEqual(rows[0]["status"], "ok")
            self.assertEqual(rows[0]["cij_basis"], "ieee_format")
            self.assertAlmostEqual(float(rows[0]["C11_GPa"]), 165.7)
            self.assertAlmostEqual(float(rows[0]["K_VRH_GPa"]), 96.5)

            self.assertEqual(rows[1]["material_id"], "mp-404")
            self.assertEqual(rows[1]["status"], "no_elasticity_data")
            self.assertEqual(rows[1]["error"], "No elasticity document returned.")

            ok_json = Path(tmp) / rows[0]["json_filename"]
            missing_json = Path(tmp) / rows[1]["json_filename"]
            self.assertTrue(ok_json.exists())
            self.assertTrue(missing_json.exists())

            payload = json.loads(ok_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "Materials Project materials/elasticity")
            self.assertEqual(payload["units"]["elastic_tensor"], "GPa")
            self.assertEqual(payload["elastic_tensor"]["ieee_format"][0][0], 165.7)
            prov = payload["provenance"]
            self.assertEqual(prov["provider"], "Materials Project")
            self.assertEqual(prov["nature_of_data"], "DFT_calculated")
            self.assertTrue(prov["numerical_cij"])
            self.assertTrue(prov["not_experimental"])
            self.assertIn("methodology_url", prov)
            self.assertIn("mp-149", prov["mp_material_url"])
            self.assertEqual(payload["schema"], "phasescout_elasticity_v1")
            self.assertIn("stiffness_GPa", payload)
            self.assertEqual(
                payload["cif2peaks"]["coordinate_frame"],
                "materials_project_ieee_conventional",
            )
            self.assertEqual(rows[0]["nature_of_data"], "DFT_calculated")
            self.assertEqual(rows[0]["provider"], "Materials Project")
            self.assertTrue((Path(tmp) / "Cij_PROVENANCE.txt").is_file())
            self.assertIn("CIF2Peaks", (Path(tmp) / "Cij_PROVENANCE.txt").read_text(encoding="utf-8"))
            manifest_path = Path(tmp) / "cif2peaks_manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "phasescout_cif2peaks_manifest_v1")
            self.assertEqual(len(manifest["items"]), 2)
            self.assertTrue(any(item.get("numerical_cij") for item in manifest["items"]))

            missing_payload = json.loads(missing_json.read_text(encoding="utf-8"))
            self.assertEqual(missing_payload["status"], "no_elasticity_data")
            self.assertIsNone(missing_payload["elastic_tensor"])
            self.assertFalse(missing_payload["provenance"]["numerical_cij"])
            self.assertEqual(missing_payload["provenance"]["nature_of_data"], "none")


if __name__ == "__main__":
    unittest.main()
