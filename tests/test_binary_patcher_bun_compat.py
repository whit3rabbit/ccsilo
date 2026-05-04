import shutil
import subprocess

import pytest

from cc_extractor.binary_patcher.bun_compat import BUN_NODE_COMPAT_MARKER, ensure_bun_node_compat


def test_ensure_bun_node_compat_prepends_marker_and_preserves_source():
    source = 'process.stdout.write(String(Bun.stringWidth("abc")));'

    patched = ensure_bun_node_compat(source)

    assert patched.startswith(BUN_NODE_COMPAT_MARKER)
    assert patched.endswith(source)
    assert patched.count(BUN_NODE_COMPAT_MARKER) == 1


def test_ensure_bun_node_compat_is_idempotent():
    source = ensure_bun_node_compat('process.stdout.write(String(Bun.hash("abc")));')

    assert ensure_bun_node_compat(source) == source


def test_bun_node_compat_executes_representative_apis(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    script = tmp_path / "compat.js"
    script.write_text(
        ensure_bun_node_compat(
            "\n".join(
                [
                    'const assert = require("assert");',
                    'assert.strictEqual(Bun.stringWidth("abc"), 3);',
                    'assert.strictEqual(Bun.stringWidth("\\u4e16"), 2);',
                    'assert.strictEqual(Bun.stripANSI("\\x1b[31mx\\x1b[0m"), "x");',
                    'assert.strictEqual(Bun.wrapAnsi("abcd", 2), "ab\\ncd");',
                    'assert.ok(Bun.hash("abc").toString());',
                    'assert.ok(Bun.semver.order("2.1.128", "2.1.0") > 0);',
                    'assert.strictEqual(Bun.JSONL.parseChunk("{\\"a\\":1}\\n").values[0].a, 1);',
                    'assert.ok(Bun.YAML.stringify({a: 1}).includes("a"));',
                    'assert.ok(Bun.which("node"));',
                    'assert.deepStrictEqual(Bun.embeddedFiles, []);',
                    'assert.strictEqual(typeof Bun.Transpiler, "function");',
                    'assert.throws(() => Bun.Terminal(), /not supported/);',
                    'process.stdout.write("ok");',
                ]
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
