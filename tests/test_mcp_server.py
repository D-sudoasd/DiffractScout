from __future__ import annotations

import asyncio
import json
from pathlib import Path
import os
import sys
from types import SimpleNamespace

import pytest

import diffractscout
from diffractscout.mcp_server import create_server

mcp = pytest.importorskip("mcp", reason="Install diffractscout[mcp] for protocol tests")
Client, StdioServerParameters = mcp.Client, mcp.StdioServerParameters


@pytest.fixture
def service(monkeypatch):
    class Request:
        @classmethod
        def from_dict(cls, data, base_dir=None):
            return data

    calls = []

    def submit(request, **kwargs):
        calls.append((request, kwargs))
        return {"run_id": "background-job", "state": "pending"}

    def missing(*args, **kwargs):
        raise FileNotFoundError("No such job")

    api = SimpleNamespace(WorkflowRequest=Request,
                          context=lambda: {"workflows": ["analyze"]},
                          schema=lambda name: {"type": "object"},
                          plan_workflow=lambda request: {"stages": ["analyze"]},
                          run_job=lambda request, **kw: {"state": "completed"},
                          submit_job=submit, status_job=missing,
                          list_jobs=lambda **kw: [{"run_id": f"job-{i}"} for i in range(4)],
                          read_events=lambda *args, **kw: {"events": [], **kw},
                          get_result=lambda *args, **kw: {"rows": [], **kw},
                          resume_job=lambda *args, **kw: {"state": "pending"},
                          cancel_job=lambda *args, **kw: {"state": "cancelling"})
    monkeypatch.setattr(diffractscout, "workflow", api, raising=False)
    return api, calls


def test_sdk_tools_metadata_structured_results_and_errors(service):
    async def exercise():
        async with Client(create_server()) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools) == {"context", "schema", "plan", "run", "submit", "list_jobs",
                                  "status", "events", "resume", "cancel", "result"}
            assert tools["context"].annotations.read_only_hint is True
            assert tools["submit"].annotations.read_only_hint is False
            assert tools["result"].input_schema["properties"]["limit"]["maximum"] == 1000
            assert tools["list_jobs"].input_schema["properties"]["offset"]["minimum"] == 0
            assert tools["context"].output_schema["type"] == "object"
            context = await client.call_tool("context")
            assert context.structured_content == {"workflows": ["analyze"]}
            submitted = await client.call_tool("submit", {"request": {"workflow": "analyze"}})
            assert submitted.structured_content["state"] == "pending"
            assert len(service[1]) == 1
            page = await client.call_tool("list_jobs", {"offset": 1, "limit": 2})
            assert page.structured_content["jobs"] == [{"run_id": "job-1"}, {"run_id": "job-2"}]
            assert page.structured_content["next_offset"] == 3
            missing = await client.call_tool("status", {"run_id": "absent"})
            assert missing.is_error
            assert missing.structured_content["error"]["type"] == "FileNotFoundError"
            invalid = await client.call_tool("events", {"run_id": "x", "limit": 0})
            assert invalid.is_error
    asyncio.run(exercise())


def test_real_stdio_client_context_schema_submit_and_missing_job(tmp_path, demo_inputs):
    async def exercise():
        source = Path(__file__).parents[1] / "src"
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "diffractscout.mcp_server"],
            env={**os.environ, "PYTHONPATH": str(source)}, cwd=str(tmp_path),
        )
        async with Client(parameters, read_timeout_seconds=20) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert {"context", "schema", "submit", "result"} <= tools
            context = await client.call_tool("context")
            assert not context.is_error
            assert isinstance(context.structured_content, dict)
            schema = await client.call_tool("schema")
            assert not schema.is_error
            assert isinstance(schema.structured_content, dict)
            missing = await client.call_tool("status", {"run_id": "missing",
                                                        "workspace": str(tmp_path / "jobs")})
            assert missing.is_error
            assert "error" in missing.structured_content
            json.loads(missing.content[0].text)
            submitted = await client.call_tool("submit", {
                "workspace": str(tmp_path / "jobs"), "request": {
                    "schema": "diffractscout_workflow_v1", "workflow": "analyze",
                    "inputs": [str(demo_inputs)], "output_dir": str(tmp_path / "bundle"),
                    "analysis": {"include_elasticity": False, "include_patterns": False},
                    "exports": {"include_excel": False},
                }})
            assert not submitted.is_error, submitted.content
            run_id = submitted.structured_content["run_id"]
            for _ in range(200):
                status = await client.call_tool("status", {"run_id": run_id,
                                                          "workspace": str(tmp_path / "jobs")})
                assert not status.is_error
                if status.structured_content["state"] not in {"pending", "running"}:
                    break
                await asyncio.sleep(0.05)
            assert status.structured_content["state"] == "completed", status.structured_content
            result = await client.call_tool("result", {"run_id": run_id,
                                                      "workspace": str(tmp_path / "jobs")})
            assert not result.is_error, result.content
            assert isinstance(result.structured_content, dict)
    asyncio.run(exercise())
