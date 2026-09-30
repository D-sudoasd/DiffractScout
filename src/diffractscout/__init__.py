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

__version__ = "0.4.0"
