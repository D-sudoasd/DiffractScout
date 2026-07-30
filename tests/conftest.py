from __future__ import annotations

from pathlib import Path

import pytest

from diffractscout.demo import write_demo_inputs


@pytest.fixture
def demo_inputs(tmp_path: Path) -> Path:
    return write_demo_inputs(tmp_path / "inputs")
