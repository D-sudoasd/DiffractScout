"""Portable task records and operating-system owned, crash-released locks."""
from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterator

from ..pipeline import _reject_reparse_components
from ..utils import utc_now_iso, write_json

TERMINAL = {"completed", "partial", "failed", "blocked", "cancelled", "interrupted"}


def process_alive(pid: int) -> bool:
    """Distinguish an exited worker from a retained Windows process handle."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0 means exited
        finally:
            kernel.CloseHandle(handle)
    # Linux zombie processes still answer kill(pid, 0), but cannot own a task.
    stat_file = Path(f"/proc/{pid}/stat")
    try:
        if stat_file.exists() and stat_file.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return False
    except (OSError, IndexError):
        pass
    from ..pipeline import _process_is_alive
    return _process_is_alive(pid)


def workspace_path(workspace: str | Path | None = None) -> Path:
    path = Path(workspace or Path.cwd() / "outputs" / "agent-workspace").expanduser().absolute()
    _reject_reparse_components(path, label="workflow workspace")
    return path


def job_path(workspace: str | Path | None, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run_id: expected a 32-character hexadecimal task identifier.")
    path = workspace_path(workspace) / "jobs" / run_id
    _reject_reparse_components(path, label="workflow task")
    return path


def read_json(path: Path) -> Any:
    _reject_reparse_components(path, label="workflow record")
    return json.loads(path.read_text(encoding="utf-8"))


@contextlib.contextmanager
def file_lock(path: Path, *, blocking: bool = False) -> Iterator[None]:
    """An open file owns the lock; no PID guessing or lock-file deletion."""
    _reject_reparse_components(path, label="workflow lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except OSError as exc:
            raise BlockingIOError(f"Task is already owned by another worker: {path.parent.name}") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with file_lock(path):
            return False
    except BlockingIOError:
        return True


class RunStore:
    """Only the worker writes state/events; clients write a cancellation marker."""

    def __init__(self, root: Path):
        self.root = root
        self.state = read_json(root / "state.json")
        self._sequence = 0
        event_file = root / "events.jsonl"
        if event_file.exists():
            # A killed writer may leave an incomplete final line. Discard only
            # that line before resuming; valid prior events remain untouched.
            raw = event_file.read_bytes()
            end = raw.rfind(b"\n") + 1
            if end != len(raw):
                with event_file.open("r+b") as stream:
                    stream.truncate(end)
            for line in raw[:end].splitlines():
                self._sequence = max(self._sequence, json.loads(line)["sequence"])

    def update(self, **values: Any) -> dict[str, Any]:
        self.state.update(values)
        self.state["updated_at"] = utc_now_iso()
        write_json(self.root / "state.json", self.state)
        return self.state

    def event(self, event: str, **values: Any) -> None:
        self._sequence += 1
        record = {"sequence": self._sequence, "time": utc_now_iso(), "event": event, **values}
        with (self.root / "events.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def count(self, name: str, amount: int = 1) -> None:
        counters = self.state.setdefault("counters", {})
        counters[name] = counters.get(name, 0) + amount
        self.update(counters=counters)

    def stage(self, name: str, *, completed: int = 0, total: int = 0) -> None:
        self.update(stage=name, completed_items=completed, total_items=total)
        self.event("stage", stage=name, completed_items=completed, total_items=total)


def events_page(root: Path, *, after: int, limit: int) -> dict[str, Any]:
    if after < 0 or not 1 <= limit <= 1000:
        raise ValueError("after must be nonnegative; limit must be between 1 and 1000.")
    rows: list[dict[str, Any]] = []
    path = root / "events.jsonl"
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.endswith("\n"):
                    break
                row = json.loads(line)
                if row["sequence"] > after:
                    rows.append(row)
                    if len(rows) > limit:
                        break
    return {"events": rows[:limit], "next_cursor": rows[min(len(rows), limit)-1]["sequence"] if rows else after,
            "has_more": len(rows) > limit}
