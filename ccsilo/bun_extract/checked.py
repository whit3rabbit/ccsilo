"""Checked binary reads for Bun parser helpers."""

import struct

from .types import BunFormatError


def checked_unpack_from(fmt: str, data, offset: int, label: str):
    if offset < 0:
        raise BunFormatError(f"{label} offset is negative: {offset}")
    size = struct.calcsize(fmt)
    if offset + size > len(data):
        raise BunFormatError(f"{label} extends past EOF")
    return struct.unpack_from(fmt, data, offset)


def checked_slice(data, start: int, length: int, label: str):
    if start < 0 or length < 0:
        raise BunFormatError(f"{label} has negative range")
    end = start + length
    if end > len(data):
        raise BunFormatError(f"{label} extends past EOF")
    return data[start:end]
