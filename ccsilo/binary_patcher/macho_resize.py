"""Mach-O binary resize and code-signature stripping for the .bun section."""

import struct
from dataclasses import dataclass

from ccsilo.bun_extract.checked import checked_unpack_from as _checked_unpack_from
from ccsilo.bun_extract.constants import (
    MACHO_HEADER_SCAN_BYTES,
    MACHO_MAGIC_64,
    MACHO_MAGIC_64_BE,
    MACHO_SECTION_HEADER_SIZE,
    OFFSETS_SIZE,
    TRAILER,
)
from ccsilo.bun_extract.types import BunFormatError

LC_CODE_SIGNATURE = 0x1D
LC_DATA_IN_CODE = 0x29
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_FUNCTION_STARTS = 0x26
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
MACH_HEADER_64_SIZE = 32
BUN_SEGNAME = "__BUN"
LINKEDIT_SEGNAME = "__LINKEDIT"
PAGE_ALIGN = 0x4000


@dataclass
class MachoRepackResult:
    buf: bytes
    signature_stripped: bool = False

    @property
    def data(self):
        return self.buf


def repack_macho(data, info, new_raw_bytes, new_offsets_struct):
    new_raw_bytes = bytes(new_raw_bytes)
    new_offsets_struct = bytes(new_offsets_struct)
    if len(new_offsets_struct) != OFFSETS_SIZE:
        raise ValueError(
            f"Mach-O repack: offsets struct must be {OFFSETS_SIZE} bytes, got {len(new_offsets_struct)}"
        )
    if info.section_offset is None:
        raise ValueError("Mach-O repack: BunBinaryInfo missing section_offset")

    section_header_offset = _find_bun_section_header_offset(data)
    if section_header_offset is None:
        raise ValueError("Mach-O repack: could not relocate __BUN section_64 struct for header rewrite")

    pre_section = bytearray(data[: info.section_offset])
    signature_stripped = False
    code_sig = _find_code_signature_lc(pre_section)
    linkedit = _find_segment(pre_section, LINKEDIT_SEGNAME)
    bun_segment = _find_segment(pre_section, BUN_SEGNAME)
    linkedit_tail = b""
    old_linkedit_fileoff = None
    new_linkedit_fileoff = None
    if code_sig is not None:
        if linkedit is not None:
            old_linkedit_fileoff = linkedit["fileoff"]
            linkedit_end = min(len(data), code_sig["dataoff"])
            if old_linkedit_fileoff <= linkedit_end:
                linkedit_tail = data[old_linkedit_fileoff:linkedit_end]
        _strip_code_signature(pre_section, code_sig)
        signature_stripped = True
    elif linkedit is not None:
        old_linkedit_fileoff = linkedit["fileoff"]
        linkedit_end = min(len(data), old_linkedit_fileoff + linkedit["filesize"])
        if old_linkedit_fileoff <= linkedit_end:
            linkedit_tail = data[old_linkedit_fileoff:linkedit_end]

    new_section_inner_size = len(new_raw_bytes) + OFFSETS_SIZE + len(TRAILER)
    new_section_payload_size = MACHO_SECTION_HEADER_SIZE + new_section_inner_size

    if linkedit is not None and old_linkedit_fileoff is not None:
        section_end = info.section_offset + new_section_payload_size
        new_linkedit_fileoff = _align_up(section_end, PAGE_ALIGN)
        linkedit_delta = new_linkedit_fileoff - old_linkedit_fileoff
        _update_linkedit_references(pre_section, old_linkedit_fileoff, linkedit_delta)
        _update_segment_fileoff(pre_section, linkedit, new_linkedit_fileoff)
        _update_segment_filesize(pre_section, linkedit, len(linkedit_tail))
        _update_segment_vmsize(pre_section, linkedit, _align_up(len(linkedit_tail), PAGE_ALIGN))

    if bun_segment is not None and new_linkedit_fileoff is not None:
        bun_filesize = new_linkedit_fileoff - bun_segment["fileoff"]
        _update_segment_filesize(pre_section, bun_segment, bun_filesize)
        new_bun_vmsize = _align_up(bun_filesize, PAGE_ALIGN)
        _update_segment_vmsize(pre_section, bun_segment, new_bun_vmsize)
        if linkedit is not None:
            # __BUN grew past its old page-aligned size: slide __LINKEDIT's
            # vmaddr so the segments stay contiguous. Overlapping segments
            # get the binary SIGKILLed at exec, even after ad-hoc re-signing.
            vm_delta = new_bun_vmsize - bun_segment["vmsize"]
            if vm_delta:
                _update_segment_vmaddr(pre_section, linkedit, linkedit["vmaddr"] + vm_delta)

    struct.pack_into("<Q", pre_section, section_header_offset + 40, new_section_payload_size)

    size_header = struct.pack("<Q", new_section_inner_size)
    parts = [bytes(pre_section), size_header, new_raw_bytes, new_offsets_struct, TRAILER]
    if new_linkedit_fileoff is not None and linkedit_tail:
        current_len = sum(len(part) for part in parts)
        if new_linkedit_fileoff < current_len:
            raise ValueError("Mach-O repack: relocated __LINKEDIT overlaps rebuilt __BUN section")
        parts.append(b"\x00" * (new_linkedit_fileoff - current_len))
        parts.append(linkedit_tail)
    return MachoRepackResult(
        buf=b"".join(parts),
        signature_stripped=signature_stripped,
    )


def _is_macho_64(data):
    if len(data) < 4:
        return False
    magic = _checked_unpack_from("<I", data, 0, "Mach-O magic")[0]
    return magic in {MACHO_MAGIC_64, MACHO_MAGIC_64_BE}


def _find_bun_section_header_offset(data):
    limit = min(len(data), MACHO_HEADER_SCAN_BYTES)
    for offset in range(0, max(0, limit - 56)):
        if (
            data[offset : offset + 6] == b"__bun\x00"
            and data[offset + 16 : offset + 21] == b"__BUN"
        ):
            return offset
    return None


def _find_code_signature_lc(data):
    if not _is_macho_64(data) or len(data) < MACH_HEADER_64_SIZE:
        return None
    try:
        ncmds = _checked_unpack_from("<I", data, 16, "Mach-O ncmds")[0]
        sizeofcmds = _checked_unpack_from("<I", data, 20, "Mach-O sizeofcmds")[0]
    except BunFormatError:
        return None
    if ncmds == 0 or sizeofcmds == 0:
        return None

    cursor = MACH_HEADER_64_SIZE
    end = MACH_HEADER_64_SIZE + sizeofcmds
    if end > len(data):
        return None
    for _ in range(ncmds):
        if cursor + 8 > end:
            return None
        cmd = _checked_unpack_from("<I", data, cursor, "Mach-O load command")[0]
        cmdsize = _checked_unpack_from("<I", data, cursor + 4, "Mach-O load command size")[0]
        if cmdsize < 8 or cursor + cmdsize > end:
            return None
        if cmd == LC_CODE_SIGNATURE and cmdsize == 16:
            return {
                "lc_offset": cursor,
                "cmdsize": cmdsize,
                "dataoff": _checked_unpack_from("<I", data, cursor + 8, "Mach-O code signature data offset")[0],
                "datasize": _checked_unpack_from("<I", data, cursor + 12, "Mach-O code signature data size")[0],
            }
        cursor += cmdsize
    return None


def _find_segment(data, segname):
    if len(data) < MACH_HEADER_64_SIZE:
        return None
    try:
        ncmds = _checked_unpack_from("<I", data, 16, "Mach-O ncmds")[0]
        sizeofcmds = _checked_unpack_from("<I", data, 20, "Mach-O sizeofcmds")[0]
    except BunFormatError:
        return None
    cursor = MACH_HEADER_64_SIZE
    end = MACH_HEADER_64_SIZE + sizeofcmds
    if end > len(data):
        return None

    for _ in range(ncmds):
        if cursor + 8 > end:
            return None
        cmd = _checked_unpack_from("<I", data, cursor, "Mach-O load command")[0]
        cmdsize = _checked_unpack_from("<I", data, cursor + 4, "Mach-O load command size")[0]
        if cmdsize < 8 or cursor + cmdsize > end:
            return None
        if cmd == LC_SEGMENT_64 and cmdsize >= 72:
            found = data[cursor + 8 : cursor + 24].split(b"\x00", 1)[0].decode("utf-8", "ignore")
            if found == segname:
                return {
                    "lc_offset": cursor,
                    "vmaddr": _checked_unpack_from("<Q", data, cursor + 24, "Mach-O segment vmaddr")[0],
                    "vmsize": _checked_unpack_from("<Q", data, cursor + 32, "Mach-O segment vmsize")[0],
                    "fileoff": _checked_unpack_from("<Q", data, cursor + 40, "Mach-O segment fileoff")[0],
                    "filesize": _checked_unpack_from("<Q", data, cursor + 48, "Mach-O segment filesize")[0],
                }
        cursor += cmdsize
    return None


def _update_segment_fileoff(data, segment, value):
    struct.pack_into("<Q", data, segment["lc_offset"] + 40, value)


def _update_segment_filesize(data, segment, value):
    struct.pack_into("<Q", data, segment["lc_offset"] + 48, value)


def _update_segment_vmsize(data, segment, value):
    struct.pack_into("<Q", data, segment["lc_offset"] + 32, value)


def _update_segment_vmaddr(data, segment, value):
    struct.pack_into("<Q", data, segment["lc_offset"] + 24, value)


def _align_up(value, alignment):
    return ((value + alignment - 1) // alignment) * alignment


def _update_linkedit_references(data, old_linkedit_fileoff, delta):
    if delta == 0:
        return
    try:
        ncmds = _checked_unpack_from("<I", data, 16, "Mach-O ncmds")[0]
        sizeofcmds = _checked_unpack_from("<I", data, 20, "Mach-O sizeofcmds")[0]
    except BunFormatError:
        return
    cursor = MACH_HEADER_64_SIZE
    end = MACH_HEADER_64_SIZE + sizeofcmds
    if end > len(data):
        return

    for _ in range(ncmds):
        if cursor + 8 > end:
            return
        cmd = _checked_unpack_from("<I", data, cursor, "Mach-O load command")[0]
        cmdsize = _checked_unpack_from("<I", data, cursor + 4, "Mach-O load command size")[0]
        if cmdsize < 8 or cursor + cmdsize > end:
            return

        if cmd in {LC_DYLD_CHAINED_FIXUPS, LC_DYLD_EXPORTS_TRIE, LC_FUNCTION_STARTS, LC_DATA_IN_CODE}:
            _shift_u32_fileoff(data, cursor + 8, old_linkedit_fileoff, delta)
        elif cmd == LC_SYMTAB:
            _shift_u32_fileoff(data, cursor + 8, old_linkedit_fileoff, delta)
            _shift_u32_fileoff(data, cursor + 16, old_linkedit_fileoff, delta)
        elif cmd == LC_DYSYMTAB:
            for offset in (32, 40, 48, 56, 64):
                _shift_u32_fileoff(data, cursor + offset, old_linkedit_fileoff, delta)

        cursor += cmdsize


def _shift_u32_fileoff(data, offset, old_linkedit_fileoff, delta):
    value = _checked_unpack_from("<I", data, offset, "Mach-O file offset field")[0]
    if value >= old_linkedit_fileoff:
        struct.pack_into("<I", data, offset, value + delta)


def _strip_code_signature(header, code_sig):
    ncmds = _checked_unpack_from("<I", header, 16, "Mach-O ncmds")[0]
    sizeofcmds = _checked_unpack_from("<I", header, 20, "Mach-O sizeofcmds")[0]
    lc_end = MACH_HEADER_64_SIZE + sizeofcmds
    tail_start = code_sig["lc_offset"] + code_sig["cmdsize"]
    tail_len = lc_end - tail_start

    if tail_len > 0:
        header[code_sig["lc_offset"] : code_sig["lc_offset"] + tail_len] = header[tail_start:lc_end]
    header[lc_end - code_sig["cmdsize"] : lc_end] = b"\x00" * code_sig["cmdsize"]
    struct.pack_into("<I", header, 16, ncmds - 1)
    struct.pack_into("<I", header, 20, sizeofcmds - code_sig["cmdsize"])
