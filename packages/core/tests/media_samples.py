"""Synthetic mp4/webm file starts with known DASH init/index ranges, for tests."""

import struct

from homefeed_core.gateway import ByteRange


def box(kind: bytes, payload_size: int) -> bytes:
    return struct.pack(">I4s", 8 + payload_size, kind) + bytes(payload_size)


def mp4(moov_payload: int = 700, sidx_payload: int = 3000, media: int = 5000) -> bytes:
    """ftyp, moov, sidx, then media. Ranges: init 0..end of moov, index = sidx."""
    return (
        box(b"ftyp", 16)
        + box(b"moov", moov_payload)
        + box(b"sidx", sidx_payload)
        + (box(b"moof", 100) + box(b"mdat", media))
    )


def mp4_ranges(moov_payload: int = 700, sidx_payload: int = 3000) -> tuple[ByteRange, ByteRange]:
    init_end = 24 + 8 + moov_payload - 1
    return ByteRange(0, init_end), ByteRange(init_end + 1, init_end + 8 + sidx_payload)


def ebml(element_id: int, payload: bytes, *, unknown_size: bool = False) -> bytes:
    id_bytes = element_id.to_bytes((element_id.bit_length() + 7) // 8, "big")
    if unknown_size:
        size = b"\x01\xff\xff\xff\xff\xff\xff\xff"
    else:
        size = (0x10000000 | len(payload)).to_bytes(4, "big")  # 4-byte vint
    return id_bytes + size + payload


def webm(cues_payload: int = 5000, cluster: int = 5000) -> bytes:
    """EBML header, Segment{SeekHead, Info, Tracks, Cues, Cluster}."""
    header = ebml(0x1A45DFA3, bytes(20))
    body = (
        ebml(0x114D9B74, bytes(40))  # SeekHead
        + ebml(0x1549A966, bytes(50))  # Info
        + ebml(0x1654AE6B, bytes(60))  # Tracks
        + ebml(0x1C53BB6B, bytes(cues_payload))  # Cues
        + ebml(0x1F43B675, bytes(cluster))  # Cluster
    )
    return header + ebml(0x18538067, body, unknown_size=True)


def webm_ranges(cues_payload: int = 5000) -> tuple[ByteRange, ByteRange]:
    cues_start = (4 + 4 + 20) + (4 + 8) + (4 + 4 + 40) + (4 + 4 + 50) + (4 + 4 + 60)
    return ByteRange(0, cues_start - 1), ByteRange(cues_start, cues_start + 8 + cues_payload - 1)
