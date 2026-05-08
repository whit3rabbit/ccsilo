import json
import struct
import importlib

import pytest

from ccsilo.bun_extract import BunFormatError, extract_all, parse_bun_binary
from ccsilo.bun_extract.constants import MACHO_MAGIC_64, OFFSETS_SIZE, PE_DOS_MAGIC, TRAILER
from ccsilo.bun_extract.parser import MAX_MODULES
from ccsilo.__main__ import inspect_binary
from ccsilo.extractor import extract_all as extract_binary
from tests.helpers.bun_fixture import build_bun_fixture

extract_module = importlib.import_module("ccsilo.bun_extract.extract")


SAMPLE_MODULES = [
    {"name": "src/entrypoints/cli.js", "content": 'console.log("hello")'},
    {"name": "src/lib/util.js", "content": "export const ok = true"},
    {"name": "node_modules/foo/index.js", "content": "module.exports = 42"},
]


def test_parse_elf_fixture():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)

    info = parse_bun_binary(fixture["buf"])

    assert info.platform == "elf"
    assert info.module_size == 52
    assert info.bun_version_hint == ">=1.3.13"
    assert info.modules[0].name == "src/entrypoints/cli.js"
    assert info.data_start == fixture["expected"]["data_start"]
    assert info.data_start == info.trailer_offset - info.byte_count - OFFSETS_SIZE


def test_parse_macho_fixture():
    fixture = build_bun_fixture(
        platform="macho",
        module_struct_size=52,
        modules=SAMPLE_MODULES,
        with_code_signature=True,
        trailing_padding=1024,
    )

    info = parse_bun_binary(fixture["buf"])

    assert info.platform == "macho"
    assert info.data_start == fixture["expected"]["data_start"]
    assert info.section_offset == fixture["expected"]["section_offset"]
    assert info.has_code_signature is True
    assert info.modules[0].name == "src/entrypoints/cli.js"


def test_parse_pe_fixture():
    fixture = build_bun_fixture(platform="pe", module_struct_size=52, modules=SAMPLE_MODULES)

    info = parse_bun_binary(fixture["buf"])

    assert info.platform == "pe"
    assert info.data_start == fixture["expected"]["data_start"]
    assert len(info.modules) == 3


def test_parse_macho_without_section_uses_trailer_relative_payload():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    data = bytearray(fixture["buf"])
    struct.pack_into("<I", data, 0, MACHO_MAGIC_64)

    info = parse_bun_binary(bytes(data))

    assert info.platform == "macho"
    assert info.section_offset is None
    assert info.data_start == fixture["expected"]["data_start"]
    assert info.modules[0].name == "src/entrypoints/cli.js"


def test_parse_pe_without_section_uses_trailer_relative_payload():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    data = bytearray(fixture["buf"])
    struct.pack_into("<H", data, 0, PE_DOS_MAGIC)

    info = parse_bun_binary(bytes(data))

    assert info.platform == "pe"
    assert info.section_offset is None
    assert info.data_start == fixture["expected"]["data_start"]
    assert info.modules[0].name == "src/entrypoints/cli.js"


def test_parse_raw_payload_uses_elf_trailer_relative_payload():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    data = bytearray(fixture["buf"])
    data[:4] = b"RAW!"

    info = parse_bun_binary(bytes(data))

    assert info.platform == "elf"
    assert info.section_offset is None
    assert info.data_start == fixture["expected"]["data_start"]
    assert info.modules[0].name == "src/entrypoints/cli.js"


def test_module_table_size_36():
    fixture = build_bun_fixture(platform="elf", module_struct_size=36, modules=SAMPLE_MODULES)

    info = parse_bun_binary(fixture["buf"])

    assert info.module_size == 36
    assert info.bun_version_hint == "pre-1.3.13"
    assert info.modules[1].name == "src/lib/util.js"


def test_entry_module_detection():
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=SAMPLE_MODULES,
        entry_point_id=1,
    )

    info = parse_bun_binary(fixture["buf"])

    assert info.entry_point_id == 1
    assert info.modules[1].is_entry is True
    assert info.modules[0].is_entry is False


def test_invalid_trailer_throws_bun_format_error():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    broken[-len(TRAILER) :] = b"GARBAGE GARBAGE!"

    with pytest.raises(BunFormatError):
        parse_bun_binary(bytes(broken))


def test_parse_rejects_module_table_past_byte_count():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    offsets_start = len(broken) - len(TRAILER) - OFFSETS_SIZE
    byte_count = struct.unpack_from("<Q", broken, offsets_start)[0]
    struct.pack_into("<I", broken, offsets_start + 8, byte_count + 1)

    with pytest.raises(BunFormatError, match="module table extends past byteCount"):
        parse_bun_binary(bytes(broken))


def test_parse_rejects_excessive_module_count_before_iterating():
    module_size = 36
    byte_count = module_size * (MAX_MODULES + 1)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    offsets = bytearray(OFFSETS_SIZE)
    struct.pack_into("<Q", offsets, 0, byte_count)
    struct.pack_into("<I", offsets, 8, 0)
    struct.pack_into("<I", offsets, 12, byte_count)

    data = bytes(header) + (b"\0" * byte_count) + bytes(offsets) + TRAILER

    with pytest.raises(BunFormatError, match="too many modules"):
        parse_bun_binary(data)


def test_parse_rejects_invalid_entry_point_id():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    offsets_start = len(broken) - len(TRAILER) - OFFSETS_SIZE
    struct.pack_into("<I", broken, offsets_start + 16, len(SAMPLE_MODULES) + 10)

    with pytest.raises(BunFormatError, match="entryPointId"):
        parse_bun_binary(bytes(broken))


def test_parse_rejects_invalid_utf8_module_name():
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    broken[fixture["expected"]["data_start"]] = 0xFF

    with pytest.raises(BunFormatError, match="valid UTF-8"):
        parse_bun_binary(bytes(broken))


def test_parse_rejects_macho_bun_section_offset_outside_file():
    fixture = build_bun_fixture(platform="macho", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    section_header_off = 32 + 72
    struct.pack_into("<I", broken, section_header_off + 48, len(broken) + 1024)

    with pytest.raises(BunFormatError, match="Computed dataStart"):
        parse_bun_binary(bytes(broken))


def test_parse_rejects_pe_bun_section_offset_outside_file():
    fixture = build_bun_fixture(platform="pe", module_struct_size=52, modules=SAMPLE_MODULES)
    broken = bytearray(fixture["buf"])
    pe_offset = struct.unpack_from("<I", broken, 0x3C)[0]
    section_base = pe_offset + 24
    struct.pack_into("<I", broken, section_base + 20, len(broken) + 1024)

    with pytest.raises(BunFormatError, match="Computed dataStart"):
        parse_bun_binary(bytes(broken))


def test_path_prefixes_are_stripped():
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[
            {"name": "/$bunfs/root/src/main.js", "content": "1"},
            {"name": "$bunfs/root/lib/x.js", "content": "2"},
        ],
    )

    info = parse_bun_binary(fixture["buf"])

    assert info.modules[0].name == "src/main.js"
    assert info.modules[1].name == "lib/x.js"
    assert info.modules[0].raw_name == "/$bunfs/root/src/main.js"
    assert info.modules[0].name_off == 0
    assert info.modules[0].name_len == len("/$bunfs/root/src/main.js")


def test_extract_all_writes_files_and_manifest(tmp_path):
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    info = parse_bun_binary(fixture["buf"])

    result = extract_all(fixture["buf"], info, str(tmp_path))

    assert result.manifest_path is not None
    assert (tmp_path / "src/entrypoints/cli.js").read_text() == 'console.log("hello")'
    manifest = json.loads((tmp_path / ".bundle_manifest.json").read_text())
    assert manifest["platform"] == "elf"
    assert manifest["moduleSize"] == 52
    assert manifest["entryPoint"] == "src/entrypoints/cli.js"
    assert manifest["byteCount"] == info.byte_count
    assert manifest["execArgvOffset"] == info.exec_argv_offset
    assert manifest["execArgvLength"] == info.exec_argv_length
    assert manifest["modules"][0]["rawName"] == "src/entrypoints/cli.js"
    assert manifest["modules"][0]["nameOffset"] == info.modules[0].name_off
    assert manifest["modules"][0]["nameSize"] == info.modules[0].name_len


def test_extract_all_enforces_file_count_limit(tmp_path, monkeypatch):
    fixture = build_bun_fixture(platform="elf", module_struct_size=52, modules=SAMPLE_MODULES)
    info = parse_bun_binary(fixture["buf"])
    monkeypatch.setattr(extract_module, "MAX_EXTRACT_FILES", 1)

    with pytest.raises(BunFormatError, match="too many files"):
        extract_all(fixture["buf"], info, str(tmp_path))


def test_extract_all_enforces_single_file_size_limit(tmp_path, monkeypatch):
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[{"name": "src/large.js", "content": "ab"}],
    )
    info = parse_bun_binary(fixture["buf"])
    monkeypatch.setattr(extract_module, "MAX_EXTRACT_SINGLE_FILE_BYTES", 1)

    with pytest.raises(BunFormatError, match="oversized module"):
        extract_all(fixture["buf"], info, str(tmp_path))


def test_extract_all_refuses_path_traversal(tmp_path):
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[{"name": "../../../etc/evil", "content": "pwned"}],
    )
    info = parse_bun_binary(fixture["buf"])

    with pytest.raises(BunFormatError):
        extract_all(fixture["buf"], info, str(tmp_path))


@pytest.mark.parametrize(
    "module_name",
    [
        "C:/Users/alice/evil.js",
        "src/./evil.js",
        "src//evil.js",
    ],
)
def test_extract_all_refuses_windows_or_ambiguous_paths(tmp_path, module_name):
    fixture = build_bun_fixture(
        platform="elf",
        module_struct_size=52,
        modules=[{"name": module_name, "content": "pwned"}],
    )
    info = parse_bun_binary(fixture["buf"])

    with pytest.raises(BunFormatError):
        extract_all(fixture["buf"], info, str(tmp_path))


@pytest.mark.parametrize("platform", ["elf", "macho", "pe"])
def test_extractor_wrapper_extracts_cross_platform_fixtures(tmp_path, platform):
    fixture = build_bun_fixture(platform=platform, module_struct_size=52, modules=SAMPLE_MODULES)
    binary_path = tmp_path / f"fixture-{platform}"
    out_dir = tmp_path / f"out-{platform}"
    binary_path.write_bytes(fixture["buf"])

    manifest = extract_binary(str(binary_path), str(out_dir))

    assert manifest["platform"] == platform
    assert (out_dir / "src/entrypoints/cli.js").read_text() == 'console.log("hello")'
    assert (out_dir / ".bundle_source.json").exists()


def test_inspect_binary_json_payload(tmp_path, capsys):
    fixture = build_bun_fixture(platform="pe", module_struct_size=52, modules=SAMPLE_MODULES)
    binary_path = tmp_path / "fixture-pe"
    binary_path.write_bytes(fixture["buf"])

    payload = inspect_binary(str(binary_path), as_json=True)

    printed = json.loads(capsys.readouterr().out)
    assert payload["platform"] == "pe"
    assert printed["entryPoint"] == "src/entrypoints/cli.js"
