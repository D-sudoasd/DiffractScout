"""Classify transient transport failures without depending on an HTTP client."""
from __future__ import annotations


def transient_error(error: BaseException) -> bool:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status is not None:
        return status in {408, 429, 500, 502, 503, 504}
    return isinstance(error, (TimeoutError, ConnectionError)) or any(
        cls.__name__ in {"Timeout", "ConnectTimeout", "ReadTimeout", "ConnectError", "ConnectionError"}
        for cls in type(error).__mro__
    )
