"""Compare real operation counts after one injected export failure, offline.

Writes only a new user-selected output directory. This is an engineering
recovery benchmark, not validation against experimental diffraction data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diffractscout import pipeline  # noqa: E402
from diffractscout.demo import SYNTHETIC_FCC_CIF  # noqa: E402
from diffractscout.models import AnalysisSettings, CandidateRecord, DownloadArtifact  # noqa: E402
from diffractscout.validation import verify_bundle  # noqa: E402
from diffractscout.workflow import resume_job, run_job  # noqa: E402


class OfflineProvider:
    name = "recovery-measurement"

    def __init__(self):
        self.queries = self.material_downloads = 0

    def metadata(self):
        return {"provider": self.name, "data_nature": "synthetic fixture"}

    def search_subsystem(self, _system, **_options):
        self.queries += 1
        return [CandidateRecord(f"fixture-{index}", formula="Al") for index in (1, 2)]

    def download_candidates(self, candidates, output_dir, **_options):
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for candidate in candidates:
            self.material_downloads += 1
            path = output_dir / f"{candidate.material_id}.cif"
            path.write_text(SYNTHETIC_FCC_CIF, encoding="utf-8")
            results.append(DownloadArtifact(candidate, path))
        return results


def measure(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = AnalysisSettings(include_elasticity=False, include_patterns=False)
    real_calculate = pipeline.simulate_powder_pattern
    evidence = {"scenario": "two synthetic CIFs; export fails once after both calculations", "runs": {}}
    for mode in ("legacy_restart", "workflow_resume"):
        provider = OfflineProvider()
        started = time.perf_counter()
        with patch.object(pipeline, "simulate_powder_pattern", wraps=real_calculate) as calculate:
            with patch.object(pipeline, "export_result_bundle", side_effect=OSError("injected export failure")):
                if mode == "legacy_restart":
                    try:
                        pipeline.run_pipeline("Al", provider, output / "legacy", analysis_settings=settings)
                    except OSError:
                        pass
                else:
                    first = run_job({"workflow": "run", "composition": "Al", "analysis": asdict(settings)},
                                    workspace=output / "workspace", provider=provider)
                    if first["state"] != "failed":
                        raise RuntimeError("Expected the injected export failure to fail the first attempt.")
            initial = {"queries": provider.queries, "material_downloads": provider.material_downloads,
                       "phase_calculations": calculate.call_count, "seconds": time.perf_counter()-started}
            retried = time.perf_counter()
            if mode == "legacy_restart":
                result = pipeline.run_pipeline("Al", provider, output / "legacy", analysis_settings=settings)
                bundle = result.output_dir
            else:
                state = resume_job(first["run_id"], workspace=output / "workspace", provider=provider, background=False)
                if state["state"] != "completed":
                    raise RuntimeError(str(state["diagnostics"]))
                bundle = Path(state["output_dir"])
            retry = {"queries": provider.queries-initial["queries"],
                     "material_downloads": provider.material_downloads-initial["material_downloads"],
                     "phase_calculations": calculate.call_count-initial["phase_calculations"],
                     "seconds": time.perf_counter()-retried}
            evidence["runs"][mode] = {"initial": initial, "retry": retry, "verified": verify_bundle(bundle)["ok"],
                                      "bundle": str(bundle.relative_to(output))}
    resumed = evidence["runs"]["workflow_resume"]["retry"]
    if any(resumed[key] != 0 for key in ("queries", "material_downloads", "phase_calculations")):
        raise RuntimeError("Resume repeated a successful operation.")
    evidence["all_passed"] = all(run["verified"] for run in evidence["runs"].values())
    (output / "measurement.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(measure(args.output), indent=2))
