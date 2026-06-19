"""
Python environment setup for AppImage builds.

Handles virtualenv creation, stdlib copying, package installation,
and system PyGObject fallback.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from utils.system import make_executable
from utils.i18n import _

# Mapping of Python import names to their pip package names
# Only needed when the import name differs from the pip package name
_IMPORT_TO_PIP: dict[str, str] = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "attr": "attrs",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "serial": "pyserial",
    "usb": "pyusb",
    "magic": "python-magic",
    "gi": "PyGObject",
    "cairo": "PyCairo",
    "Crypto": "pycryptodome",
    "jwt": "PyJWT",
    "websocket": "websocket-client",
    "socks": "PySocks",
    "skimage": "scikit-image",
    "wx": "wxPython",
    "xdg": "pyxdg",
    "usb1": "libusb1",
    "cups": "pycups",
    "gi.repository": "PyGObject",
    "odf": "odfpy",
    "OpenGL": "PyOpenGL",
    "OpenSSL": "pyOpenSSL",
    "dbus": "dbus-python",
    "Xlib": "python-xlib",
    "nacl": "PyNaCl",
    "zmq": "pyzmq",
    "slugify": "python-slugify",
    "dns": "dnspython",
    "git": "GitPython",
    "markdown": "Markdown",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "PyMuPDF",
    "google": "google-api-python-client",
}

# Development/test-only tooling that may be imported by tests, conftest, docs or
# build scripts but must never be bundled into the runtime AppImage. Compared
# against package names normalised to lower-case with "_" -> "-".
_DEV_PACKAGES: set[str] = {
    "pytest",
    "pytest-cov",
    "pytest-xdist",
    "pytest-mock",
    "pytest-asyncio",
    "pytest-timeout",
    "ruff",
    "mypy",
    "black",
    "flake8",
    "pyflakes",
    "pycodestyle",
    "pylint",
    "isort",
    "tox",
    "nox",
    "coverage",
    "pre-commit",
    "twine",
    "build",
    "wheel",
    "setuptools",
    "pip",
    "hypothesis",
    "bandit",
    "autopep8",
    "yapf",
    "sphinx",
    "mkdocs",
}

# cv2 functions that live in OpenCV's highgui (GUI) module. If an app calls any
# of these it needs the full opencv-python build; otherwise it can use the much
# smaller opencv-python-headless (no Qt5/GTK GUI stack).
_CV2_GUI_FUNCS: tuple[str, ...] = (
    "imshow",
    "namedWindow",
    "waitKey",
    "waitKeyEx",
    "startWindowThread",
    "destroyAllWindows",
    "destroyWindow",
    "selectROI",
    "selectROIs",
    "setMouseCallback",
    "createTrackbar",
    "getTrackbarPos",
    "setTrackbarPos",
    "getWindowProperty",
    "setWindowProperty",
    "getWindowImageRect",
    "moveWindow",
    "resizeWindow",
    "setWindowTitle",
    "createButton",
    "displayOverlay",
    "displayStatusBar",
)

# Full -> headless package substitutions.
_OPENCV_HEADLESS: dict[str, str] = {
    "opencv-python": "opencv-python-headless",
    "opencv-contrib-python": "opencv-contrib-python-headless",
}


class PythonEnvironmentSetup:
    """Sets up a Python virtualenv inside an AppDir for AppImage packaging."""

    def __init__(self, builder):
        self._b = builder

    def setup(self) -> None:
        """Setup Python virtualenv for Python applications."""
        self._b.log(_("Setting up Python environment..."))

        try:
            structure_analysis = self._b.app_info.structure_analysis or {}
            project_root_str = structure_analysis.get("project_root")

            if project_root_str:
                project_root = Path(project_root_str)
            else:
                project_root = Path(self._b.app_info.executable).parent
                project_root_str = str(project_root)

            # Start with essential packages for GTK/Python applications
            packages_to_install = ["PyGObject", "PyCairo"]

            # Prefer the project's *declared* dependencies (requirements.txt or
            # pyproject.toml [project.dependencies]). They are authoritative, so
            # when present we do NOT also scan imports. Import scanning is a
            # best-effort guess that can pull the wrong packages: local modules
            # in a src/ layout, names matched inside docstrings/comments, or
            # test-only deps. Mixing it in is what bloated builds with unrelated
            # packages, so declared deps win outright.
            declared = self._load_declared_dependencies(project_root)
            if declared is not None:
                packages_to_install.extend(declared)
            else:
                self._b.log(
                    _(
                        "No declared dependencies (requirements.txt / pyproject.toml). "
                        "Auto-detecting from source code..."
                    )
                )
                detected = self._detect_pip_dependencies(project_root_str)
                if detected:
                    self._b.log(
                        _("Auto-detected pip packages: {}").format(
                            ", ".join(detected)
                        )
                    )
                    packages_to_install.extend(detected)

            # Remove duplicates while preserving order and deduplicating by the
            # package base-name, so "requests" and "requests==2.0" don't both end
            # up installed (set() would also randomize the install order).
            def _base_name(spec: str) -> str:
                return re.split(r"[<>=!~\[ ]", spec.strip(), maxsplit=1)[0].lower()

            seen_names = set()
            deduped_packages = []
            for pkg in packages_to_install:
                if not pkg or not pkg.strip():
                    continue
                base = _base_name(pkg)
                if base in seen_names:
                    continue
                seen_names.add(base)
                deduped_packages.append(pkg.strip())

            requirements_content = "\n".join(deduped_packages)

            python_dir = self._b.appdir_path / "usr" / "python"
            python_dir.mkdir(parents=True, exist_ok=True)

            self._b.update_progress(55, _("Creating Python virtualenv..."))

            venv_path = python_dir / "venv"
            self._b.log(_("Creating isolated virtualenv at: {}").format(venv_path))

            # Create a clean venv with --copies flag for AppImage compatibility
            result = self._b._run_command(
                ["python3", "-m", "venv", "--copies", str(venv_path)], timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(
                    _("Failed to create virtualenv: {}").format(
                        result.stderr or result.stdout
                    )
                )

            self._b.log(_("Virtualenv created successfully."))

            # Copy Python stdlib to venv for portability
            self._b.log(_("Copying Python standard library to venv..."))
            self._b.update_progress(57, _("Copying Python stdlib..."))

            py_version_str, py_version_short, venv_stdlib_dest = (
                self._copy_stdlib(venv_path)
            )

            # Copy Python shared libraries to AppImage
            self._copy_python_libs(py_version_str)

            # Install required packages into the venv
            self._install_packages(venv_path, requirements_content, py_version_short)

            # Swap full opencv-python for the headless build when the app uses no
            # cv2 GUI functions (drops the Qt5 stack, even when opencv is only a
            # transitive dependency).
            self._optimize_opencv(venv_path, py_version_short, project_root_str)

            # Aggressive cleanup AFTER pip installation
            self._cleanup_venv(venv_path, venv_stdlib_dest, py_version_short)

            self._b.log(_("Python environment ready"))

        except subprocess.TimeoutExpired:
            raise RuntimeError(_("Python setup timed out"))
        except Exception as e:
            self._b.log(_("Python setup failed: {}").format(e))
            raise

    def _copy_stdlib(self, venv_path):
        """Copy Python stdlib into the venv. Returns (py_version_str, py_version_short, venv_stdlib_dest)."""
        try:
            # Detect Python version in build environment
            py_cmd = [
                "python3",
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ]
            result = self._b._run_command(py_cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                py_version_str = result.stdout.strip()
                self._b.python_version = py_version_str
                py_version_short = f"python{py_version_str}"
            else:
                # Fallback to host Python version
                host_py_version = (
                    f"{sys.version_info.major}.{sys.version_info.minor}"
                )
                self._b.log(
                    _(
                        "Warning: Could not detect Python version in container. Falling back to host version: {}"
                    ).format(host_py_version)
                )
                self._b.python_version = host_py_version
                py_version_short = f"python{self._b.python_version}"

            # Get stdlib path from build environment
            stdlib_cmd = [
                "python3",
                "-c",
                "import sysconfig; print(sysconfig.get_path('stdlib'))",
            ]
            result = self._b._run_command(stdlib_cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                stdlib_path = result.stdout.strip()
            else:
                import sysconfig

                stdlib_path = sysconfig.get_path("stdlib")

            venv_lib_dir = venv_path / "lib"
            venv_stdlib_dest = venv_lib_dir / py_version_short

            self._b.log(
                _("Copying stdlib from {} to {}").format(
                    stdlib_path, venv_stdlib_dest
                )
            )

            # Copy CONTENTS of stdlib
            if self._b.container_name:
                # Container: use script with wildcard
                copy_script = f"""#!/bin/bash
set -e
if [ ! -d "{stdlib_path}" ]; then
    echo "ERROR: stdlib not found at {stdlib_path}"
    exit 1
fi
mkdir -p "{venv_stdlib_dest}"
cp -r "{stdlib_path}"/* "{venv_stdlib_dest}/" || exit 1
if [ ! -d "{venv_stdlib_dest}/encodings" ]; then
    echo "ERROR: encodings module not found"
    exit 1
fi
"""
                script_path = self._b.build_dir / "copy_stdlib.sh"
                with open(script_path, "w") as f:
                    f.write(copy_script)
                make_executable(script_path)
                result = self._b._run_command([str(script_path)], timeout=120)
                if result.returncode != 0:
                    raise RuntimeError(_("Failed to copy stdlib from container"))
            else:
                # Local: iterate and copy contents
                if not Path(stdlib_path).exists():
                    raise RuntimeError(
                        _("Could not find stdlib at: {}").format(stdlib_path)
                    )

                venv_stdlib_dest.mkdir(parents=True, exist_ok=True)

                # Do NOT copy site-packages from system
                exclude_dirs = ["site-packages", "dist-packages"]

                for item in Path(stdlib_path).iterdir():
                    if item.name in exclude_dirs:
                        self._b.log(
                            _("Skipping system packages: {}").format(item.name)
                        )
                        continue

                    dest_item = venv_stdlib_dest / item.name
                    if item.is_dir():
                        if dest_item.exists():
                            shutil.rmtree(dest_item)
                        shutil.copytree(item, dest_item, symlinks=False)
                    else:
                        shutil.copy2(item, dest_item)

                if not (venv_stdlib_dest / "encodings").exists():
                    raise RuntimeError(
                        _("encodings module not found after stdlib copy")
                    )

            self._b.log(_("Python stdlib copied successfully"))

            # Clean up unnecessary files from stdlib
            self._b.log(_("Cleaning up copied stdlib..."))

            dirs_to_remove = [
                "test",
                "tests",
                "idlelib",
                "tkinter",
                "turtledemo",
                "ensurepip",
                "lib2to3",
                "distutils",
                "pydoc_data",
                "Tools",
            ]

            for dirname in dirs_to_remove:
                dir_path = venv_stdlib_dest / dirname
                if dir_path.is_dir():
                    shutil.rmtree(dir_path, ignore_errors=True)

            for pycache_dir in venv_stdlib_dest.rglob("__pycache__"):
                shutil.rmtree(pycache_dir, ignore_errors=True)

            self._b.log(_("Stdlib cleanup complete."))

        except Exception as e:
            self._b.log(_("Error copying Python stdlib: {}").format(e))
            raise RuntimeError(_("Python stdlib required for AppImage"))

        return py_version_str, py_version_short, venv_stdlib_dest

    def _copy_python_libs(self, py_version_str):
        """Copy Python shared libraries to AppImage lib dir."""
        self._b.log(_("Copying Python shared libraries..."))

        lib_dir = self._b.appdir_path / "usr" / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)

        python_lib_patterns = [
            f"/usr/lib/libpython{py_version_str}*.so*",
            f"/usr/lib/x86_64-linux-gnu/libpython{py_version_str}*.so*",
            f"/usr/lib64/libpython{py_version_str}*.so*",
        ]

        for pattern in python_lib_patterns:
            try:
                result = self._b._run_command(
                    ["sh", "-c", f"ls {pattern} 2>/dev/null || true"],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    for lib_path in result.stdout.strip().split("\n"):
                        lib_path = lib_path.strip()

                        should_copy = False
                        if self._b.container_name:
                            should_copy = bool(lib_path)
                        else:
                            should_copy = lib_path and os.path.exists(lib_path)

                        if should_copy:
                            lib_name = os.path.basename(lib_path)
                            dest = lib_dir / lib_name

                            copy_cmd = ["cp", "-L", lib_path, str(dest)]
                            result_cp = self._b._run_command(copy_cmd, timeout=10)
                            if result_cp.returncode == 0:
                                self._b.log(f"  Copied: {lib_name}")
                            else:
                                self._b.log(f"  Warning: Failed to copy {lib_name}")
            except Exception as e:
                self._b.log(
                    f"  Warning: Could not copy Python libs from {pattern}: {e}"
                )

        # `cp -L` above dereferences the .so symlink chain and writes several
        # byte-identical multi-MB copies (libpython.so, .so.1, .so.1.0).
        # Collapse the duplicates back into symlinks to save ~18 MB.
        try:
            dup_libs = sorted(lib_dir.glob(f"libpython{py_version_str}*.so*"))
            saved = self._dedup_identical_files(dup_libs)
            if saved:
                self._b.log(
                    _("  Deduplicated python libraries (saved {:.1f} MB)").format(
                        saved / 1024 / 1024
                    )
                )
        except Exception as e:
            self._b.log(f"  Warning: could not dedup python libraries: {e}")

        self._b.log(_("Python shared libraries copied"))

    @staticmethod
    def _dedup_identical_files(paths) -> int:
        """Replace byte-identical duplicate files with relative symlinks.

        Keeps the first path as the real file and points the rest at it. All
        paths must live in the same directory. Returns the bytes reclaimed.
        """
        import filecmp

        saved = 0
        canonical = None
        for p in paths:
            if not p.is_file() or p.is_symlink():
                continue
            if canonical is None:
                canonical = p
                continue
            try:
                if p.stat().st_size == canonical.stat().st_size and filecmp.cmp(
                    str(canonical), str(p), shallow=False
                ):
                    size = p.stat().st_size
                    p.unlink()
                    p.symlink_to(canonical.name)
                    saved += size
            except OSError:
                continue
        return saved

    def _install_packages(self, venv_path, requirements_content, py_version_short):
        """Install required packages into the venv."""
        self._b.update_progress(60, _("Installing Python packages..."))

        pip_executable = venv_path / "bin" / "pip"
        packages = [
            pkg.strip() for pkg in requirements_content.split("\n") if pkg.strip()
        ]

        self._b.log(_("Installing packages: {}").format(", ".join(packages)))

        install_env = None
        if self._b.container_name:
            install_env = os.environ.copy()
            pkg_config_paths = [
                "/usr/lib/x86_64-linux-gnu/pkgconfig",
                "/usr/share/pkgconfig",
                "/usr/lib/pkgconfig",
            ]
            existing_path = install_env.get("PKG_CONFIG_PATH", "")
            all_paths = pkg_config_paths + (
                [existing_path] if existing_path else []
            )
            install_env["PKG_CONFIG_PATH"] = ":".join(filter(None, all_paths))

        if not packages:
            self._b.log(_("No Python packages to install"))
            return

        # First try installing everything in a single call so pip can resolve
        # version constraints jointly (faster and avoids inconsistent pins).
        batch_cmd = [
            str(pip_executable),
            "install",
            "--no-warn-script-location",
            *packages,
        ]
        batch_result = self._b._run_command(batch_cmd, timeout=600, env=install_env)

        if batch_result.returncode == 0:
            self._b.log(_("Python packages installed"))
            return

        # Batch install failed; fall back to per-package installs so a single bad
        # package doesn't block the rest, and so the PyGObject fallback can run.
        self._b.log(
            _("Batch install failed, retrying packages individually...")
        )

        failed_packages = []
        for package in packages:
            self._b.log(_("Installing {}...").format(package))
            install_cmd = [
                str(pip_executable),
                "install",
                package,
                "--no-warn-script-location",
            ]

            result = self._b._run_command(install_cmd, timeout=300, env=install_env)

            if result.returncode != 0:
                self._b.log(
                    _("Warning: Failed to install {}: {}").format(
                        package, result.stderr or result.stdout
                    )
                )

                if package.lower() in ["pygobject", "pygi"]:
                    self._b.log(
                        _("Attempting fallback: using system PyGObject bindings")
                    )
                    self._use_system_pygobject(venv_path)
                else:
                    failed_packages.append(package)
            else:
                self._b.log(_("Successfully installed {}").format(package))

        if failed_packages:
            self._b.log(
                _("Warning: the following packages could not be installed: {}").format(
                    ", ".join(failed_packages)
                )
            )

        self._b.log(_("Python packages installed"))

    def _app_uses_cv2_gui(self, project_root: str) -> bool:
        """True if the app calls any cv2 highgui (GUI) function.

        Errs toward True (keep the full opencv build) so we never break an app
        that actually shows OpenCV windows.
        """
        root = Path(project_root)
        if not root.exists():
            return False
        attr_re = re.compile(r"cv2\s*\.\s*(" + "|".join(_CV2_GUI_FUNCS) + r")\b")
        from_re = re.compile(r"from\s+cv2\s+import\s+([^\n]+)")
        ignored = {
            "tests", "test", "testing", "docs", "doc", "examples", "example",
            ".git", "build", "dist", "node_modules", ".tox", ".venv", "venv",
        }
        for py_file in root.rglob("*.py"):
            try:
                rel_parts = py_file.relative_to(root).parts
            except ValueError:
                rel_parts = py_file.parts
            if any(seg in ignored for seg in rel_parts):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if attr_re.search(text):
                return True
            for m in from_re.finditer(text):
                if any(fn in m.group(1) for fn in _CV2_GUI_FUNCS):
                    return True
        return False

    def _optimize_opencv(self, venv_path, py_version_short, project_root: str):
        """Replace full opencv-python with the headless build when safe.

        The full wheel hard-links the Qt5 GUI stack (~25-30 MB) that a non-GUI
        app never uses. opencv-python is frequently a *transitive* dependency
        (e.g. rapidocr requires it), so swapping the declared requirement is not
        enough — we replace it in the installed venv after the fact.
        """
        site_packages = venv_path / "lib" / py_version_short / "site-packages"
        if not site_packages.exists():
            return

        installed_full = []
        for full_name in _OPENCV_HEADLESS:
            dist_glob = full_name.replace("-", "_") + "-*.dist-info"
            dist_dirs = list(site_packages.glob(dist_glob))
            if dist_dirs:
                installed_full.append((full_name, dist_dirs[0]))

        if not installed_full:
            return

        if self._app_uses_cv2_gui(project_root):
            self._b.log(
                _("Keeping full OpenCV build (app uses cv2 GUI functions).")
            )
            return

        pip_executable = venv_path / "bin" / "pip"
        for full_name, dist_dir in installed_full:
            headless_name = _OPENCV_HEADLESS[full_name]
            version = None
            try:
                stem = dist_dir.name[: -len(".dist-info")]
                version = stem.split("-")[-1]
            except Exception:
                version = None

            self._b.log(
                _("Replacing {} with {} (no cv2 GUI usage detected)...").format(
                    full_name, headless_name
                )
            )

            # Remove the full build first so its Qt5/ffmpeg libs go away cleanly
            # (via its RECORD), then install the headless build with no GUI libs.
            self._b._run_command(
                [str(pip_executable), "uninstall", "-y", full_name], timeout=120
            )

            headless_spec = (
                f"{headless_name}=={version}" if version else headless_name
            )
            result = self._b._run_command(
                [
                    str(pip_executable),
                    "install",
                    "--no-deps",
                    "--no-warn-script-location",
                    headless_spec,
                ],
                timeout=300,
            )
            if result.returncode != 0 and version:
                # exact-version headless not available — retry unpinned
                result = self._b._run_command(
                    [
                        str(pip_executable),
                        "install",
                        "--no-deps",
                        "--no-warn-script-location",
                        headless_name,
                    ],
                    timeout=300,
                )

            if result.returncode != 0:
                # Never leave cv2 broken: restore the full build.
                self._b.log(
                    _("Headless install failed; restoring {}.").format(full_name)
                )
                restore_spec = f"{full_name}=={version}" if version else full_name
                self._b._run_command(
                    [
                        str(pip_executable),
                        "install",
                        "--no-deps",
                        "--no-warn-script-location",
                        restore_spec,
                    ],
                    timeout=300,
                )
            else:
                self._b.log(
                    _("  {} installed (Qt5 GUI libraries dropped).").format(
                        headless_name
                    )
                )

    def _strip_shared_objects(self, venv_path):
        """Strip debug/local symbols from bundled .so files to reclaim space.

        Uses `strip --strip-unneeded`, which preserves the dynamic symbol table
        required for loading — safe for shared libraries, and a no-op on files
        that are already stripped.
        """
        strip_bin = shutil.which("strip")
        if not strip_bin:
            return
        stripped = 0
        saved = 0
        for so in venv_path.rglob("*.so*"):
            if not so.is_file() or so.is_symlink():
                continue
            try:
                before = so.stat().st_size
                result = subprocess.run(
                    [strip_bin, "--strip-unneeded", str(so)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                )
                if result.returncode == 0:
                    after = so.stat().st_size
                    if after < before:
                        saved += before - after
                        stripped += 1
            except (OSError, subprocess.SubprocessError):
                continue
        if stripped:
            self._b.log(
                _("  Stripped {} shared libraries (saved {:.1f} MB)").format(
                    stripped, saved / 1024 / 1024
                )
            )

    def _cleanup_venv(self, venv_path, venv_stdlib_dest, py_version_short):
        """Perform aggressive cleanup for size optimization."""
        self._b.log(_("Performing aggressive cleanup for size optimization..."))

        extra_dirs_to_remove = [
            "unittest",
            "__phello__",
            "turtle.py",
        ]

        for dirname in extra_dirs_to_remove:
            dir_path = venv_stdlib_dest / dirname
            if dir_path.is_dir():
                shutil.rmtree(dir_path, ignore_errors=True)
            elif dir_path.is_file():
                dir_path.unlink(missing_ok=True)

        # Clean up site-packages directory
        site_packages = venv_path / "lib" / py_version_short / "site-packages"
        if site_packages.exists():
            for dirname in [
                "pip",
                "setuptools",
                "pkg_resources",
                "_distutils_hack",
            ]:
                pkg_dir = site_packages / dirname
                if pkg_dir.is_dir():
                    shutil.rmtree(pkg_dir, ignore_errors=True)
                    self._b.log(_("  Removed: {}").format(dirname))

            for dist_info in site_packages.glob("*.dist-info"):
                if dist_info.is_dir():
                    shutil.rmtree(dist_info, ignore_errors=True)

            for pth_file in site_packages.glob("*.pth"):
                if pth_file.is_file():
                    try:
                        with open(pth_file, "r") as f:
                            content = f.read()
                        if "_distutils_hack" in content or "setuptools" in content:
                            pth_file.unlink()
                            self._b.log(_("  Removed: {}").format(pth_file.name))
                    except Exception:
                        pass

        # Remove all __pycache__ and .pyc files from entire venv
        self._b.log(_("Removing bytecode cache files..."))
        removed_pycache = 0
        removed_pyc = 0

        for pycache_dir in venv_path.rglob("__pycache__"):
            shutil.rmtree(pycache_dir, ignore_errors=True)
            removed_pycache += 1

        for pyc_file in venv_path.rglob("*.pyc"):
            pyc_file.unlink(missing_ok=True)
            removed_pyc += 1

        self._b.log(
            _("  Removed {} __pycache__ dirs and {} .pyc files").format(
                removed_pycache, removed_pyc
            )
        )

        # Remove static archives (*.a) — useless at runtime, often tens of MB
        # (e.g. libpython3.x.a + libpython3.x-pic.a ~= 27 MB).
        removed_static = 0
        static_bytes = 0
        for a_file in venv_path.rglob("*.a"):
            try:
                static_bytes += a_file.stat().st_size
            except OSError:
                pass
            a_file.unlink(missing_ok=True)
            removed_static += 1
        if removed_static:
            self._b.log(
                _("  Removed {} static .a archives ({:.1f} MB)").format(
                    removed_static, static_bytes / 1024 / 1024
                )
            )

        # Remove bundled test suites from installed packages — never used at
        # runtime, and heavy packages (numpy/scipy/pandas/numba/...) ship tens of
        # MB of them.
        if site_packages.exists():
            removed_tests = 0
            for tests_dir in list(site_packages.rglob("tests")):
                if tests_dir.is_dir():
                    shutil.rmtree(tests_dir, ignore_errors=True)
                    removed_tests += 1
            if removed_tests:
                self._b.log(
                    _("  Removed {} bundled test directories").format(removed_tests)
                )

        # De-duplicate the interpreter copies: `python -m venv --copies` writes
        # python / python3 / python3.x as three identical real binaries. Collapse
        # the duplicates into symlinks (~16 MB).
        bin_dir = venv_path / "bin"
        if bin_dir.is_dir():
            try:
                py_bins = sorted(
                    p
                    for p in bin_dir.glob("python*")
                    if p.is_file() and not p.is_symlink()
                )
                saved = self._dedup_identical_files(py_bins)
                if saved:
                    self._b.log(
                        _("  Deduplicated python binaries (saved {:.1f} MB)").format(
                            saved / 1024 / 1024
                        )
                    )
            except Exception:
                pass

        # Strip debug/local symbols from bundled shared libraries (OpenBLAS,
        # OpenCV, numpy/scipy extensions ship unstripped — tens of MB).
        self._strip_shared_objects(venv_path)

        self._b.log(_("Aggressive cleanup complete."))

    def _load_declared_dependencies(self, project_root: Path):
        """Return the project's *declared* runtime dependencies, or None.

        Looks for requirements.txt first, then pyproject.toml
        ([project].dependencies). Returns None when neither declares anything so
        the caller can fall back to scanning imports.
        """
        # 1) requirements.txt — closest to "exactly what to install"
        req = project_root / "requirements.txt"
        if req.exists():
            try:
                packages = []
                for line in req.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines():
                    line = line.split("#", 1)[0].strip()
                    # Skip pip option lines like "-r base.txt" / "--hash=..."
                    if line and not line.startswith("-"):
                        packages.append(line)
                if packages:
                    self._b.log(
                        _("Loaded {} packages from requirements.txt").format(
                            len(packages)
                        )
                    )
                    return packages
            except Exception as e:
                self._b.log(
                    _("Warning: could not read requirements.txt: {}").format(e)
                )

        # 2) pyproject.toml [project].dependencies
        pyproject = project_root / "pyproject.toml"
        if pyproject.exists():
            deps = self._read_pyproject_dependencies(pyproject)
            if deps:
                self._b.log(
                    _("Loaded {} dependencies from pyproject.toml").format(len(deps))
                )
                return deps

        return None

    @staticmethod
    def _read_pyproject_dependencies(pyproject_path: Path):
        """Parse [project].dependencies from pyproject.toml. Returns list or None."""
        try:
            try:
                import tomllib  # Python 3.11+
            except ModuleNotFoundError:
                try:
                    import tomli as tomllib  # backport for 3.8-3.10
                except ModuleNotFoundError:
                    return None
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            deps = data.get("project", {}).get("dependencies", [])
            cleaned = [d.strip() for d in deps if isinstance(d, str) and d.strip()]
            return cleaned or None
        except Exception:
            return None

    @staticmethod
    def _project_self_names(root: Path) -> set[str]:
        """Names that refer to the project itself and are never dependencies."""
        names: set[str] = set()
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                text = pyproject.read_text(encoding="utf-8", errors="ignore")
                m = re.search(
                    r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', text
                )
                if m:
                    base = m.group(1).strip().lower()
                    names.update({base, base.replace("-", "_"), base.replace("_", "-")})
            except Exception:
                pass
        # src-layout: every top-level package under src/ is local to the project
        src_dir = root / "src"
        if src_dir.is_dir():
            for child in src_dir.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    names.add(child.name)
        return names

    def _detect_pip_dependencies(self, project_root: str) -> list[str]:
        """Scan Python source files to auto-detect third-party pip dependencies."""
        root = Path(project_root)
        if not root.exists():
            return []

        py_files = list(root.rglob("*.py"))
        if not py_files:
            return []

        # Detect vendored directories (contain .dist-info siblings)
        vendored_dirs: set[str] = set()
        for dist_info in root.rglob("*.dist-info"):
            # The vendored package dir shares the parent with .dist-info
            pkg_name = dist_info.name.split("-")[0].lower()
            for sibling in dist_info.parent.iterdir():
                if sibling.is_dir() and sibling.name.lower() == pkg_name:
                    vendored_dirs.add(sibling.as_posix())

        # Collect ALL local module/package names. We scan recursively (not just
        # the top level) so that src-layout projects — where packages live under
        # src/<pkg>/ with no src/__init__.py — are still recognised as local and
        # not mistaken for PyPI packages. Without this, a local window.py wrongly
        # pulls the unrelated "window" package off PyPI.
        local_modules: set[str] = set()
        for py_file in py_files:
            local_modules.add(py_file.stem)
            parent = py_file.parent
            if (parent / "__init__.py").exists():
                local_modules.add(parent.name)
        # The project's own distribution/package name is never a dependency.
        local_modules |= self._project_self_names(root)

        # Directory segments to ignore when scanning for imports: test suites,
        # docs and build trees pull in dev-only deps (pytest, sphinx, ...) that
        # must not be bundled into the runtime AppImage.
        ignored_segments = {
            "tests", "test", "testing", "docs", "doc", "examples", "example",
            "benchmarks", "benchmark", ".git", "build", "dist", "node_modules",
            ".tox", ".venv", "venv",
        }

        # Collect top-level import names using the AST. Parsing (instead of regex
        # over raw text) means imports written inside docstrings/comments/strings
        # are never matched — that false-positive previously pulled a 178 MB
        # unrelated package off a single docstring line.
        import_names: set[str] = set()
        for py_file in py_files:
            file_path = py_file.as_posix()
            # Skip vendored packages
            if any(file_path.startswith(vdir) for vdir in vendored_dirs):
                continue
            # Skip test/doc/build trees and pytest files (relative to the project)
            try:
                rel_parts = py_file.relative_to(root).parts
            except ValueError:
                rel_parts = py_file.parts
            if any(seg in ignored_segments for seg in rel_parts):
                continue
            if py_file.name == "conftest.py" or py_file.name.startswith("test_"):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=file_path)
            except Exception:
                # Unparseable file — skip it rather than guessing from raw text.
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top:
                            import_names.add(top)
                elif isinstance(node, ast.ImportFrom):
                    # level > 0 is a relative import (from . / from ..) which is
                    # always a local module, never a PyPI package.
                    if node.level:
                        continue
                    if node.module:
                        top = node.module.split(".")[0]
                        if top:
                            import_names.add(top)

        # Get stdlib module names
        stdlib_modules: set[str] = set()
        if hasattr(sys, "stdlib_module_names"):
            stdlib_modules = sys.stdlib_module_names
        else:
            # Fallback for older Python
            stdlib_modules = {
                "abc",
                "aifc",
                "argparse",
                "array",
                "ast",
                "asynchat",
                "asyncio",
                "asyncore",
                "atexit",
                "base64",
                "bdb",
                "binascii",
                "binhex",
                "bisect",
                "builtins",
                "bz2",
                "calendar",
                "cgi",
                "cgitb",
                "chunk",
                "cmath",
                "cmd",
                "code",
                "codecs",
                "codeop",
                "collections",
                "colorsys",
                "compileall",
                "concurrent",
                "configparser",
                "contextlib",
                "contextvars",
                "copy",
                "copyreg",
                "cProfile",
                "crypt",
                "csv",
                "ctypes",
                "curses",
                "dataclasses",
                "datetime",
                "dbm",
                "decimal",
                "difflib",
                "dis",
                "distutils",
                "doctest",
                "email",
                "encodings",
                "enum",
                "errno",
                "faulthandler",
                "fcntl",
                "filecmp",
                "fileinput",
                "fnmatch",
                "fractions",
                "ftplib",
                "functools",
                "gc",
                "getopt",
                "getpass",
                "gettext",
                "glob",
                "grp",
                "gzip",
                "hashlib",
                "heapq",
                "hmac",
                "html",
                "http",
                "idlelib",
                "imaplib",
                "imghdr",
                "imp",
                "importlib",
                "inspect",
                "io",
                "ipaddress",
                "itertools",
                "json",
                "keyword",
                "lib2to3",
                "linecache",
                "locale",
                "logging",
                "lzma",
                "mailbox",
                "mailcap",
                "marshal",
                "math",
                "mimetypes",
                "mmap",
                "modulefinder",
                "multiprocessing",
                "netrc",
                "nis",
                "nntplib",
                "numbers",
                "operator",
                "optparse",
                "os",
                "ossaudiodev",
                "pathlib",
                "pdb",
                "pickle",
                "pickletools",
                "pipes",
                "pkgutil",
                "platform",
                "plistlib",
                "poplib",
                "posix",
                "posixpath",
                "pprint",
                "profile",
                "pstats",
                "pty",
                "pwd",
                "py_compile",
                "pyclbr",
                "pydoc",
                "queue",
                "quopri",
                "random",
                "re",
                "readline",
                "reprlib",
                "resource",
                "rlcompleter",
                "runpy",
                "sched",
                "secrets",
                "select",
                "selectors",
                "shelve",
                "shlex",
                "shutil",
                "signal",
                "site",
                "smtpd",
                "smtplib",
                "sndhdr",
                "socket",
                "socketserver",
                "sqlite3",
                "ssl",
                "stat",
                "statistics",
                "string",
                "stringprep",
                "struct",
                "subprocess",
                "sunau",
                "symtable",
                "sys",
                "sysconfig",
                "syslog",
                "tabnanny",
                "tarfile",
                "telnetlib",
                "tempfile",
                "termios",
                "test",
                "textwrap",
                "threading",
                "time",
                "timeit",
                "tkinter",
                "token",
                "tokenize",
                "tomllib",
                "trace",
                "traceback",
                "tracemalloc",
                "tty",
                "turtle",
                "turtledemo",
                "types",
                "typing",
                "unicodedata",
                "unittest",
                "urllib",
                "uu",
                "uuid",
                "venv",
                "warnings",
                "wave",
                "weakref",
                "webbrowser",
                "winreg",
                "winsound",
                "wsgiref",
                "xdrlib",
                "xml",
                "xmlrpc",
                "zipapp",
                "zipfile",
                "zipimport",
                "zlib",
                "zoneinfo",
                "_thread",
            }

        # Filter: keep only third-party imports
        third_party = import_names - stdlib_modules - local_modules
        # Remove internal/private modules
        third_party = {m for m in third_party if not m.startswith("_")}

        # Map to pip package names
        pip_packages: set[str] = set()
        for module in third_party:
            pip_name = _IMPORT_TO_PIP.get(module, module)
            pip_packages.add(pip_name)

        # Drop dev/test-only tooling (pytest, ruff, ...) and the packages already
        # in the default list.
        def _norm(name: str) -> str:
            return name.lower().replace("_", "-")

        pip_packages = {p for p in pip_packages if _norm(p) not in _DEV_PACKAGES}
        pip_packages.discard("PyGObject")
        pip_packages.discard("PyCairo")

        return sorted(pip_packages)

    def _use_system_pygobject(self, venv_path):
        """Fallback: Copy system PyGObject to venv when pip installation fails."""
        try:
            self._b.log(_("Copying system gi module to virtualenv..."))

            # Detect Python version
            py_cmd = [
                "python3",
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ]
            result = self._b._run_command(py_cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                py_version = f"python{result.stdout.strip()}"
            else:
                py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"

            # Source: system site-packages (Debian/Ubuntu and Red Hat/AlmaLinux paths)
            system_gi_paths = [
                f"/usr/lib/{py_version}/site-packages/gi",
                f"/usr/lib/{py_version}/dist-packages/gi",
                "/usr/lib/python3/dist-packages/gi",
                "/usr/lib/python3/site-packages/gi",
                f"/usr/lib64/{py_version}/site-packages/gi",
                "/usr/lib64/python3/site-packages/gi",
            ]

            source_gi = None
            for path in system_gi_paths:
                check_cmd = ["test", "-d", path]
                result = self._b._run_command(check_cmd, timeout=5)
                if result.returncode == 0:
                    source_gi = path
                    break

            if not source_gi:
                self._b.log(_("Error: System gi module not found"))
                return False

            # Destination: venv site-packages
            venv_site_packages = venv_path / "lib" / py_version / "site-packages"
            dest_gi = venv_site_packages / "gi"

            # Copy using container command
            copy_script = f"""#!/bin/bash
set -e
mkdir -p "{venv_site_packages}"

# Copy gi folder
cp -r "{source_gi}" "{dest_gi}"

# Copy _gi*.so files from dist-packages (Debian/Ubuntu)
for gi_file in /usr/lib/{py_version}/dist-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib/python3/dist-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

# Copy _gi*.so files from site-packages (Arch/Fedora)
for gi_file in /usr/lib/{py_version}/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib/python3/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

# Copy _gi*.so files from lib64/site-packages (Red Hat/AlmaLinux/Fedora)
for gi_file in /usr/lib64/{py_version}/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib64/python3/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

# Copy _gi_cairo*.so if exists (Debian/Ubuntu)
for gi_file in /usr/lib/{py_version}/dist-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib/python3/dist-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

# Copy _gi_cairo*.so from site-packages (Arch/Fedora)
for gi_file in /usr/lib/{py_version}/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib/python3/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

# Copy _gi_cairo*.so from lib64/site-packages (Red Hat/AlmaLinux/Fedora)
for gi_file in /usr/lib64/{py_version}/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

for gi_file in /usr/lib64/python3/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename "$gi_file")"
done

echo "System PyGObject copied successfully"
"""

            script_path = self._b.build_dir / "copy_pygobject.sh"
            with open(script_path, "w") as f:
                f.write(copy_script)
            make_executable(script_path)

            result = self._b._run_command([str(script_path)], timeout=60)

            if result.returncode == 0:
                self._b.log(_("System PyGObject copied successfully"))
                return True
            else:
                self._b.log(_("Failed to copy system PyGObject"))
                return False

        except Exception as e:
            self._b.log(_("Error using system PyGObject: {}").format(e))
            return False
