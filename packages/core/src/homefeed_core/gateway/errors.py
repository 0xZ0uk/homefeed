"""Errors raised by the Gateway. Callers catch these, never extractor exceptions."""

from typing import ClassVar


class GatewayError(Exception):
    """Base class. `retryable` says whether trying again later might succeed."""

    retryable: ClassVar[bool] = False
    kind: ClassVar[str] = "error"


class UnsupportedUrlError(GatewayError):
    """The input is not a YouTube URL the Gateway understands."""

    kind = "unsupported_url"


class UnavailableError(GatewayError):
    """The video or channel doesn't exist or can't be watched (removed, private, ...)."""

    kind = "unavailable"


class ExtractionError(GatewayError):
    """A transient or unknown failure talking to YouTube (network, parsing, server error)."""

    retryable = True
    kind = "extraction"


class RateLimitedError(ExtractionError):
    """YouTube is throttling us (HTTP 429 or a bot check)."""

    kind = "rate_limited"


class CookiesError(GatewayError):
    """The browser to read YouTube cookies from is invalid, or its cookies can't be read."""

    kind = "cookies"


class MediaUrlExpiredError(GatewayError):
    """A stream URL was refused (HTTP 403/410): it expired or was revoked.

    Get fresh URLs with `Gateway.get_formats` and try again.
    """

    kind = "media_url_expired"


class RangeNotSatisfiableError(GatewayError):
    """The requested byte range starts past the end of the stream (HTTP 416)."""

    kind = "range_not_satisfiable"
