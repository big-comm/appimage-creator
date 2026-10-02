"""
Application structure analysis and detection
"""

import json
import re
import shlex
import struct
import sys
from pathlib import Path
from utils.file_ops import get_file_type

# Build-system marker files that identify the source-project root of a
# compiled language (Rust, Go, C/C++, Zig, Autotools...). package.json is
# deliberately NOT listed: Electron app folders are self-contained bundles
# and must keep the whole-directory copy behavior.
BUILD_SYSTEM_MARKERS = (
    "Cargo.toml",      # Rust
    "go.mod",          # Go
    "meson.build",     # Meson (C/C++/Vala/...)
    "CMakeLists.txt",  # CMake
    "build.zig",       # Zig
    "configure.ac",    # Autotools
    "Makefile.am",     # Autotools
    "Makefile",        # Plain make
)

# Directories that only hold build artifacts or caches — never runtime
# resources. Skipped when scanning a compiled project for desktop files,
# icons and translations (a Rust target/ tree alone can hold gigabytes).
BUILD_ARTIFACT_DIRS = {
    "target", "build", "builddir", "_build", "dist", "out",
    "node_modules", ".git", ".github", ".cargo", ".venv", "venv",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
}


# Shell variable assignment: VAR=value (optionally export/readonly/local)
_SHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:export\s+|readonly\s+|local\s+)?([A-Za-z_]\w*)=(.*)$", re.M
)
# A python interpreter invocation and the rest of its command line.
# Matches python, python3, python3.12, /usr/bin/python3, env python3...
_PYTHON_CMD_RE = re.compile(
    r"(?:^|[\s;&|(`])(?:\S*/)?python(?:3(?:\.\d+)?)?(?=[ \t])(.*)$", re.M
)
_CD_BEFORE_RE = re.compile(r"\bcd\s+(\"[^\"]+\"|'[^']+'|\S+)\s*(?:&&|;)")
_SHELL_VAR_RE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")
# Interpreter options that consume the following argument
_PYTHON_OPTS_WITH_ARG = {"-X", "-W", "-Q"}
_SHELL_OPERATORS = {";", "&&", "||", "|", "&", ">", ">>", "<", "2>", "2>&1"}


def find_usr_project_root(start: Path, max_levels: int = 5) -> Path | None:
    """Walk up from ``start`` looking for a directory that contains ``usr/``.
    Never returns the filesystem root."""
    current = start
    for _ in range(max_levels):
        if current == current.parent:
            break
        if (current / "usr").is_dir():
            return current
        current = current.parent
    return None


def _strip_shell_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _expand_shell_vars(text: str, variables: dict, depth: int = 0) -> str:
    """Expand $VAR / ${VAR} using assignments found in the script. Unknown
    variables and command substitutions are left untouched."""
    if depth > 5:
        return text

    def repl(m):
        name = m.group(1) or m.group(2)
        if name in variables:
            return _expand_shell_vars(variables[name], variables, depth + 1)
        return m.group(0)

    return _SHELL_VAR_RE.sub(repl, text)


def _static_path_suffix(path: str) -> list[str]:
    """Trailing path components that contain no shell expansion, e.g.
    ``$(dirname "$D")/share/app/main.py`` -> ``["share", "app", "main.py"]``."""
    parts = path.split("/")
    suffix = []
    for part in reversed(parts):
        if not part or any(c in part for c in "$`()"):
            break
        suffix.append(part)
    return list(reversed(suffix))


def _python_targets_from_command(args: str) -> list[str]:
    """Extract script candidates from the arguments of a python invocation."""
    try:
        tokens = shlex.split(args, comments=True)
    except ValueError:
        # Unbalanced quotes (e.g. command continues on the next line)
        tokens = args.split()

    targets = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _SHELL_OPERATORS:
            break
        if tok == "-c":
            break  # inline code: handled by entry point detection
        if tok == "-m":
            if i + 1 < len(tokens):
                targets.append(tokens[i + 1].replace(".", "/") + ".py")
            break
        if tok in _PYTHON_OPTS_WITH_ARG:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if tok in ("$@", "$*", "${@}", "${*}"):
            break
        targets.append(tok)
        break
    return targets


def _resolve_wrapper_python_target(script_path: str, content: str) -> Path | None:
    """Find the Python script a shell wrapper executes, inside its project."""
    variables = {}
    for m in _SHELL_ASSIGN_RE.finditer(content):
        variables.setdefault(m.group(1), _strip_shell_quotes(m.group(2)))

    candidates = []
    for line in content.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _PYTHON_CMD_RE.search(line)
        if m:
            targets = _python_targets_from_command(m.group(1))
            # `cd <dir> && python3 main.py`: a relative target lives in <dir>
            cd = _CD_BEFORE_RE.search(line[: m.start()])
            if cd:
                base = _strip_shell_quotes(cd.group(1))
                targets = [
                    t if t.startswith(("/", "$")) else f"{base.rstrip('/')}/{t}"
                    for t in targets
                ]
            candidates.extend(targets)
    # Fallback: any .py path mentioned in the script (assignments included)
    candidates.extend(re.findall(r"[^\s\"'=]*\.py\b", content))

    script = Path(script_path).resolve()
    project_root = find_usr_project_root(script.parent) or script.parent.parent

    for raw in candidates:
        expanded = _expand_shell_vars(raw, variables)
        suffix = _static_path_suffix(expanded)
        if not suffix:
            continue
        if not suffix[-1].endswith(".py"):
            # Extension-less target (python3 /usr/share/app/app "$@")
            literal = project_root.joinpath(*suffix)
            if literal.is_file():
                return literal
            suffix[-1] += ".py"
        best = _best_suffix_match(project_root, suffix)
        if best is not None:
            return best
    return None


def _best_suffix_match(project_root: Path, suffix: list[str]) -> Path | None:
    """Among files named ``suffix[-1]`` under ``project_root``, pick the one
    whose path shares the longest trailing component sequence with ``suffix``
    (ties go to the shallowest path)."""
    best, best_key = None, None
    for found in project_root.rglob(suffix[-1]):
        rel_parts = found.relative_to(project_root).parts
        if not found.is_file() or any(p in BUILD_ARTIFACT_DIRS for p in rel_parts):
            continue
        score = 0
        for a, b in zip(reversed(rel_parts), reversed(suffix)):
            if a != b:
                break
            score += 1
        key = (score, -len(rel_parts))
        if best_key is None or key > best_key:
            best, best_key = found, key
    return best


def analyze_wrapper_script(script_path: str) -> dict:
    """Analyze wrapper script to detect underlying application type"""
    try:
        with open(script_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        analysis = {
            "type": "shell",
            "target_executable": None,
            "target_type": None,
            "dependencies": [],
            "additional_paths": [],
        }

        # Look for Python calls (improved regex patterns)
        python_patterns = [
            r"\bpython3?\b",  # python or python3
            r"\bpython3\.\d+\b",  # python3.11, python3.12, etc.
            r"/usr/bin/python3?",  # /usr/bin/python or /usr/bin/python3
            r"/usr/bin/env\s+python3?",  # /usr/bin/env python or python3
        ]

        if any(
            re.search(pattern, content, re.IGNORECASE) for pattern in python_patterns
        ):
            analysis["type"] = "python_wrapper"

            target_path = _resolve_wrapper_python_target(script_path, content)
            if target_path is not None:
                print(
                    f"[DEBUG analyze_wrapper_script] Python target: {target_path}",
                    file=sys.stderr,
                )
                analysis["target_executable"] = str(target_path)
                analysis["target_type"] = "python"

        # Look for other interpreters
        elif "node" in content or "nodejs" in content:
            analysis["type"] = "nodejs_wrapper"
            analysis["target_type"] = "javascript"
        elif "java" in content:
            analysis["type"] = "java_wrapper"
            analysis["target_type"] = "java"

        # Look for dependencies
        if "TEXTDOMAINDIR" in content:
            analysis["dependencies"].append("locale")
        if "LD_LIBRARY_PATH" in content:
            analysis["dependencies"].append("libraries")
        if "QT_" in content:
            analysis["dependencies"].append("qt")
        if "GTK_" in content or "GSETTINGS" in content:
            analysis["dependencies"].append("gtk")

        return analysis

    except Exception as e:
        return {"type": "shell", "error": str(e)}


def detect_application_structure(executable_path: str) -> dict:
    """Detect complex application structure from executable"""
    path = Path(executable_path).resolve()

    # DEBUG: Log file type detection
    file_type = get_file_type(executable_path)
    print(f"[DEBUG] File: {path.name}, Detected type: {file_type}", file=sys.stderr)

    # Check if it's a shell script by shebang OR file type
    if file_type == "shell":
        wrapper_analysis = analyze_wrapper_script(executable_path)
        if wrapper_analysis.get("type") == "python_wrapper":
            # Even for wrappers, we need to find the project root
            project_root = find_usr_project_root(path.parent)

            # Create structure for python wrapper
            structure = {
                "type": "python_wrapper",
                "main_executable": str(path),
                "project_root": str(project_root) if project_root else str(path.parent),
                "detected_files": {"desktop_files": [], "icons": [], "locale_dirs": []},
                "wrapper_analysis": wrapper_analysis,
                "has_desktop_file": False,
            }

            # Scan for desktop files, icons, etc if we found a project root
            if project_root:
                _scan_project_root(project_root, structure)
                structure["has_desktop_file"] = (
                    len(structure["detected_files"]["desktop_files"]) > 0
                )
                # All launchers this package exposes (primary + secondaries).
                # The builder/UI separate the primary (matching the selected
                # executable) from the secondaries the user opts to bundle.
                structure["entry_points"] = detect_entry_points(project_root)

            return structure

    # Compiled artifact (ELF) inside a source project: the program is the
    # binary itself, so the source tree must never be copied wholesale.
    if file_type == "binary":
        compiled_structure = _detect_compiled_structure(path)
        if compiled_structure:
            return compiled_structure

    structure = {
        "type": "simple",
        "main_executable": str(path),
        "project_root": None,  # Key change: We will find the project root
        "detected_files": {
            "desktop_files": [],
            "icons": [],
            "locale_dirs": [],
        },
        "wrapper_analysis": None,
        "has_desktop_file": False,
    }

    # Find project root by searching for a 'usr' directory in parent paths
    # but never use the filesystem root as project root
    project_root = find_usr_project_root(path.parent)

    if project_root:
        structure["project_root"] = str(project_root)
        structure["type"] = "structured_project"
        # Scan for files ONLY within the project root
        _scan_project_root(project_root, structure)
        # All launchers this package exposes (primary + secondaries)
        structure["entry_points"] = detect_entry_points(project_root)
    else:
        # Fallback for simple cases: project root is the executable's directory
        structure["project_root"] = str(path.parent)
        _scan_project_root(path.parent, structure)

    structure["has_desktop_file"] = (
        len(structure["detected_files"]["desktop_files"]) > 0
    )

    # Detect Electron app_id from resources/app.asar
    if structure.get("project_root"):
        electron_id = _detect_electron_app_id(Path(structure["project_root"]))
        if electron_id:
            structure["electron_app_id"] = electron_id
            print(f"[DEBUG] Electron app_id detected: {electron_id}", file=sys.stderr)

    return structure


def _looks_like_electron_bundle(exe_dir: Path) -> bool:
    """Detect an Electron/Chromium app folder next to the selected ELF."""
    return (
        (exe_dir / "resources" / "app.asar").exists()
        or (exe_dir / "chrome-sandbox").exists()
        or (exe_dir / "libffmpeg.so").exists()
    )


def _detect_compiled_structure(path: Path) -> dict | None:
    """
    Build the structure for a compiled executable (ELF) that lives inside a
    source project (Rust, Go, C/C++...). The artifact IS the program, so the
    builder copies only the binary to usr/bin and harvests installable
    resources (usr/share, compiled locale) from the resource root — never
    the source tree with its build directories (a Rust target/ can hold
    gigabytes of artifacts).

    Returns None when the executable does not look like the artifact of a
    source project; the caller then keeps the legacy behavior. This keeps
    Electron app folders and bare binaries with adjacent data files working
    exactly as before.
    """
    exe_dir = path.parent

    # Electron/Chromium bundles are self-contained folders that need the
    # whole-directory copy (resources/, locales/, bundled .so files).
    if _looks_like_electron_bundle(exe_dir):
        return None

    project_root = None
    current = exe_dir
    for _ in range(5):  # Search up to 5 levels
        if current == current.parent:
            break  # Reached filesystem root
        if any((current / marker).is_file() for marker in BUILD_SYSTEM_MARKERS):
            project_root = current
            break
        current = current.parent

    if not project_root:
        return None  # Not a source project — keep legacy behavior

    structure = {
        "type": "compiled",
        "main_executable": str(path),
        # Deliberately None so the whole-tree copy path in the builder and
        # the Python source scanners never run for compiled artifacts.
        "project_root": None,
        "resource_root": str(project_root),
        "build_markers": [
            m for m in BUILD_SYSTEM_MARKERS if (project_root / m).is_file()
        ],
        "detected_files": {"desktop_files": [], "icons": [], "locale_dirs": []},
        "wrapper_analysis": None,
        "has_desktop_file": False,
    }

    _scan_project_root(
        project_root, structure, extra_skip_dirs=BUILD_ARTIFACT_DIRS
    )
    structure["has_desktop_file"] = (
        len(structure["detected_files"]["desktop_files"]) > 0
    )

    print(
        f"[DEBUG] Compiled project detected (markers: {structure['build_markers']}), "
        f"resource root: {project_root}",
        file=sys.stderr,
    )
    return structure


def _looks_cli(name: str) -> bool:
    """Heuristic: does this entry point name denote a command-line tool?"""
    low = name.lower()
    return low.endswith(("-cli", "-cmd", "-term")) or low.endswith("cli")


def _entry_from_python_c(content: str) -> tuple[str, str] | None:
    """Extract (module, func) from a `python -c "from <mod> import <f>; <f>()"`
    style wrapper. Returns None when no such pattern is present."""
    m = re.search(
        r"from\s+([\w.]+)\s+import\s+(\w+)\s*;?\s*\2\s*\(", content
    )
    if m:
        return m.group(1), m.group(2)
    # `python -m package` form
    m = re.search(r"python3?\s+-m\s+([\w.]+)", content)
    if m:
        return m.group(1), ""  # -m module (no explicit func)
    return None


def detect_entry_points(project_root: Path) -> list[dict]:
    """
    Detect the launchers a Python project exposes, so a single AppImage can
    ship more than one entry point sharing the same venv (e.g. a GUI plus a
    second GUI or a CLI).

    Two sources are merged, keyed by launcher name:
      1. Wrapper scripts in ``usr/bin/`` — what the package actually installs.
         These are the source of truth (a project's pyproject can be out of
         sync with the wrappers it ships).
      2. ``pyproject.toml`` ``[project.scripts]`` / ``[project.gui-scripts]``.

    Each returned item: ``{"name", "module", "func", "is_gui", "source"}``.
    Only module/func launchers are returned (they map cleanly to
    ``python -c "from <module> import <func>; <func>()"`` regardless of cwd).
    """
    root = Path(project_root)
    entries: dict[str, dict] = {}

    # --- Source 1: wrapper scripts shipped in usr/bin/ -----------------
    bin_dir = root / "usr" / "bin"
    if bin_dir.is_dir():
        for wrapper in sorted(bin_dir.iterdir()):
            if not wrapper.is_file():
                continue
            try:
                content = wrapper.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "python" not in content:
                continue
            parsed = _entry_from_python_c(content)
            if not parsed:
                continue
            module, func = parsed
            name = wrapper.name
            entries[name] = {
                "name": name,
                "module": module,
                "func": func,
                "is_gui": not _looks_cli(name),
                "source": "wrapper",
            }

    # --- Source 2: pyproject.toml entry points -------------------------
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            for table, is_gui in (
                ("scripts", False),
                ("gui-scripts", True),
            ):
                for name, target in (project.get(table) or {}).items():
                    # target form: "module.path:func"
                    if ":" not in str(target):
                        continue
                    module, func = str(target).split(":", 1)
                    module, func = module.strip(), func.strip()
                    if name in entries:
                        continue  # wrapper wins (it's what's really shipped)
                    entries[name] = {
                        "name": name,
                        "module": module,
                        "func": func,
                        # gui-scripts are GUI; scripts are CLI unless the name
                        # says otherwise
                        "is_gui": is_gui and not _looks_cli(name),
                        "source": "pyproject",
                    }
        except (OSError, ValueError, ImportError):
            pass

    return list(entries.values())


def _detect_electron_app_id(project_root: Path) -> str | None:
    """Extract Electron app name from resources/app.asar for Wayland app_id."""
    asar_path = project_root / "resources" / "app.asar"
    if not asar_path.exists():
        return None

    try:
        with open(asar_path, "rb") as f:
            header_data = f.read(16)
            if len(header_data) < 16:
                return None
            header_string_size = struct.unpack("<I", header_data[12:16])[0]
            header_json = f.read(header_string_size).decode("utf-8")
            header = json.loads(header_json)

        # Find package.json in the asar header
        pkg_entry = header.get("files", {}).get("package.json", {})
        if "offset" not in pkg_entry or "size" not in pkg_entry:
            return None

        offset = int(pkg_entry["offset"])
        size = int(pkg_entry["size"])

        with open(asar_path, "rb") as f:
            f.seek(16 + header_string_size + offset)
            pkg_data = f.read(size)
            pkg_json = json.loads(pkg_data)

        # productName has priority (display name), but name is the app_id
        return pkg_json.get("name") or None
    except Exception:
        return None


def _scan_project_root(project_root_path, structure, extra_skip_dirs=None):
    """Scans for common files within a given project root directory."""
    root = Path(project_root_path)

    # Directories to skip during scanning (Electron/node heavy dirs)
    _skip_dirs = {"node_modules", ".git", "__pycache__", "locales"}
    if extra_skip_dirs:
        _skip_dirs = _skip_dirs | set(extra_skip_dirs)

    def _walk(base: Path):
        """Yield files under base, skipping heavy directories."""
        try:
            for entry in base.iterdir():
                if entry.is_dir():
                    if entry.name in _skip_dirs:
                        continue
                    yield from _walk(entry)
                else:
                    yield entry
        except PermissionError:
            pass

    for item in _walk(root):
        suffix = item.suffix.lower()
        name = item.name.lower()

        # Desktop files (exclude known auxiliary desktop files like updater/vainfo)
        if suffix == ".desktop":
            _excluded = ("updater", "vainfo")
            if not any(ex in name for ex in _excluded):
                structure["detected_files"]["desktop_files"].append(str(item))

        # Icons: files in "icons" dirs, or common icon filenames at project root
        elif suffix in (".svg", ".png"):
            if "icons" in str(item):
                structure["detected_files"]["icons"].append(str(item))
            elif name in ("icon.png", "icon.svg") or (
                item.parent == root and suffix in (".svg", ".png")
            ):
                structure["detected_files"]["icons"].append(str(item))

        # Locale directories (via .mo files)
        elif name.endswith(".mo") and "LC_MESSAGES" in str(item):
            locale_dir = item.parent.parent.parent
            if (
                locale_dir.name == "locale"
                and str(locale_dir) not in structure["detected_files"]["locale_dirs"]
            ):
                structure["detected_files"]["locale_dirs"].append(str(locale_dir))
