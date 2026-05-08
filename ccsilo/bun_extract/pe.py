"""PE section discovery and data-start computation."""

from dataclasses import dataclass
import struct

from .checked import checked_unpack_from as _checked_unpack_from
from .constants import PE_DOS_MAGIC, PE_NT_SIGNATURE
from .types import BunFormatError


@dataclass
class PeSection:
    pointer_to_raw_data: int
    size_of_raw_data: int


def is_pe(data):
    return len(data) >= 2 and struct.unpack_from("<H", data, 0)[0] == PE_DOS_MAGIC


def find_bun_pe_section(data):
    try:
        if len(data) < 0x40:
            return None
        pe_offset = _checked_unpack_from("<I", data, 0x3C, "PE header offset")[0]
        if pe_offset <= 0 or pe_offset + 24 > len(data):
            return None
        if _checked_unpack_from("<I", data, pe_offset, "PE signature")[0] != PE_NT_SIGNATURE:
            return None

        num_sections = _checked_unpack_from("<H", data, pe_offset + 6, "PE section count")[0]
        optional_size = _checked_unpack_from("<H", data, pe_offset + 20, "PE optional header size")[0]
        sections_start = pe_offset + 24 + optional_size

        for index in range(num_sections):
            base = sections_start + index * 40
            if base + 40 > len(data):
                return None
            name = data[base : base + 8]
            if name[:5] == b".bun\x00":
                return PeSection(
                    size_of_raw_data=_checked_unpack_from("<I", data, base + 16, "PE .bun raw size")[0],
                    pointer_to_raw_data=_checked_unpack_from("<I", data, base + 20, "PE .bun raw offset")[0],
                )
        return None
    except BunFormatError:
        return None


def pe_data_start(section_offset):
    return section_offset
