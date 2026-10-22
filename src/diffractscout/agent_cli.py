"""JSON-only command line access to the shared workflow service."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)

    def print_help(self, file=None) -> None:
        super().print_help(file=file or sys.stderr)


def error_payload(exc: Exception) -> dict[str, Any]:
    """Keep failures machine readable without echoing environment credentials."""
    message = str(exc)
    for key in ("MP_API_KEY", "MATERIALS_PROJECT_API_KEY"):
        secret = os.environ.get(key)
        if secret:
            message = message.replace(secret, "[redacted]")
    return {"ok": False, "error": {"type": type(exc).__name__, "message": message}}


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="diffractscout agent", description=__doc__)
    parser.add_argument("--workspace", help="Directory containing durable job records.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "schema", "plan", "run", "submit", "list", "status",
                 "events", "resume", "cancel", "result"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", default=argparse.SUPPRESS)
        if name == "schema":
            command.add_argument("name", nargs="?", default="request")
        if name in {"plan", "run", "submit"}:
            command.add_argument("request", help="Request JSON file, JSON object, or '-' for stdin.")
        if name in {"status", "events", "resume", "cancel", "result"}:
            command.add_argument("run_id")
        if name == "resume":
            command.add_argument("--foreground", action="store_true")
        if name == "events":
            command.add_argument("--after", type=int, default=0)
            command.add_argument("--limit", type=int, default=100)
        if name == "result":
            command.add_argument("--table")
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=100)
            command.add_argument("--no-verify", action="store_true")
    return parser


def load_request(source: str) -> tuple[dict[str, Any], Path]:
    """Read one object; relative paths in a file are relative to that file."""
    base_dir = Path.cwd()
    if source == "-":
        payload = json.load(sys.stdin)
    elif source.lstrip().startswith("{"):
        payload = json.loads(source)
    else:
        path = Path(source).expanduser().resolve()
        base_dir = path.parent
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("A workflow request or batch manifest must be a JSON object.")
    return payload, base_dir


def execute_request(
    payload: dict[str, Any], *, base_dir: Path | None = None,
    workspace: str | None = None, background: bool = False,
) -> dict[str, Any]:
    """Normalize requests once, then invoke the same service as GUI and API."""
    from . import workflow

    if payload.get("schema") == "diffractscout_batch_v1":
        unknown = set(payload) - {"schema", "requests", "max_workers"}
        if unknown:
            raise ValueError("Unknown batch manifest fields: " + ", ".join(sorted(unknown)))
        requests = payload.get("requests")
        if not isinstance(requests, list) or not requests:
            raise ValueError("Batch requests must be a nonempty array of workflow requests.")
        normalized = [workflow.WorkflowRequest.from_dict(item, base_dir=base_dir)
                      for item in requests]
        return workflow.run_batch(normalized, workspace=workspace,
                                  max_workers=payload.get("max_workers", 1),
                                  background=background)
    request = workflow.WorkflowRequest.from_dict(payload, base_dir=base_dir)
    function = workflow.submit_job if background else workflow.run_job
    return function(request, workspace=workspace)


def _dispatch(args: argparse.Namespace) -> Any:
    from . import workflow

    command, workspace = args.command, args.workspace
    if command == "context":
        return workflow.context()
    if command == "schema":
        return workflow.schema(args.name)
    if command in {"plan", "run", "submit"}:
        payload, base_dir = load_request(args.request)
        if command == "plan":
            request = workflow.WorkflowRequest.from_dict(payload, base_dir=base_dir)
            return workflow.plan_workflow(request)
        return execute_request(payload, base_dir=base_dir, workspace=workspace,
                               background=command == "submit")
    if command == "list":
        return {"jobs": workflow.list_jobs(workspace=workspace)}
    if command == "events":
        return workflow.read_events(args.run_id, workspace=workspace,
                                    after=args.after, limit=args.limit)
    if command == "result":
        return workflow.get_result(args.run_id, workspace=workspace, table=args.table,
                                   offset=args.offset, limit=args.limit,
                                   verify=not args.no_verify)
    if command == "resume":
        return workflow.resume_job(args.run_id, workspace=workspace,
                                   background=not args.foreground)
    function = workflow.status_job if command == "status" else workflow.cancel_job
    return function(args.run_id, workspace=workspace)


def exit_code(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    state = payload.get("state")
    if state == "partial":
        return 3
    if state in {"cancelled", "interrupted", "blocked", "failed"} or payload.get("ok") is False:
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    from .console import configure_cli_output

    configure_cli_output()
    try:
        args = build_parser().parse_args(argv)
        # Legacy provider progress is diagnostic output, never part of JSON stdout.
        with redirect_stdout(sys.stderr):
            payload = _dispatch(args)
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        code = exit_code(payload)
    except Exception as exc:
        serialized = json.dumps(error_payload(exc), ensure_ascii=False)
        code = 2
    print(serialized)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
