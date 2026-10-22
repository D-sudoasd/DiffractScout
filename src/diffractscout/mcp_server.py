"""Optional local stdio MCP adapter for the shared workflow service.

Install ``diffractscout[mcp]`` to run this module. Importing DiffractScout does
not import the MCP SDK or start a server.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .agent_cli import error_payload, execute_request


def create_server():
    """Create an official SDK v2 server; only this entry needs the optional SDK."""
    try:
        from mcp.server import MCPServer
        from mcp.types import CallToolResult, TextContent, ToolAnnotations
        from pydantic import Field
        from typing import Annotated
    except ImportError as exc:
        raise ImportError("Install the optional MCP adapter with: pip install 'diffractscout[mcp]'") from exc

    from . import __version__, workflow

    server = MCPServer(
        "DiffractScout", version=__version__,
        instructions=("Use context and schema to discover workflow requests. Plan before execution. "
                      "Use submit for long jobs, then status/events/result. Credentials are read "
                      "from the server environment; never include them in requests. Results are "
                      "theoretical calculations with provenance, not experimental phase identification."),
    )
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                           idempotent_hint=True, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                            idempotent_hint=False, open_world_hint=True)

    def invoke(function: Callable, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            payload = error_payload(exc)
            return CallToolResult(is_error=True, structured_content=payload,
                                  content=[TextContent(type="text", text=json.dumps(payload))])

    # Resolve locally imported Annotated/Field before SDK signature inspection.
    page_limit = Annotated[int, Field(ge=1, le=1000, description="Maximum rows returned.")]
    nonnegative = Annotated[int, Field(ge=0)]

    @server.tool(annotations=read)
    def context() -> dict[str, Any]:
        """Describe supported workflows, units, capabilities, and execution boundaries."""
        return invoke(workflow.context)

    @server.tool(annotations=read)
    def schema(name: str = "request") -> dict[str, Any]:
        """Return the named workflow JSON Schema, including the request contract."""
        return invoke(workflow.schema, name)

    @server.tool(annotations=read)
    def plan(request: dict[str, Any]) -> dict[str, Any]:
        """Validate a workflow request and describe its stages without executing it."""
        return invoke(workflow.plan_workflow, request)

    @server.tool(annotations=write)
    def run(request: dict[str, Any], workspace: str | None = None) -> dict[str, Any]:
        """Run one request or diffractscout_batch_v1 manifest to completion."""
        return invoke(execute_request, request, workspace=workspace)

    @server.tool(annotations=write)
    def submit(request: dict[str, Any], workspace: str | None = None) -> dict[str, Any]:
        """Submit durable background work and return immediately with its job identity."""
        return invoke(execute_request, request, workspace=workspace, background=True)

    def list_jobs(workspace: str | None = None, offset: int = 0,
                  limit: int = 100) -> dict[str, Any]:
        """List durable jobs with bounded pagination; offsets start at zero."""
        def get_page():
            if offset < 0 or not 1 <= limit <= 1000:
                raise ValueError("offset must be nonnegative and limit must be between 1 and 1000.")
            jobs = workflow.list_jobs(workspace=workspace)
            end = offset + limit
            return {"jobs": jobs[offset:end], "offset": offset, "limit": limit,
                    "total": len(jobs), "next_offset": end if end < len(jobs) else None}
        return invoke(get_page)

    @server.tool(annotations=read)
    def status(run_id: str, workspace: str | None = None) -> dict[str, Any]:
        """Read a job's state, progress, counters, diagnostics, and artifact paths."""
        return invoke(workflow.status_job, run_id, workspace=workspace)

    def events(run_id: str, workspace: str | None = None, after: int = 0,
               limit: int = 100) -> dict[str, Any]:
        """Read a bounded event page after the given sequence cursor."""
        return invoke(workflow.read_events, run_id, workspace=workspace, after=after, limit=limit)

    def result(run_id: str, workspace: str | None = None, table: str | None = None,
               offset: int = 0, limit: int = 100, verify: bool = True) -> dict[str, Any]:
        """Read verified artifacts or a bounded table page; preserve scientific missing values."""
        return invoke(workflow.get_result, run_id, workspace=workspace, table=table,
                      offset=offset, limit=limit, verify=verify)

    # Numeric constraints are part of the published MCP input schemas.
    for function, fields in ((list_jobs, {"offset": nonnegative, "limit": page_limit}),
                             (events, {"after": nonnegative, "limit": page_limit}),
                             (result, {"offset": nonnegative, "limit": page_limit})):
        function.__annotations__.update(fields)
        server.tool(annotations=read)(function)

    @server.tool(annotations=write)
    def resume(run_id: str, workspace: str | None = None,
               background: bool = True) -> dict[str, Any]:
        """Resume unfinished work with the service's input and checkpoint integrity checks."""
        return invoke(workflow.resume_job, run_id, workspace=workspace, background=background)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                           idempotent_hint=True, open_world_hint=False))
    def cancel(run_id: str, workspace: str | None = None) -> dict[str, Any]:
        """Request cooperative cancellation; retain completed items and recorded evidence."""
        return invoke(workflow.cancel_job, run_id, workspace=workspace)

    return server


def main() -> int:
    try:
        create_server().run(transport="stdio")
    except ImportError as exc:
        print(json.dumps(error_payload(exc)), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
