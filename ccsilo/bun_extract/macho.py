"""Mach-O section discovery and data-start computation."""

from dataclasses import dataclass
import struct

from .checked import checked_unpack_from as _checked_unpack_from
from .constants import (
    MACHO_HEADER_SCAN_BYTES,
    MACHO_MAGIC_64,
    MACHO_MAGIC_64_BE,
    MACHO_MAGIC_FAT,
    MACHO_MAGIC_FAT_LE,
    MACHO_SECTION_HEADER_SIZE,
)
from .types import BunFormatError

LC_SEGMENT_64 = 0x19
LC_CODE_SIGNATURE = 0x1D


@dataclass
class MachoSection:
    section_offset: int
    section_size: int
    has_code_signature: bool = False


def is_macho(data):
    if len(data) < 4:
        return False
    magic = struct.unpack_from("<I", data, 0)[0]
    return magic in {
        MACHO_MAGIC_64,
        MACHO_MAGIC_64_BE,
        MACHO_MAGIC_FAT,
        MACHO_MAGIC_FAT_LE,
    }


def find_bun_section(data):
    parsed = _find_bun_section_from_load_commands(data)
    if parsed is not None:
        return parsed

    return _find_bun_section_by_scan(data)


def macho_data_start(section_offset):
    return section_offset + MACHO_SECTION_HEADER_SIZE


def _macho_endian(data):
    if len(data) < 4:
        return None
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == MACHO_MAGIC_64:
        return "<"
    if magic == MACHO_MAGIC_64_BE:
        return ">"
    return None


def _find_bun_section_from_load_commands(data):
    try:
        endian = _macho_endian(data)
        if endian is None or len(data) < 32:
            return None

        ncmds = _checked_unpack_from(endian + "I", data, 16, "Mach-O ncmds")[0]
        offset = 32
        has_code_signature = False
        bun_section = None

        for _ in range(ncmds):
            if offset + 8 > len(data):
                return None

            cmd = _checked_unpack_from(endian + "I", data, offset, "Mach-O load command")[0]
            cmdsize = _checked_unpack_from(endian + "I", data, offset + 4, "Mach-O load command size")[0]
            if cmdsize < 8 or offset + cmdsize > len(data):
                return None

            if cmd == LC_CODE_SIGNATURE:
                has_code_signature = True
            elif cmd == LC_SEGMENT_64:
                section = _find_bun_section_in_segment(data, offset, cmdsize, endian)
                if section is not None:
                    bun_section = section

            offset += cmdsize

        if bun_section is None:
            return None

        bun_section.has_code_signature = has_code_signature
        return bun_section
    except BunFormatError:
        return None


def _find_bun_section_in_segment(data, segment_offset, cmdsize, endian):
    if cmdsize < 72:
        return None

    nsects = _checked_unpack_from(endian + "I", data, segment_offset + 64, "Mach-O segment nsects")[0]
    sections_start = segment_offset + 72

    for index in range(nsects):
        section_offset = sections_start + index * 80
        if section_offset + 80 > segment_offset + cmdsize or section_offset + 80 > len(data):
            return None

        sectname = _cstring(data[section_offset : section_offset + 16])
        segname = _cstring(data[section_offset + 16 : section_offset + 32])
        if sectname == "__bun" and segname == "__BUN":
            return MachoSection(
                section_size=_checked_unpack_from(endian + "Q", data, section_offset + 40, "Mach-O __bun size")[0],
                section_offset=_checked_unpack_from(endian + "I", data, section_offset + 48, "Mach-O __bun offset")[0],
            )

    return None


def _find_bun_section_by_scan(data):
    limit = min(len(data), MACHO_HEADER_SCAN_BYTES)
    has_code_signature = _scan_for_code_signature_cmd(data, limit)
    for offset in range(0, max(0, limit - 56)):
        if (
            data[offset : offset + 6] == b"__bun\x00"
            and data[offset + 16 : offset + 21] == b"__BUN"
        ):
            section_size = _checked_unpack_from("<Q", data, offset + 40, "Mach-O scanned __bun size")[0]
            section_offset = _checked_unpack_from("<I", data, offset + 48, "Mach-O scanned __bun offset")[0]
            return MachoSection(
                section_offset=section_offset,
                section_size=section_size,
                has_code_signature=has_code_signature,
            )
    return None


def _cstring(value):
    return value.split(b"\x00", 1)[0].decode("utf-8", "ignore")


def _scan_for_code_signature_cmd(data, limit):
    for offset in range(0, max(0, limit - 8), 4):
        if _checked_unpack_from("<I", data, offset, "Mach-O scanned load command")[0] != LC_CODE_SIGNATURE:
            continue
        cmdsize = _checked_unpack_from("<I", data, offset + 4, "Mach-O scanned load command size")[0]
        if cmdsize == 16:
            return True
    return False
