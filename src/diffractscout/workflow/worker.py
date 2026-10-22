"""Detached local worker entry point; no network service or global daemon."""
from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor

from .runner import execute
from .store import job_path, read_json, workspace_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--expected-attempt", type=int)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--batch-id")
    args = parser.parse_args(argv)
    if args.run_id:
        execute(job_path(args.workspace, args.run_id), expected_attempt=args.expected_attempt)
    else:
        if not re.fullmatch(r"[a-f0-9]{32}", args.batch_id):
            raise ValueError("Invalid batch_id.")
        batch = read_json(workspace_path(args.workspace) / "batches" / (args.batch_id + ".json"))
        roots = [job_path(args.workspace, run_id) for run_id in batch["run_ids"]]
        with ThreadPoolExecutor(max_workers=batch["max_workers"]) as pool:
            list(pool.map(lambda root: execute(root, expected_attempt=0),
                          [root for root in roots if read_json(root / "state.json")["state"] == "pending"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
