"""Checkpoint individual successful provider operations, including empty queries."""
from __future__ import annotations

import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..models import CandidateRecord, DownloadArtifact
from ..network import transient_error
from ..pipeline import _normalize_download_artifacts, _reconcile_download_coverage
from ..utils import to_jsonable, write_json
from .checkpoints import fingerprint, publish_checkpoint, verify_checkpoint
from .store import read_json


def artifact_from_dict(row: dict[str, Any], root: Path) -> DownloadArtifact:
    values = dict(row)
    values["candidate"] = CandidateRecord(**values["candidate"])
    for key in ("cif_path", "elasticity_path"):
        values[key] = root / values[key] if values.get(key) else None
    return DownloadArtifact(**values)


class CheckpointProvider:
    def __init__(self, provider: Any, execution: Any):
        self.provider = provider
        self.execution = execution
        self.name = provider.name
        self.failures: list[dict[str, Any]] = []

    def metadata(self) -> dict[str, Any]:
        return self.execution.scrub(self.provider.metadata())

    def _query(self, operation: str, argument: Any, options: dict) -> list[CandidateRecord]:
        execution = self.execution
        execution.check_cancel()
        execution.store.stage("discovery")
        key = fingerprint([self.name, operation, argument, options])
        target = execution.root / "queries" / key
        if target.exists():
            try:
                verify_checkpoint(target)
            except Exception as exc:
                from .execution import WorkflowIntegrityError
                raise WorkflowIntegrityError(str(exc)) from exc
            execution.store.count("reused")
            return [CandidateRecord(**row) for row in read_json(target / "records.json")]
        for attempt in range(execution.max_attempts):
            execution.check_cancel()
            execution.store.count("queries")
            try:
                function = getattr(self.provider, operation)
                rows = function(argument, **options)
                rows = [replace(row, source_url=execution.scrub(row.source_url)) for row in rows]
                publish_checkpoint(target, lambda directory: write_json(directory / "records.json", to_jsonable(rows)))
                execution.store.event("query_completed", item=str(argument), count=len(rows), outcome="records" if rows else "empty")
                return rows
            except Exception as exc:
                retryable = transient_error(exc)
                if retryable and attempt + 1 < execution.max_attempts:
                    execution.store.event("retry", stage="discovery", item=str(argument), attempt=attempt+1)
                    time.sleep(0.25 * 2**attempt)
                    continue
                failure = execution.diagnostic("QUERY_FAILED", exc, stage="discovery", item=str(argument), retryable=retryable)
                self.failures.append(failure)
                raise RuntimeError(failure["message"]) from None
        return []  # all branches above return or raise

    def search_subsystem(self, chemsys: str, **kwargs: Any) -> list[CandidateRecord]:
        return self._query("search_subsystem", chemsys, kwargs)

    def search_material_ids(self, material_ids, **kwargs: Any) -> list[CandidateRecord]:
        return self._query("search_material_ids", list(material_ids), kwargs)

    def download_candidates(self, candidates, output_dir: Path, **kwargs: Any) -> list[DownloadArtifact]:
        execution = self.execution
        candidates = list(candidates)
        results = []
        output_dir.mkdir(parents=True, exist_ok=True)
        execution.store.stage("download", total=len(candidates))
        for index, candidate in enumerate(candidates):
            execution.check_cancel()
            key = fingerprint([to_jsonable(candidate), kwargs])
            target = execution.root / "downloads" / key
            if target.exists():
                verify_checkpoint(target)
                row = artifact_from_dict(read_json(target / "artifact.json"), target)
                execution.store.count("reused")
            else:
                row = None
                for attempt in range(execution.max_attempts):
                    execution.check_cancel()
                    temporary = execution.root / "downloads" / ("attempt-" + key)
                    # Only this worker-owned uncommitted attempt is disposable.
                    if temporary.exists():
                        shutil.rmtree(temporary)
                    temporary.mkdir(parents=True)
                    execution.store.count("downloads")
                    try:
                        raw = self.provider.download_candidates([candidate], temporary, **kwargs)
                        raw, coverage = _reconcile_download_coverage([candidate], raw)
                        normalized, diagnostics = _normalize_download_artifacts(
                            raw, temporary, include_elasticity=kwargs.get("include_elasticity", True))
                        for issue in [*coverage, *diagnostics]:
                            execution.extra_diagnostics.append(issue)
                        if not normalized:
                            raise RuntimeError("Provider returned no artifact for requested material.")
                        row = normalized[0]
                        row = replace(row, error=execution.scrub(row.error), elasticity_error=execution.scrub(row.elasticity_error),
                                      provider_metadata=execution.scrub(row.provider_metadata))
                        retryable = bool(row.provider_metadata.get("retryable", False))
                    except Exception as exc:
                        retryable = transient_error(exc)
                        row = DownloadArtifact(candidate, None, status="failed", error=execution.scrub(str(exc)),
                                               provider_metadata={"retryable": retryable})
                    if row.status == "ok" or not retryable or attempt + 1 == execution.max_attempts:
                        break
                    execution.store.event("retry", stage="download", item=candidate.material_id, attempt=attempt+1)
                    time.sleep(0.25 * 2**attempt)
                if row is None:
                    raise RuntimeError("Download attempts produced no result.")
                if row.status == "ok":
                    def save(directory: Path) -> None:
                        # Keep all normalized metadata sidecars; their contents
                        # and every referenced source are verified on reuse.
                        shutil.copytree(temporary, directory, dirs_exist_ok=True)
                        payload = execution.scrub(to_jsonable(row))
                        for name in ("cif_path", "elasticity_path"):
                            value = getattr(row, name)
                            payload[name] = value.relative_to(temporary).as_posix() if value else None
                        write_json(directory / "artifact.json", payload)
                    publish_checkpoint(target, save)
                    row = artifact_from_dict(read_json(target / "artifact.json"), target)
                else:
                    self.failures.append(execution.diagnostic("DOWNLOAD_FAILED", row.error, stage="download",
                                                            item=candidate.material_id, retryable=retryable))
            results.append(row)
            execution.store.update(completed_items=index+1, total_items=len(candidates))
        return results
