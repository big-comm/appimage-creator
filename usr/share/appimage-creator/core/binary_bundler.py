"""
External binary bundling for AppImage builds.

Handles detection and bundling of external binaries (e.g., mpv, vainfo)
using linuxdeploy, and scans project files to discover binary dependencies.
"""

import os
import shutil
import subprocess
from pathlib import Path

from core.build_config import SYSTEM_BINARIES
from utils.system import make_executable
from utils.i18n import _


class BinaryBundler:
    """Detects and bundles external binaries into an AppDir."""

    def __init__(self, builder):
        self._b = builder

    def bundle_external_binaries(self) -> None:
        """Bundle external binaries (ffmpeg, etc) using linuxdeploy."""
        self._b.log(_("Processing external binaries with linuxdeploy..."))

        if not self._b.download_linuxdeploy():
            self._b.log(_("Warning: linuxdeploy not available, skipping binary bundling"))
            return

        try:
            # Backup original wrapper BEFORE linuxdeploy runs
            original_wrapper = (
                self._b.appdir_path / "usr" / "bin" / self._b.app_info.executable_name
            )
            wrapper_backup = None

            if original_wrapper.exists() and not original_wrapper.is_symlink():
                wrapper_backup = (
                    original_wrapper.parent / f"{original_wrapper.name}.backup"
                )
                shutil.copy2(original_wrapper, wrapper_backup)
                self._b.log(
                    _("Backed up original wrapper: {}").format(original_wrapper.name)
                )

            # Backup custom AppRun BEFORE linuxdeploy runs
            custom_apprun = self._b.appdir_path / "AppRun"
            apprun_backup = None

            if custom_apprun.exists() and not custom_apprun.is_symlink():
                try:
                    with open(custom_apprun, "r") as f:
                        content = f.read()
                    if "Setup Python virtualenv if it exists" in content:
                        apprun_backup = self._b.appdir_path / "AppRun.backup"
                        shutil.copy2(custom_apprun, apprun_backup)
                        make_executable(apprun_backup)
                        self._b.log(_("Backed up custom AppRun"))
                except Exception:
                    pass

            desktop_files = list(
                (self._b.appdir_path / "usr/share/applications").glob("*.desktop")
            )
            if not desktop_files:
                self._b.log(_("Warning: No .desktop file found, skipping linuxdeploy"))
                return

            desktop_file_path = desktop_files[0]

            # Detect binaries to bundle
            detected_binaries = self.detect_binary_dependencies()

            cmd = [
                self._b.linuxdeploy_path,
                "--appdir",
                str(self._b.appdir_path),
                "--desktop-file",
                str(desktop_file_path),
            ]

            cmd.append("--create-desktop-file")

            # Add each detected binary
            for binary in detected_binaries:
                if binary in ["sh", "bash"]:
                    continue

                if SYSTEM_BINARIES.get(binary, {}).get("manage_libs_manually"):
                    self._b.log(
                        _(
                            "Skipping copy of '{}' executable, as it is treated as a library provider."
                        ).format(binary)
                    )
                    continue

                system_bin = shutil.which(binary)
                if system_bin:
                    dest = self._b.appdir_path / "usr" / "bin" / binary
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copy2(system_bin, dest)
                        make_executable(dest)

                    cmd.extend(["--executable", str(dest)])
                    self._b.log(_("Will bundle: {}").format(binary))

            # Skip if no binaries or plugins to bundle
            if len(cmd) <= 4:
                self._b.log(
                    _("No external binaries or plugins to process with linuxdeploy.")
                )
                return

            env = os.environ.copy()
            env["DISABLE_COPYRIGHT_FILES_DEPLOYMENT"] = "1"
            env["NO_STRIP"] = "1"

            self._b.log(_("Running linuxdeploy..."))
            self._b.update_progress(65, _("Bundling binary dependencies..."))

            if self._b.container_name:
                self._b.log(
                    _("Note: linuxdeploy runs locally but accesses container files")
                )

            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            for line in iter(process.stdout.readline, ""):
                log_line = line.strip()
                if log_line and not log_line.startswith("ERROR:"):
                    self._b.log(f"[linuxdeploy] {log_line}")

            process.stdout.close()
            return_code = process.wait(timeout=300)

            if return_code != 0:
                self._b.log(_("Warning: linuxdeploy had issues but continuing..."))
            else:
                self._b.log(_("External binaries bundled successfully"))

            # Restore custom AppRun FIRST
            if apprun_backup and apprun_backup.exists():
                if custom_apprun.exists():
                    custom_apprun.unlink()

                shutil.copy2(apprun_backup, custom_apprun)
                make_executable(custom_apprun)
                apprun_backup.unlink()
                self._b.log(_("Restored custom AppRun"))

            # Restore original wrapper
            if wrapper_backup and wrapper_backup.exists():
                if original_wrapper.exists():
                    original_wrapper.unlink()

                shutil.copy2(wrapper_backup, original_wrapper)
                make_executable(original_wrapper)
                wrapper_backup.unlink()
                self._b.log(
                    _("Restored original wrapper: {}").format(original_wrapper.name)
                )

            # Generate icon cache inside the AppDir for better integration
            self._b.log(_("Generating icon cache inside AppDir..."))
            hicolor_dir = self._b.appdir_path / "usr/share/icons/hicolor"
            if hicolor_dir.is_dir():
                try:
                    cache_cmd = ["gtk-update-icon-cache", "-f", "-t", str(hicolor_dir)]
                    result = self._b._run_command(cache_cmd, timeout=60)
                    if result.returncode == 0:
                        self._b.log(_("Successfully generated icon-theme.cache."))
                    else:
                        self._b.log(
                            _(
                                "Warning: Failed to generate icon-theme.cache. Icons may not appear in menus."
                            )
                        )
                        self._b.log(result.stderr or result.stdout)
                except Exception as cache_error:
                    self._b.log(
                        _("Warning: Could not run gtk-update-icon-cache: {}").format(
                            cache_error
                        )
                    )

        except Exception as e:
            self._b.log(_("Warning: Binary bundling failed: {}").format(e))

    def detect_binary_dependencies(self) -> list[str]:
        """Detect required system binaries by scanning project files using SYSTEM_BINARIES."""
        detected_binaries = set()

        # Always include common shell utilities
        detected_binaries.update(["sh", "bash"])

        # Determine search path for source files
        source_path = None
        structure_analysis = self._b.app_info.structure_analysis or {}
        project_root = structure_analysis.get("project_root")
        if project_root and Path(project_root).exists():
            source_path = Path(project_root)
        elif self._b.app_info.executable:
            source_path = Path(self._b.app_info.executable).parent

        if not source_path:
            self._b.log(
                _("Warning: Could not determine source path for binary detection.")
            )
            return list(detected_binaries)

        self._b.log(_("Scanning for binary dependencies in: {}").format(source_path))

        # Scan all relevant files (.py, .sh, scripts without extension)
        files_to_scan = list(source_path.rglob("*.py")) + list(
            source_path.rglob("*.sh")
        )

        for item in source_path.rglob("*"):
            if item.is_file() and not item.suffix and os.access(item, os.X_OK):
                files_to_scan.append(item)

        for file_path in set(files_to_scan):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                for key, info in SYSTEM_BINARIES.items():
                    keyword = info["detection_keyword"]
                    if keyword in content:
                        binary_name = info["binary_name"]
                        if binary_name not in detected_binaries:
                            self._b.log(
                                _("  Detected dependency on binary: {}").format(
                                    binary_name
                                )
                            )
                            detected_binaries.add(binary_name)
            except Exception:
                continue

        return list(detected_binaries)
