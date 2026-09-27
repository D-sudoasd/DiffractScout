"""Internet / literature fallback when Materials Project has no Cij.

Does NOT invent numerical elastic tensors. Produces search packs and optional
OpenAlex literature hits so users or agents can verify values elsewhere.
"""

from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


OPENALEX_WORKS = "https://api.openalex.org/works"
USER_AGENT = "PhaseScout/1.0 (materials research; local toolkit)"


@dataclass(frozen=True)
class ElasticityWebTarget:
    """One material that still needs Cij outside Materials Project."""

    material_id: str
    formula: str
    space_group: str = ""
    space_group_number: int | None = None
    cif_filename: str = ""
    mp_status: str = ""
    mp_error: str = ""


def build_search_query(target: ElasticityWebTarget) -> str:
    """Human/search-engine query for elastic constants of this phase."""

    bits = [target.formula or target.material_id, "elastic constants", "Cij"]
    if target.space_group:
        bits.append(target.space_group)
    bits.append(target.material_id)
    return " ".join(b for b in bits if b)


def scholar_url(query: str) -> str:
    return "https://scholar.google.com/scholar?" + urllib.parse.urlencode({"q": query})


def openalex_search_url(query: str) -> str:
    return OPENALEX_WORKS + "?" + urllib.parse.urlencode(
        {"search": query, "per_page": "5", "sort": "relevance_score:desc"}
    )


def materials_project_url(material_id: str) -> str:
    mid = (material_id or "").strip().lower()
    return f"https://next-gen.materialsproject.org/materials/{mid}"


def jarvis_search_url(formula: str) -> str:
    # Public JARVIS-DFT explorer; formula search is the practical entry point.
    q = urllib.parse.quote(formula or "")
    return f"https://jarvis.nist.gov/jarvisdft/?search={q}"


def web_search_row(target: ElasticityWebTarget) -> dict[str, object]:
    query = build_search_query(target)
    return {
        "material_id": target.material_id,
        "formula": target.formula,
        "space_group": target.space_group,
        "space_group_number": target.space_group_number
        if target.space_group_number is not None
        else "",
        "cif_filename": target.cif_filename,
        "mp_status": target.mp_status,
        "mp_error": target.mp_error,
        "suggested_query": query,
        "scholar_url": scholar_url(query),
        "openalex_url": openalex_search_url(query),
        "materials_project_url": materials_project_url(target.material_id),
        "jarvis_search_url": jarvis_search_url(target.formula),
        "numerical_cij": False,
        "role": "literature_hint_only",
        "note": (
            "Literature/web hints only — NOT extracted Cij tensors. "
            "Verify values and crystal orientation before use."
        ),
    }


def write_web_search_pack(path: Path, targets: list[ElasticityWebTarget]) -> Path:
    """Write CSV of search queries/URLs for MP-missing elasticity entries."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "material_id",
        "formula",
        "space_group",
        "space_group_number",
        "cif_filename",
        "mp_status",
        "mp_error",
        "suggested_query",
        "scholar_url",
        "openalex_url",
        "materials_project_url",
        "jarvis_search_url",
        "numerical_cij",
        "role",
        "note",
    ]
    rows = [web_search_row(t) for t in targets]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _http_get_json(
    url: str,
    *,
    timeout: float = 20.0,
    opener: Callable[[str, float], Any] | None = None,
) -> Any:
    if opener is not None:
        return opener(url, timeout)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def fetch_openalex_works(
    query: str,
    *,
    per_page: int = 5,
    timeout: float = 20.0,
    opener: Callable[[str, float], Any] | None = None,
) -> list[dict[str, object]]:
    """Search OpenAlex for literature related to elastic constants."""

    params = {
        "search": query,
        "per_page": str(max(1, min(per_page, 25))),
        "sort": "relevance_score:desc",
    }
    url = OPENALEX_WORKS + "?" + urllib.parse.urlencode(params)
    try:
        payload = _http_get_json(url, timeout=timeout, opener=opener)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return [{"error": str(exc), "query": query}]

    results: list[dict[str, object]] = []
    for work in payload.get("results") or []:
        if not isinstance(work, dict):
            continue
        doi = work.get("doi") or ""
        if isinstance(doi, str) and doi.startswith("https://doi.org/"):
            doi = doi.removeprefix("https://doi.org/")
        primary = work.get("primary_location") or {}
        landing = ""
        if isinstance(primary, dict):
            landing = str(primary.get("landing_page_url") or "")
        results.append(
            {
                "id": work.get("id") or "",
                "title": work.get("title") or "",
                "publication_year": work.get("publication_year") or "",
                "doi": doi,
                "cited_by_count": work.get("cited_by_count") or 0,
                "url": landing or (f"https://doi.org/{doi}" if doi else str(work.get("id") or "")),
            }
        )
    return results


def write_web_hits_jsonl(
    path: Path,
    targets: list[ElasticityWebTarget],
    *,
    per_page: int = 5,
    timeout: float = 20.0,
    opener: Callable[[str, float], Any] | None = None,
) -> Path:
    """Live OpenAlex search for each missing material; one JSON object per line."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for target in targets:
            query = build_search_query(target)
            hits = fetch_openalex_works(
                query, per_page=per_page, timeout=timeout, opener=opener
            )
            record = {
                "material_id": target.material_id,
                "formula": target.formula,
                "space_group": target.space_group,
                "query": query,
                "source": "openalex",
                "role": "literature_hint_only",
                "numerical_cij": False,
                "nature_of_data": "literature_hint_only",
                "hit_count": len([h for h in hits if "error" not in h]),
                "hits": hits,
                "note": (
                    "Literature hints only — no auto-parsed Cij matrix. "
                    "Extract and verify manually before use."
                ),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def run_web_fallback(
    output_dir: Path,
    targets: list[ElasticityWebTarget],
    *,
    live_search: bool = True,
    per_page: int = 5,
    timeout: float = 20.0,
    opener: Callable[[str, float], Any] | None = None,
) -> dict[str, object]:
    """Write search pack (+ optional live hits) for MP-missing elasticity rows."""

    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {
        "missing_count": len(targets),
        "web_search_csv": "",
        "web_hits_jsonl": "",
        "live_search": bool(live_search and targets),
    }
    if not targets:
        return summary

    csv_path = write_web_search_pack(output_dir / "elasticity_web_search.csv", targets)
    summary["web_search_csv"] = str(csv_path)

    if live_search:
        hits_path = write_web_hits_jsonl(
            output_dir / "elasticity_web_hits.jsonl",
            targets,
            per_page=per_page,
            timeout=timeout,
            opener=opener,
        )
        summary["web_hits_jsonl"] = str(hits_path)

    return summary
