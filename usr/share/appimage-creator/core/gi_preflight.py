"""
Preflight check for GObject-introspection API compatibility.

An app developed on a rolling-release host may use API that does not exist in
the (older) build container — e.g. Adw.ShortcutLabel needs libadwaita >= 1.8
while Ubuntu 24.04 ships 1.5. Since the AppImage bundles the container's
libraries and typelibs, such symbols crash at runtime on every target system.

This module scans the app's Python sources (AST) for `Namespace.Symbol`
usages of namespaces imported from gi.repository, then generates a small
probe script that runs *inside the build environment* and reports which
symbols are missing there, so the builder can warn before packaging.
"""

import ast
import json
from pathlib import Path

# Directory segments that never contain runtime application code.
_NON_SOURCE_SEGMENTS = {
    "tests", "test", "testing", "docs", "doc", "examples", "example",
    "benchmarks", "benchmark", ".git", "build", "dist", "node_modules",
    ".tox", ".venv", "venv", "__pycache__",
}


def collect_gi_usage(project_root):
    """
    Scan the project's runtime Python sources and return a tuple:
      versions: {namespace: version}      from gi.require_version() calls
      symbols:  {namespace: set(symbols)} from Namespace.Symbol accesses

    Symbols the app already feature-checks via hasattr(Ns, "Symbol") or
    getattr(Ns, "Symbol", ...) are excluded — their absence is handled.
    """
    root = Path(project_root)
    versions = {}
    symbols = {}
    guarded = set()  # (namespace, symbol) pairs feature-checked by the app

    for py_file in root.rglob("*.py"):
        try:
            rel_parts = py_file.relative_to(root).parts
        except ValueError:
            rel_parts = py_file.parts
        if any(seg in _NON_SOURCE_SEGMENTS for seg in rel_parts):
            continue
        if py_file.name == "conftest.py" or py_file.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(
                py_file.read_text(encoding="utf-8", errors="ignore"),
                filename=py_file.as_posix(),
            )
        except Exception:
            continue

        # Local name -> gi namespace (handles "from gi.repository import X as Y")
        gi_names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "gi.repository":
                for alias in node.names:
                    gi_names[alias.asname or alias.name] = alias.name

        for node in ast.walk(tree):
            # gi.require_version("Adw", "1")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "require_version"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "gi"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Constant)
            ):
                versions[str(node.args[0].value)] = str(node.args[1].value)
            elif not gi_names:
                continue
            # hasattr(Adw, "X") / getattr(Adw, "X", default) -> app handles it
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("hasattr", "getattr")
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in gi_names
                and isinstance(node.args[1], ast.Constant)
            ):
                guarded.add((gi_names[node.args[0].id], str(node.args[1].value)))
            # Adw.Something
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in gi_names
                and not node.attr.startswith("_")
            ):
                symbols.setdefault(gi_names[node.value.id], set()).add(node.attr)

    for ns, attr in guarded:
        if ns in symbols:
            symbols[ns].discard(attr)
    return versions, {ns: syms for ns, syms in symbols.items() if syms}


def build_probe_script(versions, symbols):
    """
    Generate a self-contained Python script that checks, in the environment
    where it runs, whether each collected symbol exists. Output lines:
      VERSION <ns> <major.minor>     environment version, when introspectable
      MISSING <ns>.<symbol>          symbol not present in the environment
      NAMESPACE <ns> <error>         namespace/version not importable at all
    """
    payload = {
        ns: {"version": versions.get(ns), "symbols": sorted(syms)}
        for ns, syms in symbols.items()
    }
    return (
        "import json\n"
        "import gi\n"
        f"PAYLOAD = json.loads({json.dumps(json.dumps(payload))})\n"
        "for ns, info in PAYLOAD.items():\n"
        "    try:\n"
        "        if info.get('version'):\n"
        "            gi.require_version(ns, info['version'])\n"
        "        mod = __import__('gi.repository.' + ns, fromlist=[ns])\n"
        "    except Exception as exc:\n"
        "        print('NAMESPACE {} {}'.format(ns, exc))\n"
        "        continue\n"
        "    major = getattr(mod, 'MAJOR_VERSION', None)\n"
        "    minor = getattr(mod, 'MINOR_VERSION', None)\n"
        "    if major is not None and minor is not None:\n"
        "        print('VERSION {} {}.{}'.format(ns, major, minor))\n"
        "    for sym in info['symbols']:\n"
        "        if not hasattr(mod, sym):\n"
        "            print('MISSING {}.{}'.format(ns, sym))\n"
    )
