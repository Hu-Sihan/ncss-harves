from __future__ import annotations


class NcssError(RuntimeError):
    """Base error for NCSS Harves."""


class ResponseError(NcssError):
    """The remote response does not match the expected NCSS shape."""


class AuthenticationRequired(ResponseError):
    """NCSS requires an authenticated business session."""


class BlockedError(NcssError):
    """NCSS returned a verification or access-restriction page."""


class InvalidFilter(ValueError):
    def __init__(self, dimension: str, value: str, allowed_values: tuple[str, ...]):
        self.dimension = dimension
        self.value = value
        self.allowed_values = allowed_values
        super().__init__(f"unknown NCSS filter {dimension}: {value}")


class ShutdownRequested(NcssError):
    """The service is stopping and must not start another network request."""
