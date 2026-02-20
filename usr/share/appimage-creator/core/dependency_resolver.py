"""
Recursive ldd-based shared library resolver for AppImage builds.

Scans all .so and executable files in an AppDir, identifies missing
shared libraries, and copies them from the build system (host or container).
"""

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from utils.i18n import _


class DependencyResolver:
    """Resolves and bundles missing shared libraries recursively via ldd."""

    # Libraries that MUST come from the host system (never bundle).
    # Bundling these causes crashes or ABI incompatibilities.
    HOST_ONLY_PATTERNS = (
        "linux-vdso.so",
        "ld-linux-x86-64.so",
        "ld-linux-aarch64.so",
        "libc.so",
        "libpthread.so",
        "libdl.so",
        "librt.so",
        "libm.so",
        "libresolv.so",
        "libnss_",
        "libthread_db.so",
        "libBrokenLocale.so",
        "libSegFault.so",
        "libanl.so",
        "libcidn.so",
        "libcrypt.so",
        "libmvec.so",
        "libutil.so",
    )

    # Standard system library search paths
    SYSTEM_LIB_PATHS = [
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib64",
        "/lib/x86_64-linux-gnu",
        "/lib64",
        "/usr/lib",
        "/lib",
        "/usr/lib/aarch64-linux-gnu",
        "/lib/aarch64-linux-gnu",
    ]

    def __init__(
        self,
        log_fn: Callable[[str], None],
        run_command_fn: Optional[Callable] = None,
    ):
        """
        Args:
            log_fn: Logging function (e.g. builder.log)
            run_command_fn: Optional function to run commands in container
                           (e.g. builder._run_command). If None, runs locally.
        """
        self._log = log_fn
        self._run_command = run_command_fn

    def _is_host_only(self, lib_name: str) -> bool:
        """Check if a library must come from the host system."""
        for pattern in self.HOST_ONLY_PATTERNS:
            if lib_name.startswith(pattern):
                return True
        return False

    def _exec(self, cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Execute a command, optionally through the container."""
        if self._run_command:
            return self._run_command(cmd, timeout=timeout, capture_output=True)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _find_elf_files(self, appdir: Path) -> list[Path]:
        """Find all ELF binaries and shared libraries in the AppDir."""
        elf_files: list[Path] = []
        for root, _dirs, files in os.walk(appdir):
            for fname in files:
                fpath = Path(root) / fname
                if fpath.is_symlink():
                    continue
                if fname.endswith(".so") or ".so." in fname:
                    elf_files.append(fpath)
                elif fpath.stat().st_size > 0:
                    # Check if it's an executable ELF
                    parent_name = fpath.parent.name
                    if parent_name == "bin" or (
                        os.access(fpath, os.X_OK)
                        and not fname.endswith(
                            (
                                ".py",
                                ".sh",
                                ".desktop",
                                ".svg",
                                ".png",
                                ".xml",
                                ".json",
                                ".txt",
                                ".md",
                                ".typelib",
                                ".theme",
                                ".cache",
                            )
                        )
                    ):
                        try:
                            with open(fpath, "rb") as f:
                                magic = f.read(4)
                            if magic == b"\x7fELF":
                                elf_files.append(fpath)
                        except (OSError, PermissionError):
                            pass
        return elf_files

    def _run_ldd(self, elf_path: Path) -> list[str]:
        """Run ldd on a file and return list of 'not found' library names."""
        missing: list[str] = []
        try:
            result = self._exec(["ldd", str(elf_path)], timeout=15)
            if result.returncode != 0:
                return missing
            for line in result.stdout.splitlines():
                line = line.strip()
                # Pattern: "libfoo.so.1 => not found"
                if "not found" in line:
                    lib_name = line.split()[0]
                    if not self._is_host_only(lib_name):
                        missing.append(lib_name)
        except (subprocess.TimeoutExpired, Exception):
            pass
        return missing

    def _find_lib_in_system(self, lib_name: str) -> Optional[str]:
        """Find a library file in standard system paths."""
        for search_path in self.SYSTEM_LIB_PATHS:
            candidate = f"{search_path}/{lib_name}"
            try:
                result = self._exec(["test", "-f", candidate], timeout=5)
                if result.returncode == 0:
                    return candidate
            except Exception:
                pass

        # Fallback: use find command
        try:
            result = self._exec(
                ["find", "/usr/lib", "/lib", "-name", lib_name, "-type", "f"],
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0]
        except Exception:
            pass
        return None

    def _copy_lib(self, source_path: str, dest_dir: Path) -> bool:
        """Copy a library from source to destination."""
        lib_name = os.path.basename(source_path)
        dest = dest_dir / lib_name
        if dest.exists():
            return True
        try:
            result = self._exec(["cp", "-L", source_path, str(dest)], timeout=15)
            return result.returncode == 0
        except Exception:
            return False

    def resolve(self, appdir: Path, max_iterations: int = 3) -> dict:
        """
        Recursively resolve all missing shared libraries in an AppDir.

        Args:
            appdir: Path to the AppDir root
            max_iterations: Maximum resolution iterations (prevents infinite loops)

        Returns:
            dict with keys:
                'copied': list of library names that were copied
                'missing': list of library names that could not be found
                'iterations': number of iterations performed
        """
        self._log(_("Starting recursive dependency resolution..."))

        lib_dir = appdir / "usr" / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)

        all_copied: list[str] = []
        all_missing: set[str] = set()
        iteration = 0

        for iteration in range(1, max_iterations + 1):
            self._log(
                _("  Resolution iteration {}/{}...").format(iteration, max_iterations)
            )

            # Scan all ELF files
            elf_files = self._find_elf_files(appdir)
            self._log(_("  Found {} ELF files to scan").format(len(elf_files)))

            # Run ldd on each and collect missing libs
            missing_this_round: set[str] = set()
            for elf_path in elf_files:
                missing_libs = self._run_ldd(elf_path)
                for lib in missing_libs:
                    if lib not in all_missing:
                        missing_this_round.add(lib)

            if not missing_this_round:
                self._log(_("  No missing libraries found — resolution complete"))
                break

            self._log(
                _("  Found {} missing libraries: {}").format(
                    len(missing_this_round), ", ".join(sorted(missing_this_round))
                )
            )

            # Try to find and copy each missing lib
            newly_copied = 0
            for lib_name in sorted(missing_this_round):
                source = self._find_lib_in_system(lib_name)
                if source:
                    if self._copy_lib(source, lib_dir):
                        self._log(_("    Copied: {}").format(lib_name))
                        all_copied.append(lib_name)
                        newly_copied += 1
                    else:
                        self._log(_("    Failed to copy: {}").format(lib_name))
                        all_missing.add(lib_name)
                else:
                    self._log(_("    Not found in system: {}").format(lib_name))
                    all_missing.add(lib_name)

            if newly_copied == 0:
                self._log(_("  No new libraries could be copied — stopping"))
                break

            self._log(_("  Copied {} libraries this iteration").format(newly_copied))

        result = {
            "copied": all_copied,
            "missing": sorted(all_missing),
            "iterations": iteration,
        }

        self._log(
            _(
                "Dependency resolution complete: {} copied, {} still missing ({} iterations)"
            ).format(len(all_copied), len(all_missing), iteration)
        )

        return result


class PrePackagingValidator:
    """Validates an AppDir before creating the final AppImage."""

    def __init__(
        self,
        log_fn: Callable[[str], None],
        run_command_fn: Optional[Callable] = None,
    ):
        self._log = log_fn
        self._run_command = run_command_fn
        self._resolver = DependencyResolver(log_fn, run_command_fn)

    def _exec(self, cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Execute a command, optionally through the container."""
        if self._run_command:
            return self._run_command(cmd, timeout=timeout, capture_output=True)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def validate_libraries(self, appdir: Path) -> dict:
        """
        Check all ELF files in AppDir for unresolved library dependencies.

        Returns:
            dict with keys:
                'ok': bool — True if all dependencies resolved
                'missing': list of (elf_file, [missing_libs]) tuples
        """
        self._log(_("Validating library dependencies..."))

        elf_files = self._resolver._find_elf_files(appdir)
        problems: list[tuple[str, list[str]]] = []

        # Set LD_LIBRARY_PATH to include AppDir libs
        lib_paths = [
            str(appdir / "usr" / "lib"),
            str(appdir / "usr" / "lib-fallback"),
        ]
        env_override = {"LD_LIBRARY_PATH": ":".join(lib_paths)}

        for elf_path in elf_files:
            try:
                result = subprocess.run(
                    ["ldd", str(elf_path)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env={**os.environ, **env_override},
                )
                missing = []
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "not found" in line:
                            lib_name = line.strip().split()[0]
                            if not self._resolver._is_host_only(lib_name):
                                missing.append(lib_name)
                if missing:
                    rel_path = str(elf_path.relative_to(appdir))
                    problems.append((rel_path, missing))
            except Exception:
                pass

        if problems:
            self._log(_("Library validation FAILED:"))
            for elf_file, missing_libs in problems:
                self._log("  {} -> {}".format(elf_file, ", ".join(missing_libs)))
        else:
            self._log(_("Library validation passed — all dependencies resolved"))

        return {
            "ok": len(problems) == 0,
            "missing": problems,
        }

    def validate_python_imports(
        self, appdir: Path, main_module: Optional[str] = None
    ) -> dict:
        """
        Test Python imports in the AppDir context.

        Args:
            appdir: Path to the AppDir
            main_module: Optional main module to test import

        Returns:
            dict with 'ok' and 'error' keys
        """
        if not main_module:
            return {"ok": True, "error": None}

        self._log(_("Validating Python imports for module: {}").format(main_module))

        # Find Python in AppDir venv
        venv_python = None
        for py_path in (appdir / "usr" / "python" / "bin").glob("python3*"):
            if py_path.is_file() and not py_path.is_symlink():
                venv_python = str(py_path)
                break

        if not venv_python:
            # Try system python
            venv_python = "python3"

        # Build the import test
        app_dir_str = str(appdir / "usr" / "share")
        lib_dir = str(appdir / "usr" / "lib")
        test_script = (
            f"import sys; sys.path.insert(0, '{app_dir_str}'); import {main_module}"
        )

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = lib_dir
        env["GI_TYPELIB_PATH"] = str(appdir / "usr" / "lib" / "girepository-1.0")

        try:
            result = subprocess.run(
                [venv_python, "-c", test_script],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            if result.returncode == 0:
                self._log(_("Python import validation passed"))
                return {"ok": True, "error": None}
            else:
                error = (
                    result.stderr.strip().splitlines()[-1]
                    if result.stderr
                    else "Unknown error"
                )
                self._log(_("Python import validation FAILED: {}").format(error))
                return {"ok": False, "error": error}
        except Exception as e:
            self._log(_("Python import validation error: {}").format(e))
            return {"ok": False, "error": str(e)}

    def validate(self, appdir: Path, main_module: Optional[str] = None) -> dict:
        """
        Run all pre-packaging validations.

        Returns:
            dict with 'ok', 'library_result', and 'python_result' keys
        """
        self._log(_("Running pre-packaging validation..."))

        lib_result = self.validate_libraries(appdir)
        py_result = self.validate_python_imports(appdir, main_module)

        all_ok = lib_result["ok"] and py_result["ok"]

        if all_ok:
            self._log(_("Pre-packaging validation PASSED"))
        else:
            self._log(_("Pre-packaging validation FAILED — check warnings above"))

        return {
            "ok": all_ok,
            "library_result": lib_result,
            "python_result": py_result,
        }
