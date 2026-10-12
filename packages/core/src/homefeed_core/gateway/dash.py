"""Finding DASH init/index byte ranges by reading the start of a media file.

The fallback for adaptive formats that arrive without `init_range`/`index_range`
(see docs/spikes/0013-dash-ranges.md, option c). YouTube writes the header first and
the segment index right after it, so the first couple of KB contain the index's
header, which is all we need: its size gives the index range.

- mp4: `ftyp`, `moov`, `sidx`, then `moof`/`mdat`. init = 0..end of `moov`.
- webm: EBML header, `Segment` { SeekHead, Info, Tracks, Cues, Cluster... }.
  init = 0..just before `Cues`.

Pure functions, no I/O: `probe_dash_ranges` takes a function that fetches a range.
"""

import struct
from collections.abc import Callable

from homefeed_core.gateway.models import ByteRange

PROBE_BYTES = 2048
# A header larger than this isn't one we know how to read; give up rather than
# downloading media.
MAX_PROBE_BYTES = 64 * 1024

DashRanges = tuple[ByteRange, ByteRange]  # (init, index)

_EBML_SEGMENT = 0x18538067
_EBML_CUES = 0x1C53BB6B
_EBML_CLUSTER = 0x1F43B675


class NeedMoreBytesError(Exception):
    """The buffer ends before the index header: read more bytes."""


def dash_ranges_from_bytes(head: bytes) -> DashRanges | None:
    """The (init, index) ranges found in the first bytes of an mp4 or webm file.

    Returns None if the layout isn't header-then-index or the container is unknown.
    Raises `NeedMoreBytesError` when more bytes are needed.
    """
    if head[4:8] == b"ftyp":
        return _mp4_ranges(head)
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML magic
        return _webm_ranges(head)
    return None


def probe_dash_ranges(fetch: Callable[[ByteRange], bytes]) -> DashRanges | None:
    """Read the start of a file with `fetch(range)` and find its DASH ranges.

    Reads `PROBE_BYTES` first and, if the index header lies further in, once more up
    to `MAX_PROBE_BYTES`. Returns None when the ranges can't be found. Errors raised
    by `fetch` propagate.
    """
    size = PROBE_BYTES
    while True:
        head = fetch(ByteRange(0, size - 1))
        try:
            return dash_ranges_from_bytes(head)
        except NeedMoreBytesError:
            if len(head) < size or size >= MAX_PROBE_BYTES:
                return None  # the file (or our patience) ended first
            size = MAX_PROBE_BYTES


def _mp4_ranges(buf: bytes) -> DashRanges | None:
    pos, init_end = 0, None
    while True:
        if pos + 8 > len(buf):
            raise NeedMoreBytesError
        size, box = struct.unpack(">I4s", buf[pos : pos + 8])
        if size == 1:
            if pos + 16 > len(buf):
                raise NeedMoreBytesError
            size = struct.unpack(">Q", buf[pos + 8 : pos + 16])[0]
        if size < 8:  # 0 means "to end of file": no index follows
            return None
        if box == b"moov":
            init_end = pos + size - 1
        elif box == b"sidx":
            if init_end is None:
                return None
            return ByteRange(0, init_end), ByteRange(pos, pos + size - 1)
        elif box in (b"moof", b"mdat"):
            return None
        pos += size


def _vint(buf: bytes, pos: int, *, keep_marker: bool) -> tuple[int, int]:
    """An EBML variable-length integer at `pos`: (value, length in bytes)."""
    if pos >= len(buf):
        raise NeedMoreBytesError
    first, length = buf[pos], 1
    while length <= 8 and not first & (0x80 >> (length - 1)):
        length += 1
    if length > 8:
        raise ValueError("invalid EBML integer")
    if pos + length > len(buf):
        raise NeedMoreBytesError
    value = first if keep_marker else first & (0xFF >> length)
    for byte in buf[pos + 1 : pos + length]:
        value = (value << 8) | byte
    return value, length


def _webm_ranges(buf: bytes) -> DashRanges | None:
    try:
        pos = 0
        _, n = _vint(buf, pos, keep_marker=True)
        pos += n
        size, n = _vint(buf, pos, keep_marker=False)
        pos += n + size  # skip the EBML header
        element, n = _vint(buf, pos, keep_marker=True)
        if element != _EBML_SEGMENT:
            return None
        pos += n
        _, n = _vint(buf, pos, keep_marker=False)  # the segment's size
        pos += n
        while True:
            start = pos
            element, n = _vint(buf, pos, keep_marker=True)
            pos += n
            size, n = _vint(buf, pos, keep_marker=False)
            pos += n
            if element == _EBML_CUES:
                return ByteRange(0, start - 1), ByteRange(start, pos + size - 1)
            if element == _EBML_CLUSTER:
                return None  # media before the index
            pos += size
    except ValueError:
        return None
