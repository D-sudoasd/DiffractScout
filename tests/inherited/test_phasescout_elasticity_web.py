import json
import tempfile
import unittest
from pathlib import Path

from diffractscout.compat.phasescout.elasticity_web import (
    ElasticityWebTarget,
    build_search_query,
    fetch_openalex_works,
    run_web_fallback,
    web_search_row,
    write_web_search_pack,
)


class ElasticityWebTests(unittest.TestCase):
    def test_build_search_query(self):
        target = ElasticityWebTarget(
            material_id="mp-134",
            formula="Al",
            space_group="Fm-3m",
        )
        q = build_search_query(target)
        self.assertIn("Al", q)
        self.assertIn("elastic constants", q)
        self.assertIn("mp-134", q)

    def test_web_search_pack_csv(self):
        target = ElasticityWebTarget(
            material_id="mp-404",
            formula="Missing",
            space_group="P1",
            space_group_number=1,
            cif_filename="mp-404_Missing.cif",
            mp_status="no_elasticity_data",
            mp_error="No elasticity document returned.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_web_search_pack(Path(tmp) / "elasticity_web_search.csv", [target])
            text = path.read_text(encoding="utf-8")
            self.assertIn("mp-404", text)
            self.assertIn("scholar.google.com", text)
            self.assertIn("openalex.org", text)
            self.assertIn("jarvis.nist.gov", text)

            row = web_search_row(target)
            self.assertTrue(str(row["suggested_query"]).startswith("Missing"))

    def test_run_web_fallback_offline_and_live_mock(self):
        targets = [
            ElasticityWebTarget(material_id="mp-1", formula="Ti", space_group="P6/mmm"),
            ElasticityWebTarget(material_id="mp-2", formula="Al", space_group="Fm-3m"),
        ]

        def fake_opener(url: str, timeout: float):
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Elastic constants of Ti",
                        "publication_year": 2020,
                        "doi": "https://doi.org/10.1/xyz",
                        "cited_by_count": 3,
                        "primary_location": {"landing_page_url": "https://example.com/paper"},
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offline = run_web_fallback(root, targets, live_search=False)
            self.assertEqual(offline["missing_count"], 2)
            self.assertTrue(Path(str(offline["web_search_csv"])).is_file())
            self.assertEqual(offline["web_hits_jsonl"], "")

            live = run_web_fallback(root, targets, live_search=True, opener=fake_opener)
            hits_path = Path(str(live["web_hits_jsonl"]))
            self.assertTrue(hits_path.is_file())
            lines = hits_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            rec = json.loads(lines[0])
            self.assertEqual(rec["source"], "openalex")
            self.assertEqual(rec["hit_count"], 1)
            self.assertEqual(rec["hits"][0]["doi"], "10.1/xyz")

    def test_fetch_openalex_error_is_soft(self):
        def boom(url: str, timeout: float):
            raise TimeoutError("network down")

        hits = fetch_openalex_works("Al elastic constants", opener=boom)
        self.assertEqual(len(hits), 1)
        self.assertIn("error", hits[0])


if __name__ == "__main__":
    unittest.main()
