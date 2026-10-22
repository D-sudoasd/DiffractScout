"""DiffractScout public package interface."""

from .models import AnalysisSettings, CandidateRecord, ParsedComposition
from .pipeline import analyze_cifs, discover_candidates, run_pipeline
from .phase_cif import adapt_cif, fetch_prototypes
from .initial_cifs import PrepareCifsResult, prepare_cifs

__all__ = [
    "AnalysisSettings",
    "CandidateRecord",
    "ParsedComposition",
    "analyze_cifs",
    "discover_candidates",
    "run_pipeline",
    "adapt_cif",
    "fetch_prototypes",
    "prepare_cifs",
    "PrepareCifsResult",
    "__version__",
]

_WORKFLOW_EXPORTS = {
    "WorkflowRequest", "context", "schema", "plan_workflow", "run_job", "submit_job",
    "resume_job", "cancel_job", "status_job", "list_jobs", "read_events", "get_result",
    "run_batch",
}
__all__ += sorted(_WORKFLOW_EXPORTS)


def __getattr__(name: str):
    if name in _WORKFLOW_EXPORTS:
        from . import workflow

        value = getattr(workflow, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__version__ = "0.4.0"
