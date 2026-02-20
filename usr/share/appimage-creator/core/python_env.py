"""
Python environment setup for AppImage builds.

Handles virtualenv creation, stdlib copying, package installation,
and system PyGObject fallback.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from utils.system import make_executable
from utils.i18n import _


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
                requirements_source = project_root / "requirements.txt"
            else:
                executable_path = Path(self._b.app_info.executable)
                requirements_source = executable_path.parent / "requirements.txt"

            # Start with essential packages for GTK/Python applications
            packages_to_install = ["PyGObject", "PyCairo"]

            # If requirements.txt exists, add its content to the list
            if requirements_source.exists():
                with open(requirements_source, "r") as f:
                    user_packages = []
                    for line in f:
                        line = line.split("#", 1)[0].strip()
                        if line:
                            user_packages.append(line)
                    packages_to_install.extend(user_packages)
            else:
                self._b.log(
                    _("Warning: requirements.txt not found. Using default packages.")
                )

            # Remove duplicates and join
            requirements_content = "\n".join(list(set(packages_to_install)))

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

        self._b.log(_("Python shared libraries copied"))

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
                self._b.log(_("Successfully installed {}").format(package))

        self._b.log(_("Python packages installed"))

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
        self._b.log(_("Aggressive cleanup complete."))

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
