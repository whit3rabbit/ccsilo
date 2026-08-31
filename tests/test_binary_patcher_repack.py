import struct

import pytest

from ccsilo.binary_patcher import replace_entry_js
from ccsilo.binary_patcher.pe_resize import PeNotLastSectionError, repack_pe
from ccsilo.bun_extract import BunFormatError, parse_bun_binary
from ccsilo.bun_extract.constants import OFFSETS_SIZE, TRAILER
from tests.helpers.bun_fixture import build_bun_fixture


THREE_MODULES = [
    {"name": "src/header.js", "content": "HHHHHHHHHH"},
    {"name": "src/cli.js", "content": "CCCCCCCCCCCCCCCC"},
    {"name": "src/footer.js", "content": "FFFFFFFFFFFFFFFFFFFF"},
]


def _content(data, info, index):
    module = info.modules[index]
    return data[info.data_start + module.cont_off : info.data_start + module.cont_off + module.cont_len].decode("utf-8")


def _raw_bundle_bytes():
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])
    offsets_start = info.trailer_offset - OFFSETS_SIZE
    return (
        fixture["buf"][info.data_start : info.data_start + info.byte_count],
        fixture["buf"][offsets_start : info.trailer_offset],
    )


def _build_elf_with_resize_headers(*, late_phoff=False):
    raw_bytes, offsets = _raw_bundle_bytes()
    data_start = 0x108
    section_payload_start = data_start - 8
    tail_start = data_start + len(raw_bytes) + OFFSETS_SIZE + len(TRAILER)
    shent_size = 64
    shnum = 2
    shstr = b"\x00.bun\x00.shstrtab\x00"
    shstr_off = tail_start + shent_size * shnum

    section_table = bytearray(shent_size * shnum)
    old_section_size = 8 + len(raw_bytes) + OFFSETS_SIZE + len(TRAILER)
    struct.pack_into("<I", section_table, 0, 1)
    struct.pack_into("<Q", section_table, 24, section_payload_start)
    struct.pack_into("<Q", section_table, 32, old_section_size)
    struct.pack_into("<I", section_table, shent_size, 6)
    struct.pack_into("<Q", section_table, shent_size + 24, shstr_off)
    struct.pack_into("<Q", section_table, shent_size + 32, len(shstr))

    prefix = bytearray(data_start)
    prefix[:4] = b"\x7fELF"
    phoff = shstr_off + len(shstr) + 32 if late_phoff else 64
    phnum = 0 if late_phoff else 1
    struct.pack_into("<Q", prefix, 32, phoff)
    struct.pack_into("<Q", prefix, 40, tail_start)
    struct.pack_into("<H", prefix, 54, 56)
    struct.pack_into("<H", prefix, 56, phnum)
    struct.pack_into("<H", prefix, 58, shent_size)
    struct.pack_into("<H", prefix, 60, shnum)
    struct.pack_into("<H", prefix, 62, 1)
    struct.pack_into("<Q", prefix, section_payload_start, len(raw_bytes))

    if not late_phoff:
        old_file_size = tail_start + len(section_table) + len(shstr)
        struct.pack_into("<I", prefix, phoff, 1)
        struct.pack_into("<Q", prefix, phoff + 8, 0)
        struct.pack_into("<Q", prefix, phoff + 32, old_file_size)
        struct.pack_into("<Q", prefix, phoff + 40, old_file_size)

    buf = bytes(prefix) + raw_bytes + offsets + TRAILER + bytes(section_table) + shstr
    return buf, {
        "bun_section_header_off": tail_start,
        "phoff": phoff,
        "section_payload_start": section_payload_start,
        "tail_start": tail_start,
    }


def _build_signed_macho_with_linkedit():
    raw_bytes, offsets = _raw_bundle_bytes()
    lc_segment_64 = 0x19
    lc_code_signature = 0x1D
    bun_segment_size = 72 + 80
    linkedit_segment_size = 72
    code_sig_cmd_size = 16
    section_offset = 32 + bun_segment_size + linkedit_segment_size + code_sig_cmd_size
    section_size = 8 + len(raw_bytes) + OFFSETS_SIZE + len(TRAILER)
    sig_size = 0x80

    header = bytearray(section_offset)
    struct.pack_into("<I", header, 0, 0xFEEDFACF)
    struct.pack_into("<I", header, 16, 3)
    struct.pack_into("<I", header, 20, bun_segment_size + linkedit_segment_size + code_sig_cmd_size)

    bun_segment_off = 32
    struct.pack_into("<I", header, bun_segment_off, lc_segment_64)
    struct.pack_into("<I", header, bun_segment_off + 4, bun_segment_size)
    header[bun_segment_off + 8 : bun_segment_off + 24] = b"__BUN".ljust(16, b"\x00")
    struct.pack_into("<Q", header, bun_segment_off + 32, section_size)
    struct.pack_into("<Q", header, bun_segment_off + 40, section_offset)
    struct.pack_into("<Q", header, bun_segment_off + 48, section_size)
    struct.pack_into("<I", header, bun_segment_off + 64, 1)

    section_header_off = bun_segment_off + 72
    header[section_header_off : section_header_off + 16] = b"__bun".ljust(16, b"\x00")
    header[section_header_off + 16 : section_header_off + 32] = b"__BUN".ljust(16, b"\x00")
    struct.pack_into("<Q", header, section_header_off + 40, section_size)
    struct.pack_into("<I", header, section_header_off + 48, section_offset)

    linkedit_off = bun_segment_off + bun_segment_size
    linkedit_prefix_size = 0x40
    linkedit_vmsize = 0x400
    linkedit_filesize = linkedit_prefix_size + sig_size
    struct.pack_into("<I", header, linkedit_off, lc_segment_64)
    struct.pack_into("<I", header, linkedit_off + 4, linkedit_segment_size)
    header[linkedit_off + 8 : linkedit_off + 24] = b"__LINKEDIT".ljust(16, b"\x00")
    struct.pack_into("<Q", header, linkedit_off + 32, linkedit_vmsize)
    struct.pack_into("<Q", header, linkedit_off + 40, section_offset + section_size)
    struct.pack_into("<Q", header, linkedit_off + 48, linkedit_filesize)

    code_sig_off = linkedit_off + linkedit_segment_size
    struct.pack_into("<I", header, code_sig_off, lc_code_signature)
    struct.pack_into("<I", header, code_sig_off + 4, code_sig_cmd_size)
    struct.pack_into("<I", header, code_sig_off + 8, section_offset + section_size + linkedit_prefix_size)
    struct.pack_into("<I", header, code_sig_off + 12, sig_size)

    size_header = struct.pack("<Q", len(raw_bytes) + OFFSETS_SIZE + len(TRAILER))
    buf = bytes(header) + size_header + raw_bytes + offsets + TRAILER + (b"L" * linkedit_prefix_size) + (b"S" * sig_size)
    return buf, {
        "code_sig_cmd_size": code_sig_cmd_size,
        "lc_code_signature": lc_code_signature,
        "linkedit_off": linkedit_off,
        "linkedit_prefix_size": linkedit_prefix_size,
        "sig_size": sig_size,
    }


def _has_load_command(data, command):
    cursor = 32
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        cmd = struct.unpack_from("<I", data, cursor)[0]
        cmdsize = struct.unpack_from("<I", data, cursor + 4)[0]
        if cmd == command:
            return True
        cursor += cmdsize
    return False


@pytest.mark.parametrize("platform", ["elf", "macho", "pe"])
@pytest.mark.parametrize(
    ("new_content", "expected_delta"),
    [
        (b"X" * 64, 48),
        (b"xy", -14),
        (b"1234567890ABCDEF", 0),
    ],
)
def test_replace_entry_js_resizes_entry(platform, new_content, expected_delta):
    fixture = build_bun_fixture(
        platform=platform,
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])

    result = replace_entry_js(fixture["buf"], info, new_content)

    reparsed = parse_bun_binary(result.buf)
    assert result.delta == expected_delta
    assert reparsed.modules[0].name == "src/header.js"
    assert reparsed.modules[1].name == "src/cli.js"
    assert reparsed.modules[2].name == "src/footer.js"
    assert _content(result.buf, reparsed, 0) == "HHHHHHHHHH"
    assert _content(result.buf, reparsed, 1) == new_content.decode("utf-8")
    assert _content(result.buf, reparsed, 2) == "FFFFFFFFFFFFFFFFFFFF"


@pytest.mark.parametrize("platform", ["elf", "macho", "pe"])
def test_replace_entry_js_resizes_v36_module_table(platform):
    fixture = build_bun_fixture(
        platform=platform,
        module_struct_size=36,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])

    result = replace_entry_js(fixture["buf"], info, b"Z" * 40)

    reparsed = parse_bun_binary(result.buf)
    assert reparsed.module_size == 36
    assert _content(result.buf, reparsed, 0) == "HHHHHHHHHH"
    assert _content(result.buf, reparsed, 1) == "Z" * 40
    assert _content(result.buf, reparsed, 2) == "FFFFFFFFFFFFFFFFFFFF"


@pytest.mark.parametrize(("entry_point_id", "new_content"), [(0, b"NEWHEADER123456789012"), (2, b"NEWFOOTER")])
def test_replace_entry_js_handles_entry_position(entry_point_id, new_content):
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=entry_point_id,
    )
    info = parse_bun_binary(fixture["buf"])

    result = replace_entry_js(fixture["buf"], info, new_content)

    reparsed = parse_bun_binary(result.buf)
    assert _content(result.buf, reparsed, entry_point_id) == new_content.decode("utf-8")


def test_replace_entry_js_rejects_truncated_offsets_cleanly():
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])
    truncated = fixture["buf"][: info.trailer_offset - 8]

    with pytest.raises(BunFormatError, match="replace-entry"):
        replace_entry_js(truncated, info, b"X" * 32)


def test_replace_entry_js_rejects_bad_module_table_offset_cleanly():
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])
    data = bytearray(fixture["buf"])
    offsets_start = info.trailer_offset - OFFSETS_SIZE
    struct.pack_into("<I", data, offsets_start + 8, info.byte_count + 4096)

    with pytest.raises(BunFormatError, match="module 0 table"):
        replace_entry_js(bytes(data), info, b"X" * 32)


def test_replace_entry_js_strips_macho_code_signature():
    fixture = build_bun_fixture(
        platform="macho",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
        with_code_signature=True,
        trailing_padding=256,
    )
    info = parse_bun_binary(fixture["buf"])
    assert info.has_code_signature is True

    result = replace_entry_js(fixture["buf"], info, b"Y" * 32)

    reparsed = parse_bun_binary(result.buf)
    assert result.signature_invalidated is True
    assert result.signature_stripped is True
    assert reparsed.has_code_signature is False
    assert _content(result.buf, reparsed, 1) == "Y" * 32


def test_replace_entry_js_updates_realistic_elf_resize_headers():
    data, meta = _build_elf_with_resize_headers()
    info = parse_bun_binary(data)
    old_e_shoff = struct.unpack_from("<Q", data, 40)[0]
    old_pt_filesz = struct.unpack_from("<Q", data, meta["phoff"] + 32)[0]
    old_pt_memsz = struct.unpack_from("<Q", data, meta["phoff"] + 40)[0]
    old_size_prefix = struct.unpack_from("<Q", data, meta["section_payload_start"])[0]
    old_bun_section_size = struct.unpack_from("<Q", data, meta["bun_section_header_off"] + 32)[0]

    result = replace_entry_js(data, info, b"X" * 64)

    out = result.buf
    moved_bun_header_off = meta["bun_section_header_off"] + result.delta
    assert result.delta == 48
    assert struct.unpack_from("<Q", out, 40)[0] == old_e_shoff + result.delta
    assert struct.unpack_from("<Q", out, meta["phoff"] + 32)[0] == old_pt_filesz + result.delta
    assert struct.unpack_from("<Q", out, meta["phoff"] + 40)[0] == old_pt_memsz + result.delta
    assert struct.unpack_from("<Q", out, meta["section_payload_start"])[0] == old_size_prefix + result.delta
    assert struct.unpack_from("<Q", out, moved_bun_header_off + 32)[0] == old_bun_section_size + result.delta
    reparsed = parse_bun_binary(out)
    assert _content(out, reparsed, 1) == "X" * 64


def test_replace_entry_js_shifts_late_elf_program_header_offset():
    data, _ = _build_elf_with_resize_headers(late_phoff=True)
    info = parse_bun_binary(data)
    old_e_phoff = struct.unpack_from("<Q", data, 32)[0]

    result = replace_entry_js(data, info, b"X" * 64)

    assert struct.unpack_from("<Q", result.buf, 32)[0] == old_e_phoff + result.delta


def test_replace_entry_js_strips_macho_code_signature_and_preserves_linkedit():
    data, meta = _build_signed_macho_with_linkedit()
    info = parse_bun_binary(data)
    old_ncmds = struct.unpack_from("<I", data, 16)[0]
    old_sizeofcmds = struct.unpack_from("<I", data, 20)[0]

    result = replace_entry_js(data, info, b"Y" * 32)

    out = result.buf
    assert info.has_code_signature is True
    assert result.signature_stripped is True
    assert struct.unpack_from("<I", out, 16)[0] == old_ncmds - 1
    assert struct.unpack_from("<I", out, 20)[0] == old_sizeofcmds - meta["code_sig_cmd_size"]
    linkedit_fileoff = struct.unpack_from("<Q", out, meta["linkedit_off"] + 40)[0]
    linkedit_filesize = struct.unpack_from("<Q", out, meta["linkedit_off"] + 48)[0]
    assert linkedit_filesize == meta["linkedit_prefix_size"]
    assert linkedit_fileoff + linkedit_filesize <= len(out)
    assert out[linkedit_fileoff : linkedit_fileoff + linkedit_filesize] == b"L" * meta["linkedit_prefix_size"]
    assert _has_load_command(out, meta["lc_code_signature"]) is False
    reparsed = parse_bun_binary(out)
    assert reparsed.has_code_signature is False
    assert _content(out, reparsed, 1) == "Y" * 32


def test_replace_entry_js_grown_macho_keeps_linkedit_vmaddr_contiguous():
    # A grown __BUN segment must slide __LINKEDIT's vmaddr along with its
    # file offset. Overlapping vm ranges get the binary SIGKILLed at exec
    # even after ad-hoc re-signing (seen with Claude Code 2.1.248+ arm64
    # variant builds whose patched modules grew the section past a page).
    data, meta = _build_signed_macho_with_linkedit()
    bun_segment_off = 32
    linkedit_off = meta["linkedit_off"]
    header = bytearray(data)
    old_section_size = struct.unpack_from("<Q", header, bun_segment_off + 32)[0]
    base = 0x100000
    struct.pack_into("<Q", header, bun_segment_off + 24, base)
    struct.pack_into("<Q", header, linkedit_off + 24, base + old_section_size)
    data = bytes(header)

    info = parse_bun_binary(data)
    old_bun_vmsize = struct.unpack_from("<Q", data, bun_segment_off + 32)[0]

    result = replace_entry_js(data, info, b"G" * 20000)

    out = result.buf
    bun_vmaddr = struct.unpack_from("<Q", out, bun_segment_off + 24)[0]
    bun_vmsize = struct.unpack_from("<Q", out, bun_segment_off + 32)[0]
    linkedit_vmaddr = struct.unpack_from("<Q", out, linkedit_off + 24)[0]
    assert bun_vmsize > old_bun_vmsize
    assert linkedit_vmaddr == base + old_section_size + (bun_vmsize - old_bun_vmsize)
    assert bun_vmaddr + bun_vmsize == linkedit_vmaddr


def test_pe_last_section_guard_rejects_not_last_bun_section():
    fixture = build_bun_fixture(
        platform="pe",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
        pe_extra_section_after=True,
    )
    info = parse_bun_binary(fixture["buf"])

    with pytest.raises(PeNotLastSectionError):
        repack_pe(fixture["buf"], info, b"hi", b"\x00" * OFFSETS_SIZE)


def test_pe_repack_rejects_truncated_pe_layout_cleanly():
    fixture = build_bun_fixture(
        platform="pe",
        module_struct_size=52,
        modules=THREE_MODULES,
        entry_point_id=1,
    )
    info = parse_bun_binary(fixture["buf"])

    with pytest.raises(ValueError, match="could not locate"):
        repack_pe(fixture["buf"][:64], info, b"hi", b"\x00" * OFFSETS_SIZE)
