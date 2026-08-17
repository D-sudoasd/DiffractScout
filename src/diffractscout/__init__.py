"""DiffractScout public package interface."""

from .models import AnalysisSettings, CandidateRecord, ParsedComposition
from .pipeline import analyze_cifs, discover_candidates, run_pipeline

__all__ = [
    "AnalysisSettings",
    "CandidateRecord",
    "ParsedComposition",
    "analyze_cifs",
    "discover_candidates",
    "run_pipeline",
    "__version__",
]

__version__ = "0.4.0"
