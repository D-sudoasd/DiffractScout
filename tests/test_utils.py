from __future__ import annotations

import importlib.metadata

import diffractscout

from diffractscout.utils import package_versions


def test_package_versions_uses_runtime_diffractscout_version(monkeypatch) -> None:
    def stale_metadata(name: str) -> str:
        if name == "diffractscout":
            return "0.0.0-stale"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", stale_metadata)
    assert package_versions(("diffractscout",))["diffractscout"] == diffractscout.__version__


def test_package_versions_keeps_external_metadata_and_missing_behavior(monkeypatch) -> None:
    def metadata_version(name: str) -> str:
        if name == "gemmi":
            return "9.9.9-fixture"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", metadata_version)
    assert package_versions(("gemmi", "package-that-is-not-installed")) == {
        "gemmi": "9.9.9-fixture",
        "package-that-is-not-installed": "not-installed",
    }
