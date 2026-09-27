"""Keep legacy environment-mutating GUI tests isolated from the main suite."""
import os

import pytest


@pytest.fixture(autouse=True)
def restore_tk_environment():
    keys = ("TCL_LIBRARY", "TK_LIBRARY")
    before = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
