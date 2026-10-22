"""Public machine-readable response types; runtime values are plain JSON objects."""
from typing import Any, TypedDict


class ArtifactRef(TypedDict, total=False):
    kind: str
    path: str
    sha256: str


class WorkflowPlan(TypedDict):
    ready: bool
    request: dict[str, Any]
    stages: list[str]
    diagnostics: list[dict[str, Any]]
    estimated_queries: int
    required_dependencies: list[str]
    parameter_sources: dict[str, Any]


class RunStatus(TypedDict, total=False):
    schema: str
    run_id: str
    name: str
    workflow: str
    state: str
    stage: str
    completed_items: int
    total_items: int
    diagnostics: list[dict[str, Any]]
    artifacts: list[ArtifactRef]
    integrity: str
    coverage: dict[str, int]
    counters: dict[str, int]
    elapsed_seconds: float
    output_dir: str
    workspace: str
    active: bool
