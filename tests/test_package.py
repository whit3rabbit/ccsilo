import importlib
import importlib.metadata as metadata
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

import pytest

import ccsilo
from ccsilo._version import __version__
from ccsilo.cli.parsers import build_parser
from ccsilo.extractor import extract_all


def test_package_exports_are_loaded_lazily(monkeypatch):
    ccsilo.__dict__.pop("extract_all", None)
    import_calls = []

    def track_import(name, package=None):
        import_calls.append((name, package))
        return importlib.import_module(name, package)

    monkeypatch.setattr(ccsilo, "import_module", track_import)

    assert ccsilo.extract_all is extract_all
    assert import_calls == [(".extractor", "ccsilo")]


def test_package_metadata_has_publish_urls():
    meta = metadata.metadata("ccsilo")

    assert meta["Name"] == "ccsilo"
    project_urls = meta.get_all("Project-URL")
    assert "Repository, https://github.com/whit3rabbit/ccsilo" in project_urls


def test_runtime_version_matches_pyproject():
    if tomllib is None:
        pytest.skip("tomllib is unavailable")

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_cli_version_flags_print_package_version(flag, capsys):
    parser, _, _ = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args([flag])

    assert exc.value.code == 0
    assert capsys.readouterr().out == f"ccsilo {__version__}\n"
