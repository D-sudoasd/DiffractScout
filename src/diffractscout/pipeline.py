"""High-level local-analysis, discovery, and end-to-end workflows."""

from __future__ import annotations

import errno
import ctypes
import json
import math
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

import numpy as np

from .composition import parse_composition_text
from .diffraction import simulate_powder_pattern, validate_analysis_settings
from .elasticity import (
    discover_elastic_tensor,
    load_elastic_tensor_for_cif,
    normalize_elasticity_sidecar,
    validate_elastic_tensor,
)
from .exporters import export_result_bundle
from .models import (
    AnalysisSettings,
    DiagnosticRecord,
    DiscoveryResult,
    DownloadArtifact,
    DiscoverySettings,
    ElasticTensor,
    PhaseAnalysis,
    PipelineResult,
)
from .providers.base import PhaseProvider
from .selection import search_candidates
from .structure import load_structure
from .utils import sha256_file, slugify
from .validation import verify_bundle


def collect_cif_paths(inputs: Sequence[str | Path], *, recursive: bool = True) -> list[Path]:
    """Collect readable CIF files with case-insensitive suffix handling.

    ``Path.glob('*.cif')`` is case-sensitive on common Linux filesystems. A
    directory walk followed by a suffix check keeps command-line and GUI
    behavior consistent for ``.cif``, ``.CIF``, and mixed-case variants.
    """

    output: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input path does not exist: {path}")
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            candidates = sorted(
                (
                    value
                    for value in iterator
                    if value.is_file() and value.suffix.lower() == ".cif"
                ),
                key=lambda value: str(value).lower(),
            )
        else:
            if path.suffix.lower() != ".cif":
                raise ValueError(f"Explicit input file is not a CIF: {path}")
            candidates = [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.suffix.lower() == ".cif" and resolved.is_file() and resolved not in seen:
                output.append(resolved)
                seen.add(resolved)
    return output


def _unique_input_target(cif_path: Path, inputs_dir: Path, digest: str) -> Path:
    """Choose a deterministic, collision-safe filename inside a result bundle."""

    suffix = ".cif"
    preferred = inputs_dir / f"{cif_path.stem}{suffix}"
    if not preferred.exists():
        return preferred

    candidate = inputs_dir / f"{cif_path.stem}_{digest[:8]}{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = inputs_dir / f"{cif_path.stem}_{digest[:8]}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _validate_input_output_separation(
    inputs: Sequence[str | Path], output_dir: str | Path
) -> None:
    """Reject input/output overlap before an overwrite can remove source data."""

    target = Path(output_dir).expanduser().resolve()
    for item in inputs:
        source = Path(item).expanduser().resolve()
        if source == target or source.is_relative_to(target) or target.is_relative_to(source):
            raise ValueError(
                "Input and output paths must be disjoint. "
                f"Unsafe overlap: input={source}, output={target}."
            )


_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    """Return whether *path* is a symlink or Windows reparse point.

    ``Path.is_junction`` was added after Python 3.10 and is not available in
    all supported runtimes.  ``st_file_attributes`` is exposed by Windows
    ``stat`` results on those runtimes, while remaining absent on POSIX.
    """

    try:
        stat_result = path.stat(follow_symlinks=False)
    except (OSError, TypeError):
        try:
            stat_result = path.lstat()
        except OSError:
            return path.is_symlink()
    return path.is_symlink() or bool(
        getattr(stat_result, "st_file_attributes", 0)
        & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _reject_reparse_components(path: Path, *, label: str) -> None:
    """Reject symlink/junction/reparse components before resolving a path."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    components: list[Path] = []
    current = absolute
    while True:
        components.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for component in reversed(components):
        if component.exists() or component.is_symlink():
            if _is_reparse_point(component):
                raise FileExistsError(
                    f"Refusing to use a symbolic-link or Windows reparse-point {label}: {component}"
                )


def _validate_output_target(output_dir: str | Path, *, overwrite: bool) -> Path:
    raw = Path(output_dir).expanduser()
    _reject_reparse_components(raw, label="output directory")
    output = raw.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"Output path exists and is not a directory: {output}")
    if output.exists() and any(output.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Output directory is not empty: {output}. Choose a new directory or pass overwrite=True."
            )
        manifest = output / "manifest.json"
        if not manifest.is_file():
            raise FileExistsError(
                f"Refusing to overwrite a non-empty directory without a DiffractScout manifest: {output}"
            )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(
                f"Refusing to overwrite output with an unreadable manifest: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema") != "diffractscout_bundle_manifest_v1":
            raise FileExistsError("Refusing to overwrite output with an unknown manifest schema.")
        verification = verify_bundle(output)
        if not verification["ok"]:
            details = "; ".join(verification["errors"][:5])
            raise FileExistsError(
                "Refusing to overwrite an existing DiffractScout bundle that fails integrity "
                f"verification: {details}"
            )
    return output


def _create_staging_output(target: Path) -> Path:
    return Path(
        tempfile.mkdtemp(prefix=f".{target.name}.diffractscout-", dir=str(target.parent))
    ).resolve()


@dataclass(frozen=True)
class _TargetState:
    """Identity and observable contents captured for a commit precondition."""

    exists: bool
    is_dir: bool = False
    identity: tuple[int, int] | None = None
    manifest_sha256: str | None = None
    manifest_size: int | None = None
    members: tuple[tuple[str, int, str], ...] | None = None
    reparse: bool = False


def _record_transaction_warning(
    message: str,
    warning_sink: list[str] | None = None,
) -> None:
    if warning_sink is not None:
        warning_sink.append(message)
    try:
        warnings.warn(message, RuntimeWarning, stacklevel=3)
    except Exception:
        # Diagnostics must never replace the active transaction exception.
        pass


def _add_exception_note(error: BaseException, message: str) -> None:
    """Attach rollback context when the runtime supports ``add_note``."""

    add_note = getattr(error, "add_note", None)
    if not callable(add_note):
        return
    try:
        add_note(message)
    except Exception:
        # A diagnostic must never replace the active transaction exception.
        pass


def _safe_unlink(
    path: Path,
    *,
    warning_sink: list[str] | None = None,
    context: str = "temporary file",
) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _record_transaction_warning(
            f"Could not remove {context} {path}: {type(exc).__name__}: {exc}",
            warning_sink,
        )


def _safe_rmtree(
    path: Path,
    *,
    warning_sink: list[str] | None = None,
    context: str = "directory",
) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _record_transaction_warning(
            f"Could not remove {context} {path}: {type(exc).__name__}: {exc}",
            warning_sink,
        )


def _path_exists(path: Path) -> bool:
    """Return true for ordinary paths and dangling links alike."""

    try:
        return path.exists() or path.is_symlink()
    except OSError:
        # An inaccessible path must never be treated as vacant.
        return True


def _bundle_member_fingerprint(
    target: Path,
    *,
    manifest_name: str = "manifest.json",
) -> tuple[tuple[str, int, str], ...] | None:
    """Fingerprint every manifest-declared member of a verified bundle.

    Normal result bundles continue to use :func:`verify_bundle`.  Benchmark
    bundles intentionally use a different manifest name/schema, but the
    transaction expected-state contract still needs the same member-level
    digest protection.  The small generic reader below is limited to the
    shared ``files``/``path``/``size_bytes``/``sha256`` shape.
    """

    manifest = target / manifest_name
    if not _path_exists(manifest):
        if manifest_name != "manifest.json":
            try:
                has_entries = any(target.iterdir())
            except OSError as exc:
                raise FileExistsError(
                    f"Cannot inspect benchmark target without {manifest_name}: {target}."
                ) from exc
            if has_entries:
                raise FileExistsError(
                    f"Benchmark target has files but no {manifest_name}: {target}."
                )
        return None
    if manifest_name == "manifest.json":
        report = verify_bundle(target)
        if not report["ok"]:
            details = "; ".join(report["errors"][:5])
            raise FileExistsError(
                f"Cannot fingerprint an unverifiable output target {target}: {details}"
            )
        entries = report["files"]
    else:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileExistsError(
                f"Cannot fingerprint an unreadable output target manifest {manifest}: {exc}"
            ) from exc
        entries = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise FileExistsError(
                f"Cannot fingerprint malformed output target manifest {manifest}."
            )
    members: list[tuple[str, int, str]] = []
    declared_paths: set[str] = set()
    for entry in entries:
        try:
            relative = str(entry["path"])
            if manifest_name == "manifest.json":
                size = int(entry["actual_size_bytes"])
                digest = str(entry["actual_sha256"])
            else:
                size = int(entry["size_bytes"])
                digest = str(entry["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FileExistsError(
                f"Cannot fingerprint malformed output target {target}."
            ) from exc
        relative_path = Path(relative)
        normalized = relative_path.as_posix()
        if (
            not relative
            or relative_path.is_absolute()
            or normalized == "."
            or ".." in relative_path.parts
            or any(part in {"", "."} for part in relative_path.parts)
            or normalized == manifest_name
        ):
            raise FileExistsError(
                f"Cannot fingerprint unsafe manifest path {relative!r} in {manifest}."
            )
        if manifest_name != "manifest.json" and normalized in declared_paths:
            raise FileExistsError(
                f"Duplicate benchmark manifest path: {normalized}."
            )
        declared_paths.add(normalized)
        member = target.joinpath(*relative_path.parts)
        try:
            _reject_reparse_components(member, label="manifest member")
            resolved = member.resolve(strict=False)
            resolved.relative_to(target.resolve())
        except (OSError, ValueError) as exc:
            raise FileExistsError(
                f"Cannot fingerprint unsafe manifest member {relative!r} in {target}."
            ) from exc
        if not member.is_file():
            raise FileExistsError(
                f"Cannot fingerprint missing manifest member {relative!r} in {target}."
            )
        try:
            actual_size = member.stat().st_size
            actual_digest = sha256_file(member)
        except OSError as exc:
            raise FileExistsError(
                f"Cannot fingerprint unreadable manifest member {relative!r} in {target}."
            ) from exc
        if actual_size != size or actual_digest != digest:
            raise FileExistsError(
                f"Cannot fingerprint changed manifest member {relative!r} in {target}."
            )
        members.append((normalized, actual_size, actual_digest))
    if manifest_name != "manifest.json":
        # Benchmark targets use a different manifest schema, so the normal
        # result-bundle verifier is not available as the final guard.  The
        # expected state must nevertheless cover every actual file: an
        # unlisted external file must stop the transaction before isolation.
        actual: set[str] = set()
        try:
            for path in target.rglob("*"):
                if path == manifest:
                    continue
                _reject_reparse_components(path, label="manifest member")
                if path.is_file():
                    actual.add(path.relative_to(target).as_posix())
        except (OSError, ValueError) as exc:
            raise FileExistsError(
                f"Cannot enumerate actual files for benchmark target {target}."
            ) from exc
        declared = {item[0] for item in members}
        if actual != declared:
            extras = sorted(actual - declared)
            missing = sorted(declared - actual)
            details: list[str] = []
            if extras:
                details.append(f"unlisted files: {', '.join(extras[:5])}")
            if missing:
                details.append(f"missing files: {', '.join(missing[:5])}")
            raise FileExistsError(
                f"Benchmark target files differ from its manifest: {'; '.join(details)}."
            )
    return tuple(sorted(members))


def _target_identity(stat_result: os.stat_result) -> tuple[int, int]:
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
    )


def _capture_target_state(
    target: Path,
    *,
    manifest_name: str = "manifest.json",
) -> _TargetState:
    """Capture a target state without following the target itself."""

    try:
        stat_result = target.stat(follow_symlinks=False)
    except FileNotFoundError:
        try:
            stat_result = target.lstat()
        except (FileNotFoundError, OSError, AttributeError):
            try:
                dangling = target.is_symlink()
            except OSError:
                dangling = True
            if dangling:
                return _TargetState(exists=True, reparse=True)
            return _TargetState(exists=False)
    except (OSError, TypeError):
        try:
            stat_result = target.lstat()
        except (FileNotFoundError, OSError, AttributeError) as exc:
            raise OSError(f"Could not inspect output target {target}.") from exc

    try:
        reparse = _is_reparse_point(target)
    except (OSError, TypeError, AttributeError):
        reparse = bool(getattr(target, "is_symlink", lambda: False)())
    identity = _target_identity(stat_result)
    if reparse:
        return _TargetState(
            exists=True,
            identity=identity,
            reparse=True,
        )

    is_dir = stat.S_ISDIR(getattr(stat_result, "st_mode", 0))
    if not is_dir:
        return _TargetState(
            exists=True,
            is_dir=False,
            identity=identity,
        )

    manifest = target / manifest_name
    manifest_sha256: str | None = None
    manifest_size: int | None = None
    if _path_exists(manifest):
        try:
            manifest_sha256 = sha256_file(manifest)
            manifest_size = manifest.stat().st_size
        except OSError as exc:
            raise FileExistsError(
                f"Cannot read output target manifest for {target}."
            ) from exc
    return _TargetState(
        exists=True,
        is_dir=True,
        identity=identity,
        manifest_sha256=manifest_sha256,
        manifest_size=manifest_size,
        members=_bundle_member_fingerprint(target, manifest_name=manifest_name),
    )


def _lock_path_for(target: Path) -> Path:
    return target.parent / f".{target.name}.diffractscout-lock"


def _lock_host() -> str:
    return socket.gethostname()


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if getattr(exc, "winerror", None) == 87:  # ERROR_INVALID_PARAMETER: no such PID
            return False
        # Permission denied and platform-specific errors are ambiguous; never
        # remove a lock that might still belong to a live process.
        return True
    return True


def _lock_snapshot(lock_path: Path) -> tuple[bytes, tuple[int, int, int]]:
    raw = lock_path.read_bytes()
    stat_result = lock_path.stat(follow_symlinks=False)
    identity = (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
        int(getattr(stat_result, "st_size", 0)),
    )
    return raw, identity


def _restore_isolated_transaction_lock(
    isolated_path: Path,
    lock_path: Path,
    raw: bytes | None,
    warning_sink: list[str] | None = None,
) -> None:
    """Restore an isolated lock without replacing a lock that won the race."""

    try:
        os.link(os.fspath(isolated_path), os.fspath(lock_path))
    except FileExistsError:
        # The current path is another lock.  Keep both objects rather than
        # replacing the live lock or deleting the isolated one.
        _record_transaction_warning(
            f"Transaction lock {lock_path} appeared while restoring {isolated_path}; "
            "preserving both locks.",
            warning_sink,
        )
        return
    except FileNotFoundError:
        _record_transaction_warning(
            f"Isolated transaction lock {isolated_path} disappeared while restoring; "
            f"leaving {lock_path} untouched.",
            warning_sink,
        )
        return
    except OSError:
        # Hardlinks are unavailable on some filesystems.  O_EXCL still makes
        # this fallback no-replace; the isolated object remains until the
        # restored copy is complete.
        if raw is None:
            _record_transaction_warning(
                f"Could not restore isolated transaction lock {isolated_path} to "
                f"{lock_path} without verifying its contents; isolated lock preserved.",
                warning_sink,
            )
            return
        descriptor: int | None = None
        try:
            descriptor = os.open(
                os.fspath(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            return
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            _record_transaction_warning(
                f"Could not restore changed transaction lock {lock_path}: "
                f"{type(exc).__name__}: {exc}; isolated lock preserved at {isolated_path}.",
                warning_sink,
            )
            return

    _safe_unlink(
        isolated_path,
        warning_sink=warning_sink,
        context="isolated transaction lock",
    )


def _read_lock_metadata(lock_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FileExistsError(
            f"Active transaction lock {lock_path} has unreadable metadata; "
            "refusing unsafe recovery."
        ) from exc
    if not isinstance(payload, dict):
        raise FileExistsError(
            f"Active transaction lock {lock_path} has ambiguous metadata; "
            "refusing unsafe recovery."
        )
    host = payload.get("host")
    pid = payload.get("pid")
    created_at = payload.get("created_at")
    if (
        not isinstance(host, str)
        or not host.strip()
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(created_at, bool)
        or not isinstance(created_at, (int, float))
        or not math.isfinite(float(created_at))
        or float(created_at) > time.time() + 5.0
    ):
        raise FileExistsError(
            f"Active transaction lock {lock_path} has ambiguous metadata; "
            "refusing unsafe recovery."
        )
    return {"host": host, "pid": pid, "created_at": float(created_at)}


def _recover_stale_transaction_lock(
    lock_path: Path,
    warning_sink: list[str] | None = None,
) -> bool:
    """Recover a lock only after same-host owner death is proven."""

    try:
        raw, identity = _lock_snapshot(lock_path)
    except FileNotFoundError:
        return True
    metadata = _read_lock_metadata(lock_path)
    if metadata["host"].casefold() != _lock_host().casefold():
        raise FileExistsError(
            f"Transaction lock {lock_path} belongs to another host; "
            "refusing unsafe recovery."
        )
    if _process_is_alive(metadata["pid"]):
        raise FileExistsError(
            f"Output transaction is already active (pid={metadata['pid']}) for {lock_path}."
        )

    try:
        current_raw, current_identity = _lock_snapshot(lock_path)
    except FileNotFoundError:
        return True
    if current_raw != raw or current_identity != identity:
        raise FileExistsError(
            f"Transaction lock {lock_path} changed during stale recovery; "
            "retry after confirming the owner."
        )

    quarantine = lock_path.with_name(f"{lock_path.name}.stale-{uuid4().hex}")
    try:
        lock_path.replace(quarantine)
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise FileExistsError(
            f"Could not isolate stale transaction lock {lock_path}; "
            "refusing unsafe recovery."
        ) from exc

    try:
        moved_raw = quarantine.read_bytes()
        if moved_raw != raw:
            if not _path_exists(lock_path):
                try:
                    quarantine.replace(lock_path)
                except OSError as exc:
                    _record_transaction_warning(
                        f"Could not restore changed transaction lock {lock_path}: {exc}",
                        warning_sink,
                    )
            raise FileExistsError(
                f"Transaction lock {lock_path} changed while being isolated; "
                "the lock was preserved."
            )
        if _path_exists(lock_path):
            # A new owner won the race after the stale file was isolated.  The
            # old owner is proven dead, so removing only the quarantine is safe.
            _safe_unlink(
                quarantine,
                warning_sink=warning_sink,
                context="stale lock quarantine",
            )
            raise FileExistsError(
                f"A new transaction acquired {lock_path} during stale recovery; "
                "the live lock was preserved."
            )
        _safe_unlink(
            quarantine,
            warning_sink=warning_sink,
            context="stale lock quarantine",
        )
        return True
    except FileNotFoundError as exc:
        raise FileExistsError(
            f"Stale transaction lock quarantine {quarantine} disappeared; "
            "refusing unsafe recovery."
        ) from exc


def _acquire_transaction_lock(
    target: Path,
    *,
    warning_sink: list[str] | None = None,
) -> Path:
    """Create an exclusive lock marker with conservative stale recovery."""

    lock_path = _lock_path_for(target)
    for _attempt in range(3):
        try:
            descriptor = os.open(
                os.fspath(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            if _recover_stale_transaction_lock(lock_path, warning_sink):
                continue
            raise FileExistsError(f"Output transaction lock is unavailable: {lock_path}.")

        descriptor_open = True
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor_open = False
                json.dump(
                    {
                        "version": 1,
                        "host": _lock_host(),
                        "pid": os.getpid(),
                        "created_at": time.time(),
                    },
                    handle,
                    sort_keys=True,
                )
                handle.write("\n")
        except Exception:
            if descriptor_open:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            _safe_unlink(
                lock_path,
                warning_sink=warning_sink,
                context="partially written transaction lock",
            )
            raise
        return lock_path
    raise FileExistsError(f"Could not acquire output transaction lock {lock_path}.")


def _release_transaction_lock(
    lock_path: Path,
    *,
    warning_sink: list[str] | None = None,
) -> None:
    """Release a lock without masking a commit result or primary error."""

    try:
        raw, identity = _lock_snapshot(lock_path)
    except FileNotFoundError:
        return
    except OSError as exc:
        _record_transaction_warning(
            f"Could not inspect transaction lock {lock_path} before release: "
            f"{type(exc).__name__}: {exc}",
            warning_sink,
        )
        return

    try:
        metadata = _read_lock_metadata(lock_path)
    except FileNotFoundError:
        return
    except FileExistsError as exc:
        _record_transaction_warning(str(exc), warning_sink)
        return
    if (
        metadata["host"].casefold() != _lock_host().casefold()
        or metadata["pid"] != os.getpid()
    ):
        _record_transaction_warning(
            f"Transaction lock {lock_path} is owned by another process; "
            "leaving it in place.",
            warning_sink,
        )
        return

    try:
        current_raw, current_identity = _lock_snapshot(lock_path)
    except FileNotFoundError:
        _record_transaction_warning(
            f"Transaction lock {lock_path} disappeared during release; "
            "leaving the current lock untouched.",
            warning_sink,
        )
        return
    except OSError as exc:
        _record_transaction_warning(
            f"Could not verify transaction lock {lock_path} before release: "
            f"{type(exc).__name__}: {exc}; leaving it in place.",
            warning_sink,
        )
        return
    if current_raw != raw or current_identity != identity:
        _record_transaction_warning(
            f"Transaction lock {lock_path} changed during release; "
            "leaving the current lock in place.",
            warning_sink,
        )
        return

    quarantine = lock_path.with_name(f"{lock_path.name}.release-{uuid4().hex}")
    try:
        # Isolate the exact directory entry atomically before removing it.  A
        # replacement that wins after the last snapshot is moved instead and
        # is detected below, rather than being unlinked in place.
        lock_path.replace(quarantine)
    except FileNotFoundError:
        _record_transaction_warning(
            f"Transaction lock {lock_path} disappeared during release; "
            "leaving the current lock untouched.",
            warning_sink,
        )
        return
    except OSError as exc:
        _record_transaction_warning(
            f"Could not isolate transaction lock {lock_path}: "
            f"{type(exc).__name__}: {exc}; leaving it in place.",
            warning_sink,
        )
        return

    try:
        isolated_raw, isolated_identity = _lock_snapshot(quarantine)
    except FileNotFoundError:
        _record_transaction_warning(
            f"Isolated transaction lock {quarantine} disappeared during release; "
            "refusing unsafe cleanup.",
            warning_sink,
        )
        return
    except OSError as exc:
        _record_transaction_warning(
            f"Could not verify isolated transaction lock {quarantine}: "
            f"{type(exc).__name__}: {exc}; preserving it.",
            warning_sink,
        )
        _restore_isolated_transaction_lock(quarantine, lock_path, None, warning_sink)
        return

    if isolated_raw != raw or isolated_identity != identity:
        _record_transaction_warning(
            f"Transaction lock {lock_path} changed while being isolated; "
            "preserving the current lock.",
            warning_sink,
        )
        _restore_isolated_transaction_lock(quarantine, lock_path, isolated_raw, warning_sink)
        return

    _safe_unlink(
        quarantine,
        warning_sink=warning_sink,
        context="transaction lock",
    )


def _attempt_restore_backup(
    backup: Path | None,
    target: Path,
    *,
    primary_error: BaseException | None = None,
    warning_sink: list[str] | None = None,
) -> None:
    """Restore an isolated target only while its path is still vacant."""

    if backup is None or not _path_exists(backup):
        return
    if _path_exists(target):
        message = (
            f"Rollback conflict for {target}: target reappeared; "
            f"isolated backup preserved at {backup}."
        )
        _record_transaction_warning(message, warning_sink)
        if primary_error is not None:
            _add_exception_note(primary_error, message)
        return
    try:
        _rename_directory_noreplace(backup, target)
    except Exception as exc:
        message = (
            f"Could not restore isolated backup {backup} to {target}: "
            f"{type(exc).__name__}: {exc}; backup was preserved."
        )
        _record_transaction_warning(message, warning_sink)
        if primary_error is not None:
            _add_exception_note(primary_error, message)


def _raise_publication_error(
    error_number: int,
    source: Path,
    target: Path,
    *,
    operation: str,
) -> None:
    message = f"Atomic no-replace directory publication failed ({operation}): {source} -> {target}"
    if error_number == errno.EEXIST:
        raise FileExistsError(errno.EEXIST, message, os.fspath(target))
    raise OSError(error_number or errno.EIO, message, os.fspath(target))


def _rename_directory_noreplace_windows(source: Path, target: Path) -> None:
    """Use Windows' documented no-replace behavior for ``os.rename``."""

    try:
        os.rename(os.fspath(source), os.fspath(target))
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno == errno.EEXIST or getattr(exc, "winerror", None) in {80, 183}:
            _raise_publication_error(
                errno.EEXIST,
                source,
                target,
                operation="Windows no-replace rename",
            )
        raise


def _rename_directory_noreplace_linux(source: Path, target: Path) -> None:
    """Call libc ``renameat2(..., RENAME_NOREPLACE)`` without raw syscalls."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2")
    except (AttributeError, OSError) as exc:
        raise OSError(
            errno.ENOTSUP,
            "Linux atomic directory no-replace primitive renameat2 is unavailable; "
            "refusing a racy publication.",
        ) from exc
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    at_fdcwd = getattr(os, "AT_FDCWD", -100)
    result = renameat2(
        at_fdcwd,
        os.fsencode(source),
        at_fdcwd,
        os.fsencode(target),
        1,  # Linux RENAME_NOREPLACE, a documented renameat2 flag.
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    _raise_publication_error(
        error_number or errno.EIO,
        source,
        target,
        operation="Linux renameat2 RENAME_NOREPLACE",
    )


def _rename_directory_noreplace_macos(source: Path, target: Path) -> None:
    """Call macOS ``renamex_np(..., RENAME_EXCL)`` through libc."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError as exc:
        raise OSError(
            errno.ENOTSUP,
            "macOS atomic directory no-replace libc is unavailable; "
            "refusing a racy publication.",
        ) from exc

    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    try:
        renamex_np = getattr(libc, "renamex_np")
    except AttributeError:
        try:
            renameatx_np = getattr(libc, "renameatx_np")
        except AttributeError as exc:
            raise OSError(
                errno.ENOTSUP,
                "macOS atomic directory no-replace primitive renamex_np/renameatx_np "
                "is unavailable; refusing a racy publication.",
            ) from exc
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(-2, source_bytes, -2, target_bytes, 0x00000004)
    else:
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_bytes, target_bytes, 0x00000004)
    if result == 0:
        return
    error_number = ctypes.get_errno()
    _raise_publication_error(
        error_number or errno.EIO,
        source,
        target,
        operation="macOS renamex_np/renameatx_np RENAME_EXCL",
    )


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Publish a directory with an atomic, no-replace primitive."""

    if os.name == "nt":
        _rename_directory_noreplace_windows(source, target)
        return
    if sys.platform.startswith("linux"):
        _rename_directory_noreplace_linux(source, target)
        return
    if sys.platform == "darwin":
        _rename_directory_noreplace_macos(source, target)
        return
    raise OSError(
        errno.ENOTSUP,
        f"Atomic directory no-replace publication is unsupported on {sys.platform!r}; "
        "refusing a racy rename.",
    )


def _commit_staging_output(
    target: Path,
    staging: Path,
    *,
    expected_state: _TargetState | None = None,
    warning_sink: list[str] | None = None,
    manifest_name: str = "manifest.json",
) -> None:
    """Commit a verified staging tree without deleting a changed target."""

    def capture(path: Path) -> _TargetState:
        # Keep the historical one-argument call shape for default result
        # bundles; tests and callers monkeypatch this diagnostic seam.
        if manifest_name == "manifest.json":
            return _capture_target_state(path)
        return _capture_target_state(path, manifest_name=manifest_name)

    if expected_state is None:
        expected_state = capture(target)
    lock_path = _acquire_transaction_lock(target, warning_sink=warning_sink)
    backup: Path | None = None
    committed = False
    primary_error: BaseException | None = None
    try:
        current = capture(target)
        if current.reparse:
            raise FileExistsError(
                f"Output target is a symbolic link or reparse point: {target}."
            )
        if current != expected_state:
            raise FileExistsError(
                f"Output target changed during analysis; refusing to replace {target}."
            )

        if _path_exists(target):
            backup = target.with_name(f".{target.name}.backup-{uuid4().hex}")
            # Directory replacement is atomic on the same filesystem.  The
            # backup is retained until the new target has been published.
            target.replace(backup)
            isolated = capture(backup)
            if isolated.reparse:
                raise FileExistsError(
                    f"Isolated output target is a symbolic link or reparse point: {backup}."
                )
            if _path_exists(target):
                raise FileExistsError(
                    f"Rollback conflict for {target}: target reappeared; "
                    f"isolated backup preserved at {backup}."
                )
            if isolated != expected_state:
                raise FileExistsError(
                    f"Output target changed while being isolated; "
                    f"backup preserved at {backup}."
                )

        # Re-check immediately before the platform adapter's atomic
        # no-replace directory publication if an external writer wins this
        # last race.
        current = capture(target)
        if current.reparse:
            raise FileExistsError(
                f"Output target is a symbolic link or reparse point: {target}."
            )
        if current.exists:
            raise FileExistsError(
                f"Output target appeared during commit; refusing to replace {target}."
            )
        try:
            _rename_directory_noreplace(staging, target)
        except Exception as exc:
            primary_error = exc
            _attempt_restore_backup(
                backup,
                target,
                primary_error=exc,
                warning_sink=warning_sink,
            )
            backup = None
            raise
        committed = True
    except Exception as exc:
        primary_error = primary_error or exc
        raise
    finally:
        if committed:
            if backup is not None:
                _safe_rmtree(
                    backup,
                    warning_sink=warning_sink,
                    context="published transaction backup",
                )
        elif backup is not None:
            _attempt_restore_backup(
                backup,
                target,
                primary_error=primary_error,
                warning_sink=warning_sink,
            )
        try:
            _release_transaction_lock(lock_path, warning_sink=warning_sink)
        except Exception as exc:
            _record_transaction_warning(
                f"Transaction lock cleanup failed for {lock_path}: "
                f"{type(exc).__name__}: {exc}",
                warning_sink,
            )


def _lookup_elastic_override(
    cif_path: Path,
    overrides: Mapping[str, ElasticTensor] | None,
) -> ElasticTensor | None:
    """Match an override by canonical path, then an unambiguous legacy key.

    GUI state uses the canonical absolute CIF path so two files with the same
    basename cannot inherit one another's tensor.  Filename/stem keys remain
    supported for older callers, but a simultaneous ``name`` and ``stem``
    match is treated as ambiguous rather than selected by iteration order.
    """

    if not overrides:
        return None
    canonical = Path(cif_path).expanduser().resolve()
    canonical_text = str(canonical)
    # Prefer an exact key first, then tolerate equivalent absolute spellings
    # (for example case differences on Windows) without interpreting a stem
    # such as ``C`` as a path.
    if canonical_text in overrides:
        return overrides[canonical_text]
    absolute_matches: list[ElasticTensor] = []
    for key, tensor in overrides.items():
        try:
            key_path = Path(str(key)).expanduser()
        except (TypeError, ValueError):
            continue
        if not key_path.is_absolute():
            continue
        try:
            if key_path.resolve() == canonical:
                absolute_matches.append(tensor)
        except OSError:
            continue
    if len(absolute_matches) == 1:
        return absolute_matches[0]
    if len(absolute_matches) > 1:
        return None

    legacy_matches = [
        tensor
        for key, tensor in overrides.items()
        if str(key) in {cif_path.name, cif_path.stem}
    ]
    if len(legacy_matches) == 1:
        return legacy_matches[0]
    return None


def _revalidate_user_tensor(tensor: ElasticTensor) -> ElasticTensor:
    """Re-run validation so overrides cannot bypass stiffness checks."""

    return validate_elastic_tensor(
        tensor.stiffness_GPa,
        source_provider=tensor.source_provider or "user_input",
        source_record_id=tensor.source_record_id,
        source_url=tensor.source_url,
        methodology_url=tensor.methodology_url,
        nature_of_data=tensor.nature_of_data or "user_input",
        coordinate_frame=tensor.coordinate_frame,
        raw_payload_path=tensor.raw_payload_path,
    )


_HARDLINK_UNSUPPORTED_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EPERM", None),
        getattr(errno, "EXDEV", None),
        getattr(errno, "ENOSYS", None),
        getattr(errno, "EINVAL", None),
    )
    if value is not None
)


def _hardlink_unsupported(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or exc.errno in _HARDLINK_UNSUPPORTED_ERRNOS


def _publish_private_snapshot(
    temporary: Path,
    candidate: Path,
    *,
    expected_digest: str,
    expected_size: int,
    warning_sink: list[str] | None = None,
) -> bool:
    """Publish a private snapshot without replacing a candidate path."""

    try:
        os.link(os.fspath(temporary), os.fspath(candidate))
        return True
    except FileExistsError:
        return False
    except OSError as exc:
        if not _hardlink_unsupported(exc):
            raise

    # Hardlinks are unavailable on some filesystems.  O_EXCL keeps this
    # fallback no-overwrite, while the file remains private to the staging
    # directory and is verified before the caller exports a manifest.
    descriptor: int | None = None
    try:
        descriptor = os.open(
            os.fspath(candidate),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            with temporary.open("rb") as source:
                shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        if (
            sha256_file(candidate) != expected_digest
            or candidate.stat().st_size != expected_size
        ):
            raise OSError("Published provider snapshot failed integrity verification.")
        return True
    except FileExistsError:
        return False
    except Exception:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _safe_unlink(
            candidate,
            warning_sink=warning_sink,
            context="partial snapshot fallback",
        )
        raise


def _copy_local_snapshot(
    source: Path,
    candidate: Path,
    *,
    expected_digest: str,
    expected_size: int,
) -> Path:
    """Copy one local CIF through a verified private snapshot."""

    candidate.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{candidate.name}-",
        suffix=".tmp",
        dir=str(candidate.parent),
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        os.close(descriptor)
        descriptor_open = False
        shutil.copy2(source, temporary)
        source_after_digest = sha256_file(source)
        source_after_size = source.stat().st_size
        if (
            sha256_file(temporary) != expected_digest
            or temporary.stat().st_size != expected_size
            or source_after_digest != expected_digest
            or source_after_size != expected_size
        ):
            raise RuntimeError(
                f"Local CIF source changed while being copied: {source}."
            )
        if _path_exists(candidate):
            raise FileExistsError(
                f"Local CIF staging target appeared during copy: {candidate}."
            )
        if not _publish_private_snapshot(
            temporary,
            candidate,
            expected_digest=expected_digest,
            expected_size=expected_size,
        ):
            raise FileExistsError(
                f"Local CIF staging target appeared during publish: {candidate}."
            )
        return candidate
    finally:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _safe_unlink(temporary, context="local CIF temporary snapshot")


def _remove_owned_snapshot(path: Path | None, *, digest: str, size: int) -> None:
    """Remove a snapshot only while it still has the bytes we published."""

    if path is None or not _path_exists(path):
        return
    try:
        if path.is_file() and path.stat().st_size == size and sha256_file(path) == digest:
            path.unlink()
    except OSError:
        # Cleanup is best effort; an external replacement must never be
        # removed merely because our transaction is being rolled back.
        return


def _local_elasticity_sources(cif_path: Path) -> list[Path]:
    """List local elasticity inputs without parsing any source bytes."""

    exact = cif_path.with_name(f"{cif_path.stem}_elasticity.json")
    if exact.is_file():
        return [exact]
    candidates = [
        item
        for item in sorted(cif_path.parent.glob("*_elasticity.json"))
        if item.is_file()
    ]
    for name in (
        "elasticity_index.csv",
        "diffractscout_elasticity.csv",
        "elasticity.csv",
    ):
        item = cif_path.parent / name
        if item.is_file():
            candidates.append(item)
    return candidates


def _copy_verified_local_elasticity(
    source: Path,
    destination: Path,
) -> tuple[str, int, bool]:
    """Snapshot a local sidecar with source-before/source-after checks."""

    digest = sha256_file(source)
    size = source.stat().st_size
    _reject_reparse_components(destination, label="local elasticity staging target")
    if _path_exists(destination):
        if not destination.is_file():
            raise FileExistsError(
                f"Local elasticity staging target is not a file: {destination}."
            )
        destination_digest = sha256_file(destination)
        destination_size = destination.stat().st_size
        source_after_digest = sha256_file(source)
        source_after_size = source.stat().st_size
        if (
            destination_digest == digest
            and destination_size == size
            and source_after_digest == digest
            and source_after_size == size
        ):
            return digest, size, False
        raise FileExistsError(
            f"Local elasticity staging target conflicts with source bytes: {destination}."
        )
    _copy_local_snapshot(
        source,
        destination,
        expected_digest=digest,
        expected_size=size,
    )
    return digest, size, True


def _bind_override_to_staged_sidecar(
    override: ElasticTensor,
    staged: ElasticTensor | None,
    staged_path: Path,
) -> ElasticTensor:
    """Keep explicit override values after checking a staged provenance sidecar."""

    if staged is None or staged.status == "invalid":
        raise ValueError(
            f"Elasticity override sidecar {staged_path.name} did not contain a valid tensor."
        )
    matrix_matches = (
        override.stiffness_GPa.shape == staged.stiffness_GPa.shape
        and override.stiffness_GPa.shape == (6, 6)
        and bool(
            np.allclose(
                override.stiffness_GPa,
                staged.stiffness_GPa,
                rtol=1e-10,
                atol=1e-12,
            )
        )
    )
    frame_matches = override.coordinate_frame == staged.coordinate_frame
    if not matrix_matches or not frame_matches:
        details: list[str] = []
        if not matrix_matches:
            details.append("stiffness matrix")
        if not frame_matches:
            details.append("coordinate frame")
        raise ValueError(
            f"Explicit elasticity override does not match staged sidecar "
            f"{staged_path.name} ({' and '.join(details)} mismatch)."
        )
    # The explicit override remains authoritative for numerical values and
    # provenance; only the raw payload path is rebound into the committed tree.
    override.raw_payload_path = staged_path
    return override


def _stage_local_elasticity(
    cif_path: Path,
    staged_cif: Path,
    inputs_dir: Path,
) -> tuple[ElasticTensor | None, list[tuple[Path, str, int]]]:
    """Stage and parse local elasticity only from private snapshot bytes."""

    sources = _local_elasticity_sources(cif_path)
    if not sources:
        return None, []

    owned: list[tuple[Path, str, int]] = []
    exact = sources[0] if sources[0].name == f"{cif_path.stem}_elasticity.json" else None
    if exact is not None:
        destination = staged_cif.with_name(f"{staged_cif.stem}_elasticity.json")
        digest, size, created = _copy_verified_local_elasticity(exact, destination)
        if created:
            owned.append((destination, digest, size))
        if staged_cif.name != cif_path.name:
            normalize_elasticity_sidecar(
                destination,
                destination,
                cif_path=cif_path,
                committed_cif_name=staged_cif.name,
            )
            digest = sha256_file(destination)
            size = destination.stat().st_size
            if created:
                owned[-1] = (destination, digest, size)
        tensor = discover_elastic_tensor(staged_cif)
        if tensor is None:
            _remove_owned_snapshot(destination, digest=digest, size=size)
            return None, []
        return tensor, owned

    # Probe fallback sidecars/index files from a private directory first.  No
    # source path is parsed before its verified snapshot exists.
    probe = Path(tempfile.mkdtemp(prefix=".elasticity-probe-", dir=str(inputs_dir)))
    try:
        for source in sources:
            probe_target = probe / source.name
            _copy_verified_local_elasticity(source, probe_target)
        probe_cif = probe / cif_path.name
        tensor = discover_elastic_tensor(probe_cif)
        raw = tensor.raw_payload_path if tensor is not None else None
        if raw is None or not raw.is_file():
            return None, []
        if raw.suffix.lower() == ".json":
            destination = staged_cif.with_name(f"{staged_cif.stem}_elasticity.json")
        else:
            destination = inputs_dir / raw.name
        digest, size, created = _copy_verified_local_elasticity(raw, destination)
        if created:
            owned.append((destination, digest, size))
        if destination.suffix.lower() == ".json" and staged_cif.name != cif_path.name:
            normalize_elasticity_sidecar(
                destination,
                destination,
                cif_path=cif_path,
                committed_cif_name=staged_cif.name,
            )
            digest = sha256_file(destination)
            size = destination.stat().st_size
            if created:
                owned[-1] = (destination, digest, size)
        final_tensor = discover_elastic_tensor(staged_cif)
        if final_tensor is None:
            _remove_owned_snapshot(destination, digest=digest, size=size)
            return None, []
        return final_tensor, owned
    finally:
        _safe_rmtree(probe, context="local elasticity probe")


def _copy_local_input(
    cif_path: Path,
    inputs_dir: Path,
    *,
    include_elasticity: bool,
    elastic_override: ElasticTensor | None = None,
) -> tuple[Path, ElasticTensor | None]:
    digest = sha256_file(cif_path)
    size = cif_path.stat().st_size
    target = _unique_input_target(cif_path, inputs_dir, digest)
    owned_sidecars: list[tuple[Path, str, int]] = []
    try:
        _copy_local_snapshot(
            cif_path,
            target,
            expected_digest=digest,
            expected_size=size,
        )

        if not include_elasticity:
            return target, None

        if elastic_override is not None:
            tensor = _revalidate_user_tensor(elastic_override)
            raw = tensor.raw_payload_path
            if raw is not None and raw.is_file():
                sidecar_target = target.with_name(
                    f"{target.stem}_elasticity{raw.suffix}"
                )
                if raw.suffix.lower() != ".json":
                    sidecar_target = inputs_dir / raw.name
                sidecar_digest, sidecar_size, sidecar_created = _copy_verified_local_elasticity(
                    raw,
                    sidecar_target,
                )
                if sidecar_created:
                    owned_sidecars.append((sidecar_target, sidecar_digest, sidecar_size))
                if raw.suffix.lower() == ".json" and target.name != cif_path.name:
                    normalize_elasticity_sidecar(
                        sidecar_target,
                        sidecar_target,
                        cif_path=cif_path,
                        committed_cif_name=target.name,
                    )
                    sidecar_digest = sha256_file(sidecar_target)
                    sidecar_size = sidecar_target.stat().st_size
                    if sidecar_created:
                        owned_sidecars[-1] = (sidecar_target, sidecar_digest, sidecar_size)
                staged_tensor = discover_elastic_tensor(target)
                tensor = _bind_override_to_staged_sidecar(
                    tensor,
                    staged_tensor,
                    sidecar_target,
                )
            return target, tensor

        tensor, owned_sidecars = _stage_local_elasticity(cif_path, target, inputs_dir)
        return target, tensor
    except Exception:
        for sidecar, sidecar_digest, sidecar_size in owned_sidecars:
            _remove_owned_snapshot(
                sidecar,
                digest=sidecar_digest,
                size=sidecar_size,
            )
        _remove_owned_snapshot(target, digest=digest, size=size)
        raise


def _safe_staged_filename(value: object, fallback: str, *, suffix: str) -> str:
    """Make an artifact basename that cannot encode a path traversal."""

    raw_name = Path(str(value or "")).name
    raw_stem = Path(raw_name).stem
    stem = slugify(raw_stem, Path(fallback).stem).replace(".", "_")
    stem = slugify(stem, Path(fallback).stem).replace(".", "_")
    return f"{stem}{suffix}"


def _copy_provider_artifact(
    source: str | Path,
    destination_dir: Path,
    *,
    preferred_name: str,
    suffix: str,
) -> Path:
    """Copy one provider artifact into ``inputs`` with a collision-safe name."""

    source_path = Path(source).expanduser()
    _reject_reparse_components(source_path, label="provider artifact")
    if not source_path.is_file():
        raise FileNotFoundError(f"Provider artifact does not exist: {source_path}")
    source_path = source_path.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    preferred = destination_dir / _safe_staged_filename(
        preferred_name,
        "provider_artifact",
        suffix=suffix,
    )
    _reject_reparse_components(preferred, label="staged provider artifact")
    digest = sha256_file(source_path)
    size = source_path.stat().st_size
    candidate = preferred
    if candidate.exists():
        if candidate.is_file() and sha256_file(candidate) == digest:
            return candidate
        candidate = destination_dir / (
            f"{preferred.stem}_{digest[:8]}{preferred.suffix}"
        )
        counter = 2
        while candidate.exists():
            if candidate.is_file() and sha256_file(candidate) == digest:
                return candidate
            candidate = destination_dir / (
                f"{preferred.stem}_{digest[:8]}_{counter}{preferred.suffix}"
            )
            counter += 1

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{candidate.name}-",
        suffix=".tmp",
        dir=str(destination_dir),
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        os.close(descriptor)
        descriptor_open = False
        shutil.copy2(source_path, temporary)
        source_after_digest = sha256_file(source_path)
        source_after_size = source_path.stat().st_size
        if (
            sha256_file(temporary) != digest
            or temporary.stat().st_size != size
            or source_after_digest != digest
            or source_after_size != size
        ):
            raise OSError("Provider artifact changed while it was being copied.")

        while True:
            if _path_exists(candidate):
                if candidate.is_file() and sha256_file(candidate) == digest:
                    return candidate
                candidate = destination_dir / (
                    f"{preferred.stem}_{digest[:8]}_{uuid4().hex[:8]}{preferred.suffix}"
                )
                continue
            if _publish_private_snapshot(
                temporary,
                candidate,
                expected_digest=digest,
                expected_size=size,
            ):
                return candidate
    finally:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _safe_unlink(temporary, context="provider artifact temporary snapshot")


def _stable_provider_artifact_error(prefix: str, source: object, exc: Exception) -> str:
    """Describe an artifact failure without exposing transaction-directory paths."""

    name = Path(str(source or "provider-artifact")).name or "provider-artifact"
    return f"{prefix} {name!r}: {type(exc).__name__}."


def _scrub_transaction_path(message: object, staging: Path) -> str:
    """Remove staging-root details from provider-facing error strings."""

    text = str(message or "")
    staging_text = str(staging)
    variants = {
        staging_text,
        staging_text.replace("\\", "/"),
        staging.name,
    }
    for variant in variants:
        if variant:
            text = text.replace(variant, "<staging>")
    return text


def _failed_download_artifact(item: DownloadArtifact, message: str) -> DownloadArtifact:
    """Reject an artifact while retaining a deterministic, exportable failure row."""

    return replace(
        item,
        cif_path=None,
        elasticity_path=None,
        status="failed",
        error=message,
    )


def _canonical_material_id(value: object) -> str:
    """Return an internal material key without changing the source record."""

    return str(value).strip().casefold()


def _reconcile_download_coverage(
    candidates: Sequence[Any],
    downloads: Sequence[DownloadArtifact] | None,
) -> tuple[list[DownloadArtifact], list[DiagnosticRecord]]:
    """Reconcile provider results with the requested candidate IDs.

    Missing candidates receive synthetic failure rows.  Duplicate and
    unrequested provider rows are retained only as rejected failure rows, so
    no provider artifact can be analyzed under the wrong candidate.
    """

    requested: dict[str, Any] = {}
    requested_order: list[str] = []
    for candidate in candidates:
        material_id = _canonical_material_id(candidate.material_id)
        if material_id not in requested:
            requested[material_id] = candidate
            requested_order.append(material_id)

    returned: dict[str, list[DownloadArtifact]] = {}
    unrequested: list[DownloadArtifact] = []
    diagnostics: list[DiagnosticRecord] = []
    for item in list(downloads or []):
        material_id = _canonical_material_id(item.candidate.material_id)
        if material_id not in requested:
            message = (
                f"unrequested provider download artifact for candidate "
                f"{item.candidate.material_id!r}; "
                "artifact was rejected."
            )
            unrequested.append(_failed_download_artifact(item, message))
            diagnostics.append(
                DiagnosticRecord("download", item.candidate.material_id, "error", message)
            )
            continue
        returned.setdefault(material_id, []).append(item)

    reconciled: list[DownloadArtifact] = []
    for material_id in requested_order:
        matches = returned.get(material_id, [])
        if not matches:
            message = (
                "missing provider download artifact for requested candidate "
                f"{requested[material_id].material_id!r}."
            )
            reconciled.append(
                DownloadArtifact(
                    candidate=requested[material_id],
                    cif_path=None,
                    status="failed",
                    error=message,
                )
            )
            diagnostics.append(
                DiagnosticRecord(
                    "download", requested[material_id].material_id, "error", message
                )
            )
            continue
        if len(matches) > 1:
            message = (
                "duplicate provider download artifacts for requested candidate "
                f"{requested[material_id].material_id!r}; "
                "all duplicates were rejected."
            )
            reconciled.extend(_failed_download_artifact(item, message) for item in matches)
            diagnostics.append(
                DiagnosticRecord(
                    "download", requested[material_id].material_id, "error", message
                )
            )
            continue
        reconciled.append(matches[0])

    # Keep rejected unrequested rows after the requested-candidate rows in the
    # provider's original order, making exports deterministic and auditable.
    reconciled.extend(unrequested)
    return reconciled, diagnostics


def _normalize_download_artifacts(
    downloads: Sequence[DownloadArtifact],
    inputs_dir: Path,
    *,
    include_elasticity: bool,
) -> tuple[list[DownloadArtifact], list[DiagnosticRecord]]:
    """Normalize provider-returned files into the transaction staging root.

    Providers are allowed to use their own temporary download locations, but
    a result bundle must never depend on those locations after commit.  Every
    successful candidate therefore gets a staged CIF, and an explicitly
    returned elasticity artifact is copied and paired with that staged CIF.
    """

    normalized: list[DownloadArtifact] = []
    diagnostics: list[DiagnosticRecord] = []
    for item in downloads:
        staged_cif: Path | None = None
        staged_elasticity: Path | None = None
        status = item.status
        error = _scrub_transaction_path(item.error, inputs_dir.parent)
        elasticity_status = item.elasticity_status
        elasticity_error = _scrub_transaction_path(item.elasticity_error, inputs_dir.parent)

        if item.status == "ok":
            if item.cif_path is None:
                status = "failed"
                error = error or "Provider reported success without a CIF artifact."
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        error,
                    )
                )
            else:
                try:
                    staged_cif = _copy_provider_artifact(
                        item.cif_path,
                        inputs_dir,
                        preferred_name=item.cif_path.name,
                        suffix=".cif",
                    )
                except (OSError, ValueError) as exc:
                    status = "failed"
                    error = _stable_provider_artifact_error(
                        "Could not stage provider CIF artifact",
                        item.cif_path,
                        exc,
                    )
                    diagnostics.append(
                        DiagnosticRecord(
                            "download",
                            item.candidate.material_id,
                            "error",
                            error,
                        )
                    )

        if not include_elasticity:
            elasticity_status = "not_requested"
            elasticity_error = ""
        elif item.elasticity_path is None:
            no_data_statuses = {
                "no_elasticity_data",
                "no_elastic_tensor",
                "not_available",
            }
            failure_statuses = {"invalid", "elasticity_query_failed"}
            if item.status == "ok" or elasticity_status not in no_data_statuses | failure_statuses:
                elasticity_status = "no_elasticity_data"
                elasticity_error = (
                    elasticity_error
                    or "Provider reported a successful candidate without an elasticity artifact."
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )
            elif elasticity_status in failure_statuses and not elasticity_error:
                elasticity_error = "Provider returned no readable elasticity artifact."
        elif item.status == "ok" and staged_cif is None:
            if elasticity_status not in {"invalid", "elasticity_query_failed"}:
                elasticity_status = "elasticity_query_failed"
                elasticity_error = (
                    "Provider elasticity artifact was not consumed because CIF staging failed."
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )
        elif staged_cif is not None:
            try:
                staged_elasticity = _copy_provider_artifact(
                    item.elasticity_path,
                    inputs_dir,
                    preferred_name=f"{staged_cif.stem}_elasticity.json",
                    suffix=".json",
                )
                elasticity_status, elasticity_error = normalize_elasticity_sidecar(
                    staged_elasticity,
                    staged_elasticity,
                    # Keep provider pairing validation against the provider's
                    # original CIF identity; all numeric parsing and rewrite
                    # input now comes from the staged sidecar snapshot.
                    cif_path=item.cif_path,
                    committed_cif_name=staged_cif.name,
                    expected_material_id=item.candidate.material_id,
                )
                elasticity_error = _scrub_transaction_path(
                    elasticity_error, inputs_dir.parent
                )
                if elasticity_status in {"invalid", "elasticity_query_failed"}:
                    diagnostics.append(
                        DiagnosticRecord(
                            "elasticity",
                            item.candidate.material_id,
                            "error",
                            elasticity_error or elasticity_status,
                        )
                    )
                elif elasticity_status not in {"", "ok"}:
                    diagnostics.append(
                        DiagnosticRecord(
                            "elasticity",
                            item.candidate.material_id,
                            "warning",
                            elasticity_error or elasticity_status,
                        )
                    )
            except (OSError, TypeError, ValueError) as exc:
                elasticity_status = "elasticity_query_failed"
                elasticity_error = _stable_provider_artifact_error(
                    "Could not stage or validate provider elasticity artifact",
                    item.elasticity_path,
                    exc,
                )
                diagnostics.append(
                    DiagnosticRecord(
                        "elasticity",
                        item.candidate.material_id,
                        "error",
                        elasticity_error,
                    )
                )

        normalized.append(
            replace(
                item,
                cif_path=staged_cif,
                elasticity_path=staged_elasticity if include_elasticity else None,
                status=status,
                error=error,
                elasticity_status=elasticity_status,
                elasticity_error=elasticity_error,
            )
        )
    return normalized, diagnostics


def _rebind_committed_path(path: Path | None, staging: Path, target: Path) -> Path | None:
    if path is None:
        return None
    path_abs = Path(os.path.abspath(os.fspath(path)))
    staging_abs = Path(os.path.abspath(os.fspath(staging)))
    try:
        relative = path_abs.relative_to(staging_abs)
    except ValueError:
        return path
    return target / relative


def _rebind_metadata_paths(value: Any, staging: Path, target: Path) -> Any:
    """Rebind Path values recursively without rewriting arbitrary strings."""

    if isinstance(value, Path):
        return _rebind_committed_path(value, staging, target) or value
    if isinstance(value, dict):
        return {
            _rebind_metadata_paths(key, staging, target): _rebind_metadata_paths(
                item, staging, target
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebind_metadata_paths(item, staging, target) for item in value]
    if isinstance(value, tuple):
        return tuple(_rebind_metadata_paths(item, staging, target) for item in value)
    if isinstance(value, set):
        return {_rebind_metadata_paths(item, staging, target) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_rebind_metadata_paths(item, staging, target) for item in value)
    return value


def _rebind_committed_results(
    analyses: Sequence[PhaseAnalysis],
    downloads: Sequence[DownloadArtifact],
    staging: Path,
    target: Path,
    *,
    discovery: DiscoveryResult | None = None,
) -> list[DownloadArtifact]:
    """Rebind returned artifact paths after the staging directory is renamed."""

    for analysis in analyses:
        analysis.structure.cif_path = _rebind_committed_path(
            analysis.structure.cif_path, staging, target
        ) or analysis.structure.cif_path
        if analysis.elastic_tensor is not None:
            analysis.elastic_tensor.raw_payload_path = _rebind_committed_path(
                analysis.elastic_tensor.raw_payload_path, staging, target
            )
        analysis.metadata = _rebind_metadata_paths(analysis.metadata, staging, target)
        analysis.structure.source_metadata = _rebind_metadata_paths(
            analysis.structure.source_metadata, staging, target
        )
    if discovery is not None:
        discovery.provider_metadata = _rebind_metadata_paths(
            discovery.provider_metadata, staging, target
        )
    return [
        replace(
            item,
            cif_path=_rebind_committed_path(item.cif_path, staging, target),
            elasticity_path=_rebind_committed_path(
                item.elasticity_path, staging, target
            ),
            provider_metadata=_rebind_metadata_paths(
                item.provider_metadata, staging, target
            ),
        )
        for item in downloads
    ]


def _analyze_paths(
    paths_and_tensors: Iterable[tuple[Path, ElasticTensor | None]],
    settings: AnalysisSettings,
) -> tuple[list[PhaseAnalysis], list[DiagnosticRecord]]:
    analyses: list[PhaseAnalysis] = []
    diagnostics: list[DiagnosticRecord] = []
    for path, tensor in paths_and_tensors:
        try:
            structure = load_structure(path)
            analysis = simulate_powder_pattern(
                structure,
                settings,
                elastic_tensor=tensor,
            )
            analyses.append(analysis)
            for warning in analysis.warnings:
                diagnostics.append(
                    DiagnosticRecord("analysis", path.name, "warning", warning)
                )
        except Exception as exc:
            diagnostics.append(
                DiagnosticRecord("analysis", path.name, "error", str(exc))
            )
    return analyses, diagnostics


def _diagnostic_warnings(diagnostics: list[DiagnosticRecord]) -> list[str]:
    return list(
        dict.fromkeys(
            f"{item.item}: {item.message}" if item.item else item.message
            for item in diagnostics
            if item.level in {"warning", "error"}
        )
    )


def _verify_staged_analysis_inputs(
    analyses: Sequence[PhaseAnalysis], staging: Path
) -> None:
    """Ensure exported analysis tables still describe the staged CIF bytes."""

    staging_abs = Path(os.path.abspath(os.fspath(staging)))
    for analysis in analyses:
        cif_path = Path(analysis.structure.cif_path)
        cif_abs = Path(os.path.abspath(os.fspath(cif_path)))
        try:
            cif_abs.relative_to(staging_abs)
        except ValueError as exc:
            raise RuntimeError(
                f"Analysis CIF is outside the staging directory: {cif_path}"
            ) from exc
        try:
            actual_hash = sha256_file(cif_abs)
        except OSError as exc:
            raise RuntimeError(
                f"Could not re-read analysis CIF before commit: {cif_path}"
            ) from exc
        if actual_hash != analysis.structure.cif_sha256:
            raise RuntimeError(
                f"Analysis CIF hash changed before commit: {cif_path.name}."
            )


def _verify_and_commit(
    target: Path,
    staging: Path,
    *,
    overwrite: bool,
    analyses: Sequence[PhaseAnalysis] = (),
    expected_state: _TargetState | None = None,
    diagnostics: list[DiagnosticRecord] | None = None,
) -> Path:
    report = verify_bundle(staging)
    if not report["ok"]:
        raise RuntimeError(
            "Generated bundle failed its integrity check: " + "; ".join(report["errors"])
        )
    _verify_staged_analysis_inputs(analyses, staging)
    # Close the long-running transaction's time-of-check/time-of-use gap. A
    # target created or modified during analysis must satisfy the same overwrite
    # policy as it did before the run started.
    _validate_output_target(target, overwrite=overwrite)
    if expected_state is None:
        expected_state = _capture_target_state(target)
    transaction_warnings: list[str] = []
    try:
        _commit_staging_output(
            target,
            staging,
            expected_state=expected_state,
            warning_sink=transaction_warnings,
        )
    finally:
        if diagnostics is not None:
            diagnostics.extend(
                DiagnosticRecord("transaction", target.name, "warning", message)
                for message in transaction_warnings
            )
    return target / "manifest.json"


def analyze_cifs(
    inputs: Sequence[str | Path],
    output_dir: str | Path,
    *,
    settings: AnalysisSettings | None = None,
    recursive: bool = True,
    include_excel: bool = True,
    overwrite: bool = False,
    elastic_overrides: Mapping[str, ElasticTensor] | None = None,
) -> PipelineResult:
    settings = settings or AnalysisSettings()
    validate_analysis_settings(settings)
    _validate_input_output_separation(inputs, output_dir)
    paths = collect_cif_paths(inputs, recursive=recursive)
    if not paths:
        raise FileNotFoundError("No CIF files were found in the supplied inputs.")
    target = _validate_output_target(output_dir, overwrite=overwrite)
    expected_target_state = _capture_target_state(target)
    staging = _create_staging_output(target)
    try:
        inputs_dir = staging / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        copied = [
            _copy_local_input(
                path,
                inputs_dir,
                include_elasticity=settings.include_elasticity,
                elastic_override=(
                    _lookup_elastic_override(path, elastic_overrides)
                    if settings.include_elasticity
                    else None
                ),
            )
            for path in paths
        ]
        analyses, diagnostics = _analyze_paths(copied, settings)
        export_result_bundle(
            staging,
            analyses=analyses,
            settings=settings,
            downloads=[],
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(
            target,
            staging,
            overwrite=overwrite,
            analyses=analyses,
            expected_state=expected_target_state,
            diagnostics=diagnostics,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _rebind_committed_results(analyses, [], staging, target)
    return PipelineResult(
        output_dir=target,
        discovery=None,
        downloads=[],
        analyses=analyses,
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
    )


def discover_candidates(
    composition: str,
    provider: PhaseProvider,
    *,
    settings: DiscoverySettings | None = None,
) -> DiscoveryResult:
    parsed = parse_composition_text(composition)
    return search_candidates(provider, parsed, settings or DiscoverySettings())


def export_discovery(
    composition: str,
    provider: PhaseProvider,
    output_dir: str | Path,
    *,
    discovery_settings: DiscoverySettings | None = None,
    include_excel: bool = True,
    overwrite: bool = False,
) -> PipelineResult:
    target = _validate_output_target(output_dir, overwrite=overwrite)
    expected_target_state = _capture_target_state(target)
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    staging = _create_staging_output(target)
    diagnostics = [
        DiagnosticRecord("discovery", "query", "warning", warning)
        for warning in discovery.warnings
    ]
    try:
        export_result_bundle(
            staging,
            analyses=[],
            settings=AnalysisSettings(),
            discovery=discovery,
            downloads=[],
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(
            target,
            staging,
            overwrite=overwrite,
            expected_state=expected_target_state,
            diagnostics=diagnostics,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _rebind_committed_results([], [], staging, target, discovery=discovery)
    return PipelineResult(
        output_dir=target,
        discovery=discovery,
        downloads=[],
        analyses=[],
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
    )


def run_pipeline(
    composition: str,
    provider: PhaseProvider,
    output_dir: str | Path,
    *,
    discovery_settings: DiscoverySettings | None = None,
    analysis_settings: AnalysisSettings | None = None,
    conventional_unit_cell: bool = True,
    include_elasticity: bool = True,
    include_excel: bool = True,
    overwrite: bool = False,
    confirm_above: int = 200,
    authorize_large_download: bool = False,
) -> PipelineResult:
    requested_analysis_settings = analysis_settings or AnalysisSettings(
        include_elasticity=include_elasticity
    )
    if requested_analysis_settings.include_elasticity != include_elasticity:
        requested_analysis_settings = replace(
            requested_analysis_settings, include_elasticity=include_elasticity
        )
    validate_analysis_settings(requested_analysis_settings)
    if include_elasticity and not conventional_unit_cell:
        raise ValueError(
            "Primitive-cell downloads cannot be paired automatically with Materials Project "
            "elastic tensors. Set include_elasticity=False or use the conventional cell."
        )
    if isinstance(confirm_above, bool) or not isinstance(confirm_above, int) or confirm_above < 1:
        raise ValueError("confirm_above must be a positive integer.")

    target = _validate_output_target(output_dir, overwrite=overwrite)
    expected_target_state = _capture_target_state(target)
    discovery = discover_candidates(
        composition,
        provider,
        settings=discovery_settings,
    )
    if len(discovery.candidates) > confirm_above and not authorize_large_download:
        raise PermissionError(
            f"Refusing to download {len(discovery.candidates)} candidates (> {confirm_above}) "
            "without explicit authorization. Set authorize_large_download=True or reduce the query."
        )

    staging = _create_staging_output(target)
    diagnostics = [
        DiagnosticRecord("discovery", "query", "warning", warning)
        for warning in discovery.warnings
    ]
    try:
        inputs_dir = staging / "inputs"
        provider_downloads = provider.download_candidates(
            discovery.candidates,
            inputs_dir,
            conventional_unit_cell=conventional_unit_cell,
            include_elasticity=include_elasticity,
        )
        reconciled_downloads, coverage_diagnostics = _reconcile_download_coverage(
            discovery.candidates,
            provider_downloads,
        )
        downloads, artifact_diagnostics = _normalize_download_artifacts(
            reconciled_downloads,
            inputs_dir,
            include_elasticity=include_elasticity,
        )
        diagnostics.extend(coverage_diagnostics)
        diagnostics.extend(artifact_diagnostics)
        settings = requested_analysis_settings

        path_pairs: list[tuple[Path, ElasticTensor | None]] = []
        for index, item in enumerate(downloads):
            if item.status != "ok":
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        item.error or "Structure download failed.",
                    )
                )
                continue
            if item.cif_path is None or not item.cif_path.is_file():
                diagnostics.append(
                    DiagnosticRecord(
                        "download",
                        item.candidate.material_id,
                        "error",
                        "Provider reported success without a readable CIF file.",
                    )
                )
                continue
            tensor = None
            if include_elasticity:
                if item.elasticity_path is not None:
                    if item.elasticity_status not in {
                        "invalid",
                        "no_elasticity_data",
                        "no_elastic_tensor",
                        "elasticity_query_failed",
                        "not_available",
                    }:
                        tensor, sidecar_status, sidecar_error = load_elastic_tensor_for_cif(
                            item.elasticity_path,
                            item.cif_path,
                            expected_material_id=item.candidate.material_id,
                        )
                        sidecar_changed = (
                            sidecar_status != item.elasticity_status
                            or sidecar_error != item.elasticity_error
                        )
                        if sidecar_changed:
                            item = replace(
                                item,
                                elasticity_status=sidecar_status,
                                elasticity_error=sidecar_error,
                            )
                            downloads[index] = item
                            if sidecar_status in {"invalid", "elasticity_query_failed"}:
                                diagnostics.append(
                                    DiagnosticRecord(
                                        "elasticity",
                                        item.candidate.material_id,
                                        "error",
                                        sidecar_error or sidecar_status,
                                    )
                                )
                            elif sidecar_status not in {"", "ok"} and sidecar_error:
                                diagnostics.append(
                                    DiagnosticRecord(
                                        "elasticity",
                                        item.candidate.material_id,
                                        "warning",
                                        sidecar_error,
                                    )
                                )
            path_pairs.append((item.cif_path, tensor))

        analyses, analysis_diagnostics = _analyze_paths(path_pairs, settings)
        diagnostics.extend(analysis_diagnostics)
        export_result_bundle(
            staging,
            analyses=analyses,
            settings=settings,
            discovery=discovery,
            downloads=downloads,
            diagnostics=diagnostics,
            include_excel=include_excel,
        )
        manifest = _verify_and_commit(
            target,
            staging,
            overwrite=overwrite,
            analyses=analyses,
            expected_state=expected_target_state,
            diagnostics=diagnostics,
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    downloads = _rebind_committed_results(
        analyses,
        downloads,
        staging,
        target,
        discovery=discovery,
    )
    return PipelineResult(
        output_dir=target,
        discovery=discovery,
        downloads=downloads,
        analyses=analyses,
        manifest_path=manifest,
        warnings=_diagnostic_warnings(diagnostics),
        diagnostics=diagnostics,
    )
