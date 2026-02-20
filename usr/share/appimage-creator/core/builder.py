"""
Core AppImage builder - orchestrates the build process
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from validators.validators import (
    validate_app_name,
    validate_version,
    validate_executable,
)
from core.structure_analyzer import detect_application_structure
from templates.app_templates import get_app_type_from_file
from generators.icons import process_icon, generate_default_icon
from generators.files import create_apprun_file, generate_desktop_file
from utils.file_ops import copy_files_recursively, download_file, verify_download_sha256
from utils.system import get_system_info, find_executable_in_path, make_executable
from core.dependency_resolver import DependencyResolver, PrePackagingValidator
from core.app_info import AppInfo
from utils.i18n import _


class AppImageBuilder:
    """Main class for building AppImages"""

    def __init__(self):
        self.app_info = {}
        self.build_dir = None
        self.appdir_path = None
        self.appimagetool_path = None
        self.linuxdeploy_path = None
        self.progress_callback = None
        self.log_callback = None
        self.cancel_requested = False
        self.validation_result: dict | None = None
        self._build_thread = None
        self.build_environment = None
        self.python_version = None
        self.container_name = None

    def is_local_build(self) -> bool:
        """Check if building locally (not in container)"""
        return self.build_environment is None or self.container_name is None

    def get_compatibility_warning(self) -> Optional[dict]:
        """Get compatibility warning message for local builds"""
        if not self.is_local_build():
            return None

        app_type = self.app_info.app_type or "binary"
        if app_type not in ["python", "python_wrapper", "gtk", "qt"]:
            return None

        import platform

        host_distro = platform.freedesktop_os_release().get("NAME", "Unknown")

        return {
            "title": _("⚠️ Local Build Warning"),
            "message": _(
                "You are building locally on {distro}.\n\n"
                "AppImages built on your system may NOT work on other distributions due to:\n"
                "• Different Python versions\n"
                "• Different library versions\n"
                "• Distribution-specific dependencies\n\n"
                "For MAXIMUM COMPATIBILITY, use:\n"
                "Build Environment → Ubuntu 20.04 or 22.04\n\n"
                "Continue anyway?"
            ).format(distro=host_distro),
            "severity": "warning",
        }

    def set_app_info(self, app_info: AppInfo) -> None:
        """Set application information with structure analysis"""

        app_info = app_info.copy()

        # Validate required fields
        app_info.name = validate_app_name(app_info.name)
        app_info.version = validate_version(app_info.version)
        app_info.executable = validate_executable(app_info.executable)

        # Analyze structure
        structure_analysis = detect_application_structure(app_info.executable)
        app_info.structure_analysis = structure_analysis

        # Auto-detect app type
        if not app_info.app_type:
            app_info.app_type = get_app_type_from_file(
                app_info.executable, structure_analysis
            )

        # Define the base name - use the actual executable filename
        if not app_info.executable_name:
            executable_path = Path(app_info.executable)
            app_info.executable_name = executable_path.name

        # Store wrapper analysis
        if structure_analysis.get("wrapper_analysis"):
            app_info.wrapper_analysis = structure_analysis["wrapper_analysis"]

        # Merge suggested directories (already has default from dataclass)

        # Set defaults for empty fields
        if not app_info.description:
            app_info.description = f"{app_info.name} application"

        self.app_info = app_info

        # Set build environment
        self.build_environment = app_info.build_environment
        if self.build_environment:
            self.container_name = f"appimage-creator-{self.build_environment}"
            self.log(_("Will build in container: {}").format(self.container_name))
        else:
            self.container_name = None
            self.log(_("Will build in local system"))

    def set_progress_callback(self, callback: Callable[[int, str], None]) -> None:
        """Set progress callback function"""
        self.progress_callback = callback

    def set_log_callback(self, callback: Callable[[str], None]) -> None:
        """Set log callback function"""
        self.log_callback = callback

    def _run_command(self, cmd, env=None, cwd=None, timeout=None, capture_output=True):
        """Run command, optionally inside container."""
        if self.container_name:
            # Run inside container using distrobox-enter
            self.log(_("Running in container: {}").format(" ".join(cmd)))

            # Build the full command to run inside container
            cmd_str = " ".join(shlex.quote(str(arg)) for arg in cmd)

            # If there's a working directory, cd into it first
            if cwd:
                cmd_str = f"cd {shlex.quote(str(cwd))} && {cmd_str}"

            # Build container command
            container_cmd = [
                "distrobox-enter",
                self.container_name,
                "--",
                "bash",
                "-c",
                cmd_str,
            ]

            # Merge environment variables
            merged_env = os.environ.copy()
            if env:
                merged_env.update(env)

            return subprocess.run(
                container_cmd,
                env=merged_env,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=None,
            )
        else:
            # Run locally
            return subprocess.run(
                cmd,
                env=env,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

    def log(self, message: str) -> None:
        """Log a message"""
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass
        print(message)

    def update_progress(self, percentage: int, message: str) -> None:
        """Update progress"""
        if self.progress_callback:
            try:
                self.progress_callback(percentage, message)
            except Exception:
                pass

    def cancel_build(self) -> None:
        """Cancel the current build process"""
        self.cancel_requested = True
        self.log(_("Build cancellation requested"))

    def create_build_directory(self) -> Path:
        """Create temporary build directory"""
        try:
            self.build_dir = Path(tempfile.mkdtemp(prefix="appimage_build_"))
            self.appdir_path = (
                self.build_dir / f"{self.app_info.executable_name}.AppDir"
            )
            self.log(_("Created build directory: {}").format(self.build_dir))
            return self.build_dir
        except Exception as e:
            raise RuntimeError(_("Failed to create build directory: {}").format(e))

    def create_appdir_structure(self) -> None:
        """Create AppDir directory structure"""
        self.log(_("Creating AppDir structure..."))

        try:
            if self.appdir_path.exists():
                shutil.rmtree(self.appdir_path)

            # A minimal structure is enough, the copy will create the rest
            self.appdir_path.mkdir(parents=True, exist_ok=True)

            self.update_progress(10, _("AppDir structure created"))
        except Exception as e:
            raise RuntimeError(_("Failed to create AppDir structure: {}").format(e))

    def copy_application_files(self) -> None:
        """Copy application files to AppDir"""
        self.log(_("Copying application files..."))

        try:
            structure_analysis = self.app_info.structure_analysis or {}
            project_root = structure_analysis.get("project_root")

            if project_root and os.path.exists(project_root):
                self.log(_("Copying structured project from: {}").format(project_root))
                exclude_patterns = [
                    # Version control and cache
                    ".git",
                    ".github",
                    ".gitignore",
                    "__pycache__",
                    "*.pyc",
                    ".DS_Store",
                    # Temporary and translation files
                    "*.tmp",
                    "*.po",
                    "*.pot",
                    # Documentation and project metadata files
                    "README.md",
                    "LICENSE",
                    "requirements.txt",  # The builder uses it, but it doesn't need to be in the final AppImage
                    # Specific build/package directories
                    "pkgbuild",
                ]

                copy_files_recursively(
                    project_root, self.appdir_path, exclude_patterns=exclude_patterns
                )
            else:
                # Fallback for simple applications without a clear root
                self.log(_("Project root not found, copying as simple application."))
                executable_path = Path(self.app_info.executable)
                app_share_dir = (
                    self.appdir_path / "usr" / "share" / self.app_info.executable_name
                )
                app_share_dir.mkdir(parents=True, exist_ok=True)
                if executable_path.is_file():
                    shutil.copy2(executable_path, app_share_dir)
                else:
                    copy_files_recursively(executable_path, app_share_dir)

            # Copy any extra user-defined directories
            self._copy_additional_directories()

            # --- NEW: Copy the integration helper script ---
            self.log(_("Copying desktop integration helper..."))
            helper_script_src = Path(__file__).parent.parent / "integration_helper.py"
            if helper_script_src.exists():
                helper_script_dest_dir = self.appdir_path / "usr" / "bin"
                helper_script_dest_dir.mkdir(parents=True, exist_ok=True)
                helper_script_dest = helper_script_dest_dir / "integration_helper.py"
                shutil.copy2(helper_script_src, helper_script_dest)
                make_executable(helper_script_dest)  # ← ADICIONE ESTA LINHA
                self.log(_("Integration helper copied successfully."))
            else:
                self.log(_("Warning: integration_helper.py not found, skipping."))
            # --- END OF NEW SECTION ---

            self.update_progress(25, _("Application files copied"))
        except Exception as e:
            raise RuntimeError(_("Failed to copy application files: {}").format(e))

    def _copy_additional_directories(self):
        """Copy user-specified additional directories"""
        additional_dirs = self.app_info.additional_directories

        for dir_path in additional_dirs:
            try:
                if not os.path.exists(dir_path):
                    self.log(_("Warning: Directory not found: {}").format(dir_path))
                    continue

                src_path = Path(dir_path)
                dest_path = self.appdir_path / "usr" / "share" / src_path.name

                self.log(
                    _("Copying additional directory: {} -> {}").format(
                        src_path, dest_path
                    )
                )
                copy_files_recursively(src_path, dest_path)
            except Exception as e:
                self.log(
                    _("Warning: Failed to copy directory {}: {}").format(dir_path, e)
                )

    def process_application_icon(self) -> None:
        """Process and copy icon with consistent naming."""
        self.log(_("Processing icon..."))

        try:
            icon_path = self.app_info.icon
            canonical_basename = self.app_info.canonical_basename
            if not canonical_basename:
                canonical_basename = (
                    (self.app_info.name or "app").lower().replace(" ", "-")
                )

            if not icon_path and self.app_info.structure_analysis:
                detected_icons = self.app_info.structure_analysis["detected_files"].get(
                    "icons", []
                )
                if detected_icons:
                    svg_icons = [i for i in detected_icons if i.endswith(".svg")]

                    # Prioritize icons that match the canonical basename
                    matching_icons = [
                        i
                        for i in svg_icons
                        if canonical_basename in os.path.basename(i).lower()
                    ]
                    if matching_icons:
                        icon_path = matching_icons[0]
                    elif svg_icons:
                        icon_path = svg_icons[0]
                    else:
                        icon_path = detected_icons[0]

                    self.log(_("Using detected icon: {}").format(icon_path))

            # Define the destination for the icon
            icon_dest_dir = self.appdir_path / "usr/share/icons/hicolor/scalable/apps"
            icon_dest_dir.mkdir(parents=True, exist_ok=True)

            if not icon_path or not os.path.exists(icon_path):
                self.log(_("No icon provided or found, generating a default one."))
                generate_default_icon(icon_dest_dir, canonical_basename)
            else:
                # Process the existing icon and save it with the canonical name
                process_icon(icon_path, icon_dest_dir, canonical_basename)

            self.update_progress(35, _("Icon processed"))

        except Exception as e:
            self.log(_("Warning: Icon processing failed: {}").format(e))

    def create_launcher_and_desktop_files(self) -> None:
        """Create launcher and desktop files preserving original .desktop filename."""
        self.log(_("Creating launcher and desktop files..."))

        try:
            appdir_desktop_files_dir = self.appdir_path / "usr/share/applications"
            appdir_desktop_files = list(appdir_desktop_files_dir.glob("*.desktop"))

            if not appdir_desktop_files:
                self.log(_("No desktop file found in AppDir, generating a new one."))
                # Generate a new desktop file with a canonical name
                canonical_basename = (
                    (self.app_info.name or "app").lower().replace(" ", "-")
                )
                desktop_content = generate_desktop_file(self.app_info)
                new_desktop_path = (
                    appdir_desktop_files_dir / f"{canonical_basename}.desktop"
                )
                with open(new_desktop_path, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
                main_desktop_file_path = new_desktop_path
            else:
                # Use the existing desktop file, preserving its original name
                source_desktop_file = appdir_desktop_files[0]
                self.log(
                    _("Found desktop file from source project: {}").format(
                        source_desktop_file.name
                    )
                )

                # Keep the original filename - do NOT rename it
                main_desktop_file_path = source_desktop_file
                self.log(
                    f"Using desktop file with original name: {main_desktop_file_path.name}"
                )

            # Create symlink to the desktop file in AppDir root (using original name)
            root_desktop_path = self.appdir_path / main_desktop_file_path.name
            relative_desktop = os.path.relpath(main_desktop_file_path, self.appdir_path)
            if root_desktop_path.exists():
                root_desktop_path.unlink()
            root_desktop_path.symlink_to(relative_desktop)
            self.log(
                _("Created desktop symlink in AppDir root: {}").format(
                    main_desktop_file_path.name
                )
            )

            self.log(_("Creating custom AppRun script..."))

            app_info_for_apprun = self.app_info.copy()
            app_type = self.app_info.app_type

            # Add the dynamically detected python_version to the app_info copy
            if hasattr(self, "python_version") and self.python_version:
                app_info_for_apprun.python_version = self.python_version

            # Determine the components of the command that AppRun should execute
            if app_type in ["python", "python_wrapper", "gtk", "qt"]:
                structure = self.app_info.structure_analysis or {}
                wrapper_analysis = structure.get("wrapper_analysis", {})

                target_script_abs = wrapper_analysis.get("target_executable")
                project_root_abs = structure.get("project_root")

                if not target_script_abs or not project_root_abs:
                    raise RuntimeError(
                        "Could not determine target Python script from structure analysis."
                    )

                # Calculate the script's path relative to the project root
                relative_script_path = os.path.relpath(
                    target_script_abs, project_root_abs
                )

                app_info_for_apprun.apprun_executable = "usr/python/venv/bin/python3"
                app_info_for_apprun.apprun_argument = relative_script_path
                self.log(
                    _("AppRun will execute Python on: {}").format(relative_script_path)
                )

            else:
                # For binary apps
                sa = self.app_info.structure_analysis or {}
                project_root = sa.get("project_root")
                if project_root:
                    rel_path = os.path.relpath(self.app_info.executable, project_root)
                    app_info_for_apprun.apprun_executable = rel_path
                else:
                    app_info_for_apprun.apprun_executable = (
                        f"usr/bin/{self.app_info.executable_name}"
                    )

                app_info_for_apprun.apprun_argument = None
                self.log(
                    _("AppRun will execute: {}").format(
                        app_info_for_apprun.apprun_executable
                    )
                )

            # Create the AppRun file
            create_apprun_file(self.appdir_path, app_info_for_apprun)

            self.update_progress(50, _("Launcher and desktop files created"))
        except Exception as e:
            raise RuntimeError(_("Failed to create launcher files: {}").format(e))

    def copy_integration_helpers(self) -> None:
        """Copy integration helper scripts to usr/bin/ inside AppImage"""
        self.log(_("Copying integration helper scripts..."))

        try:
            # Destination directory inside AppImage
            bin_dir = self.appdir_path / "usr" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)

            # Source directory (where this builder script is located)
            # integration_helper.py should be in the project root
            project_root = Path(__file__).parent.parent

            # Copy integration_helper.py
            integration_helper_source = project_root / "integration_helper.py"
            if integration_helper_source.exists():
                integration_helper_dest = bin_dir / "integration_helper.py"
                shutil.copy2(integration_helper_source, integration_helper_dest)
                integration_helper_dest.chmod(0o755)
                self.log(_("✓ Copied integration_helper.py"))
            else:
                self.log(
                    _("Warning: integration_helper.py not found at {}").format(
                        integration_helper_source
                    )
                )

            # Copy appimage-cleanup.py
            cleanup_script_source = project_root / "appimage-cleanup.py"
            if cleanup_script_source.exists():
                cleanup_script_dest = bin_dir / "appimage-cleanup.py"
                shutil.copy2(cleanup_script_source, cleanup_script_dest)
                cleanup_script_dest.chmod(0o755)
                self.log(_("✓ Copied appimage-cleanup.py"))
            else:
                self.log(
                    _("Warning: appimage-cleanup.py not found at {}").format(
                        cleanup_script_source
                    )
                )

            # Copy updater module (for auto-update feature)
            updater_dir_source = project_root / "updater"
            if updater_dir_source.exists() and updater_dir_source.is_dir():
                # Create usr/bin/updater directory (will be copied to ~/.local/bin/updater by integration_helper)
                updater_dest_dir = bin_dir / "updater"
                updater_dest_dir.mkdir(parents=True, exist_ok=True)

                # Copy all Python files from updater module
                for py_file in updater_dir_source.glob("*.py"):
                    dest_file = updater_dest_dir / py_file.name
                    shutil.copy2(py_file, dest_file)

                # Copy updater translations
                locale_source = updater_dir_source / "locale"
                if locale_source.exists():
                    locale_dest = self.appdir_path / "usr" / "share" / "locale"
                    locale_dest.mkdir(parents=True, exist_ok=True)

                    # Copy only .mo files for each language
                    for lang_dir in locale_source.glob("*/LC_MESSAGES"):
                        lang_code = lang_dir.parent.name
                        dest_lang_dir = locale_dest / lang_code / "LC_MESSAGES"
                        dest_lang_dir.mkdir(parents=True, exist_ok=True)

                        for mo_file in lang_dir.glob("*.mo"):
                            dest_mo = dest_lang_dir / mo_file.name
                            shutil.copy2(mo_file, dest_mo)

                self.log(_("✓ Copied updater module"))

                # Copy updater icon and desktop file
                try:
                    # Try multiple possible locations for the updater files
                    # This handles different installation scenarios (dev, system, AppImage)

                    possible_roots = [
                        # Project root (usr/share/appimage-creator)
                        project_root,
                        # Development (running from git repo root)
                        project_root.parent.parent,
                        # System installation
                        Path("/usr"),
                        # Running from AppImage (APPDIR)
                        Path(os.environ.get("APPDIR", "/")),
                        # Current working directory as fallback
                        Path.cwd(),
                    ]

                    updater_icon_copied = False
                    updater_desktop_copied = False

                    for root in possible_roots:
                        # Try to find and copy updater icon
                        if not updater_icon_copied:
                            updater_icon_source = (
                                root
                                / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg"
                            )
                            if updater_icon_source.exists():
                                icons_dest_dir = (
                                    self.appdir_path
                                    / "usr"
                                    / "share"
                                    / "icons"
                                    / "hicolor"
                                    / "scalable"
                                    / "apps"
                                )
                                icons_dest_dir.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(
                                    updater_icon_source,
                                    icons_dest_dir / "appimage-update.svg",
                                )
                                self.log(
                                    _("✓ Copied updater icon from {}").format(
                                        updater_icon_source
                                    )
                                )
                                updater_icon_copied = True

                        # Try to find and copy updater .desktop
                        if not updater_desktop_copied:
                            updater_desktop_source = (
                                root
                                / "usr/share/applications/org.bigcommunity.appimage.updater.desktop"
                            )
                            if updater_desktop_source.exists():
                                desktop_dest_dir = (
                                    self.appdir_path / "usr" / "share" / "applications"
                                )
                                desktop_dest_dir.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(
                                    updater_desktop_source,
                                    desktop_dest_dir
                                    / "org.bigcommunity.appimage.updater.desktop",
                                )
                                self.log(
                                    _("✓ Copied updater .desktop from {}").format(
                                        updater_desktop_source
                                    )
                                )
                                updater_desktop_copied = True

                        # If both found, we're done
                        if updater_icon_copied and updater_desktop_copied:
                            break

                    # Warn if files were not found
                    if not updater_icon_copied:
                        self.log(
                            _(
                                "Warning: Updater icon (appimage-update.svg) not found in any location"
                            )
                        )
                    if not updater_desktop_copied:
                        self.log(
                            _(
                                "Warning: Updater .desktop (org.bigcommunity.appimage.updater.desktop) not found in any location"
                            )
                        )

                    # Create symlink for updater icon in AppDir root (required by appimagetool)
                    if updater_icon_copied:
                        # Define icons_dest_dir explicitly to avoid scope issues
                        icons_dest_dir = (
                            self.appdir_path
                            / "usr"
                            / "share"
                            / "icons"
                            / "hicolor"
                            / "scalable"
                            / "apps"
                        )
                        updater_icon_in_appdir = icons_dest_dir / "appimage-update.svg"

                        self.log(
                            f"[DEBUG] Checking for updater icon at: {updater_icon_in_appdir}"
                        )
                        self.log(
                            f"[DEBUG] Icon exists: {updater_icon_in_appdir.exists()}"
                        )

                        if updater_icon_in_appdir.exists():
                            relative_updater_icon = os.path.relpath(
                                updater_icon_in_appdir, self.appdir_path
                            )
                            updater_icon_symlink = (
                                self.appdir_path / "appimage-update.svg"
                            )

                            self.log(
                                f"[DEBUG] Creating symlink: {updater_icon_symlink} -> {relative_updater_icon}"
                            )

                            # Remove old symlink if exists
                            if (
                                updater_icon_symlink.exists()
                                or updater_icon_symlink.is_symlink()
                            ):
                                updater_icon_symlink.unlink()
                                self.log("[DEBUG] Removed old symlink")

                            updater_icon_symlink.symlink_to(relative_updater_icon)
                            self.log(_("✓ Created updater icon symlink in AppDir root"))
                        else:
                            self.log(
                                f"[DEBUG] Updater icon not found at expected location: {updater_icon_in_appdir}"
                            )

                except Exception as e:
                    self.log(
                        _("Warning: Failed to copy updater icon/desktop: {}").format(e)
                    )

            else:
                self.log(
                    _(
                        "Info: Updater module not found (auto-update will not be available)"
                    )
                )

        except Exception as e:
            self.log(_("Warning: Failed to copy integration helpers: {}").format(e))

    def copy_dependencies(self) -> None:
        """Copy dependencies: Python virtualenv + external binaries"""
        if not self.app_info.include_dependencies:
            self.log(_("Skipping dependency inclusion."))
            self.update_progress(70, _("Dependencies skipped"))
            return

        # Python dependencies (if Python app)
        app_type = self.app_info.app_type or "binary"
        if app_type in ["python", "python_wrapper", "gtk", "qt"]:
            self._setup_python_environment()

        # External binaries with linuxdeploy
        self._bundle_external_binaries()

        # Create icon symlinks matching desktop file name
        self._create_icon_symlinks()

        # System libraries (fallback)
        self._copy_system_libraries()

        # GObject Introspection typelibs (for PyGObject apps)
        self._copy_typelibs()

        # Copy only essential GStreamer plugins
        self._copy_gstreamer_plugins()

        # Copy MPV configuration if needed
        self._copy_mpv_config()

        # Icon theme handling based on user configuration
        include_icon_theme = self.app_info.include_icon_theme
        icon_theme_choice = self.app_info.icon_theme_choice

        if include_icon_theme:
            # Check if it's a GTK application
            is_gtk_app = False
            if app_type in ["python", "python_wrapper", "gtk", "qt"]:
                is_gtk_app = self._detect_gi_usage(self.app_info)

            # If GTK app or user explicitly enabled, copy the selected theme
            if is_gtk_app:
                if icon_theme_choice == "papirus":
                    self.log(_("Installing Papirus icon theme for GTK application"))
                    self._copy_papirus_symbolic_icons()
                elif icon_theme_choice == "adwaita":
                    self.log(_("Installing Adwaita icon theme for GTK application"))
                    self._copy_symbolic_icons()
            else:
                # Not a GTK app, but user enabled icon theme
                selected_deps = self.app_info.selected_dependencies
                if "gtk4" in selected_deps or "adwaita" in selected_deps:
                    if icon_theme_choice == "papirus":
                        self.log(_("Installing Papirus icon theme"))
                        self._copy_papirus_symbolic_icons()
                    elif icon_theme_choice == "adwaita":
                        self.log(_("Installing Adwaita icon theme"))
                        self._copy_symbolic_icons()
        else:
            self.log(_("Icon theme inclusion disabled by user"))

        # Recursive ldd-based dependency resolution
        self._resolve_missing_libraries()

        self.log(_("Dependencies installed successfully."))
        self.update_progress(70, _("Dependencies processed"))

    def _resolve_missing_libraries(self):
        """Use recursive ldd scanning to find and copy missing shared libraries."""
        self.log(_("Running recursive library dependency resolution..."))
        self.update_progress(68, _("Resolving library dependencies..."))

        resolver = DependencyResolver(
            log_fn=self.log,
            run_command_fn=self._run_command if self.container_name else None,
        )
        result = resolver.resolve(self.appdir_path, max_iterations=3)

        if result["missing"]:
            self.log(
                _("Warning: {} libraries could not be resolved: {}").format(
                    len(result["missing"]), ", ".join(result["missing"])
                )
            )

    def _setup_python_environment(self):
        """Setup Python virtualenv for Python applications."""
        from core.python_env import PythonEnvironmentSetup

        PythonEnvironmentSetup(self).setup()

    def _detect_gui_dependencies(self, app_info: AppInfo):
        """
        Detect GUI framework dependencies by analyzing Python source code.
        Returns dict with framework info: {'gtk3': True, 'gtk4': True, etc}
        """
        self.log(_("Detecting GUI framework dependencies..."))
        dependencies: dict[str, bool] = {}

        # Find Python files in the original project source, not the AppDir
        python_files = []
        structure_analysis = app_info.structure_analysis or {}
        project_root = structure_analysis.get("project_root")

        if project_root and Path(project_root).exists():
            self.log(_("Analyzing Python files in: {}").format(project_root))
            python_files = list(Path(project_root).rglob("*.py"))
        else:
            # Fallback if project root is not available
            executable_path = app_info.executable
            if executable_path:
                executable_dir = Path(executable_path).parent
                self.log(
                    _("Analyzing Python files in executable's directory: {}").format(
                        executable_dir
                    )
                )
                python_files = list(executable_dir.rglob("*.py"))

        if not python_files:
            self.log(_("No Python files found for dependency detection"))
            return dependencies

        self.log(_("Analyzing {} Python files...").format(len(python_files)))

        # Patterns to detect GUI frameworks
        patterns = {
            "gtk3": [
                r"gi\.require_version\(['\"]Gtk['\"],\s*['\"]3\.0['\"]",
            ],
            "gtk4": [
                r"gi\.require_version\(['\"]Gtk['\"],\s*['\"]4\.0['\"]",
            ],
            "adwaita": [
                r"gi\.require_version\(['\"]Adw['\"],\s*['\"]1['\"]",
            ],
            "vte": [
                r"gi\.require_version\(['\"]Vte['\"],\s*['\"]3\.91['\"]",
                r"gi\.require_version\(['\"]Vte['\"],\s*['\"]2\.91['\"]",
            ],
            "libsecret": [
                r"gi\.require_version\(['\"]Secret['\"],\s*['\"]1['\"]",
                r"from gi\.repository import Secret",
                r"import.*Secret",
            ],
            "qt5": [r"from PyQt5", r"import PyQt5"],
            "qt6": [r"from PyQt6", r"import PyQt6"],
            "gstreamer-gtk": [
                # Detects modern GStreamer GTK4 integration via gtk4paintablesink
                # as well as the older GstGtk import.
                r"gtk4paintablesink",
                r"from gi\.repository import GstGtk",
                r"gi\.require_version\(['\"]GstGtk['\"],",
            ],
            "mpv": [r"import\s+mpv", r"from\s+mpv"],
        }

        for py_file in python_files[:50]:
            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    for framework, pattern_list in patterns.items():
                        for pattern in pattern_list:
                            if re.search(pattern, content):
                                dependencies[framework] = True
                                self.log(_("  Detected: {}").format(framework.upper()))
                                break
            except Exception:
                continue

        return dependencies

    def _detect_gi_usage(self, app_info: AppInfo):
        """
        Detect if the application uses PyGObject (gi module).
        Returns True if gi is imported anywhere in the code.
        """
        self.log(_("Checking for PyGObject usage..."))

        python_files = []
        structure_analysis = app_info.structure_analysis or {}
        project_root = structure_analysis.get("project_root")

        if project_root and Path(project_root).exists():
            python_files = list(Path(project_root).rglob("*.py"))
        else:
            # Fallback if project root is not available
            executable_path = app_info.executable
            if executable_path:
                executable_dir = Path(executable_path).parent
                python_files = list(executable_dir.rglob("*.py"))

        if not python_files:
            return False

        import re

        gi_patterns = [
            r"\bimport\s+gi\b",
            r"\bfrom\s+gi\b",
            r"\bfrom\s+gi\.repository\b",
        ]

        for py_file in python_files[:50]:
            try:
                with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    for pattern in gi_patterns:
                        if re.search(pattern, content):
                            self.log(_("  Detected PyGObject usage"))
                            return True
            except Exception:
                continue

        return False

    def _ensure_native_dependencies(self, dependencies):
        """
        Install native GUI libraries in container if missing.
        """
        if not dependencies:
            return

        self.log(_("Ensuring native GUI dependencies..."))

        # Detect package manager based on build environment
        package_manager = "apt"  # default
        if self.build_environment:
            if any(
                distro in self.build_environment.lower()
                for distro in ["fedora", "alma", "rhel", "centos"]
            ):
                package_manager = "dnf"

        # Package mappings per distro family
        debian_packages = {
            "gtk3": [
                "libgtk-3-0",
                "gir1.2-gtk-3.0",
                "libgirepository-1.0-1",
                "libgirepository-2.0-0",
                "python3-gi",
                "python3-gi-cairo",
            ],
            "gtk4": [
                "libgtk-4-1",
                "gir1.2-gtk-4.0",
                "libgirepository-1.0-1",
                "libgirepository-2.0-0",
                "python3-gi",
                "python3-gi-cairo",
            ],
            "adwaita": ["libadwaita-1-0", "gir1.2-adw-1"],
            "vte": [
                "libvte-2.91-0",
                "gir1.2-vte-2.91",
                "libvte-2.91-gtk4-0",
                "gir1.2-vte-3.91",
                "libvte-2.91-gtk4-dev",
            ],
            "libsecret": ["libsecret-1-0", "gir1.2-secret-1"],
            "qt5": ["libqt5core5a", "libqt5gui5", "libqt5widgets5"],
            "qt6": ["libqt6core6", "libqt6gui6", "libqt6widgets6"],
        }

        rpm_packages = {
            "gtk3": [
                "gtk3",
                "gtk3-devel",
                "gobject-introspection",
                "python3-gobject",
                "python3-cairo",
            ],
            "gtk4": [
                "gtk4",
                "gtk4-devel",
                "gobject-introspection",
                "python3-gobject",
                "python3-cairo",
            ],
            "adwaita": ["libadwaita", "libadwaita-devel"],
            "vte": ["vte291", "vte291-devel"],
            "libsecret": ["libsecret", "libsecret-devel"],
            "qt5": ["qt5-qtbase", "qt5-qtbase-devel"],
            "qt6": ["qt6-qtbase", "qt6-qtbase-devel"],
        }

        package_map = debian_packages if package_manager == "apt" else rpm_packages

        # Add specific package maps for non-GUI dependencies like media libraries
        debian_media_packages = {
            "mpv": ["libmpv-dev"],
        }
        rpm_media_packages = {
            "mpv": ["mpv-libs-devel"],
        }
        media_package_map = (
            debian_media_packages if package_manager == "apt" else rpm_media_packages
        )

        packages_needed = []
        for fw in dependencies.keys():
            if fw in package_map:
                packages_needed.extend(package_map[fw])
            # Check for media dependencies as well
            if fw in media_package_map:
                packages_needed.extend(media_package_map[fw])

        packages_needed = list(set(packages_needed))
        self.log(_("Required packages: {}").format(", ".join(packages_needed)))

        # Check which packages are actually missing from the container
        packages_to_install = []
        self.log(_("Checking for missing packages in the container..."))
        for pkg in packages_needed:
            # Use dpkg-query to check package status. It returns non-zero if not installed.
            check_cmd = ["dpkg-query", "-W", "-f='${Status}'", pkg]
            result = self._run_command(check_cmd, capture_output=True)
            # A successful query contains 'install ok installed'
            if result.returncode != 0 or "install ok installed" not in result.stdout:
                packages_to_install.append(pkg)
                self.log(f"  -> Package '{pkg}' is missing.")

        # If there's nothing to install, we can stop here.
        if not packages_to_install:
            self.log(_("All required native dependencies are already installed."))
            return

        self.log(_("Packages to install: {}").format(", ".join(packages_to_install)))

        # Check for GTK4 on Ubuntu 20.04
        if "gtk4" in dependencies:
            if (
                self.build_environment
                and "ubuntu-20.04" in self.build_environment.lower()
            ):
                raise RuntimeError(
                    _(
                        "GTK4 application detected, but Ubuntu 20.04 does not have GTK4 in repositories.\n\n"
                        "Solution: Use Ubuntu 22.04 or 24.04 container instead.\n"
                        "Go to: Build Environment → Select a newer Ubuntu version"
                    )
                )

            self.log(_("Note: GTK4 detected - using modern container recommended"))

        # Update repos first
        self.log(_("Updating package lists..."))
        if package_manager == "apt":
            self._run_command(["sudo", "apt-get", "update"], timeout=120)
        else:
            self._run_command(["sudo", "dnf", "check-update"], timeout=120)

        # Install packages
        self.log(_("Installing GUI libraries..."))
        if package_manager == "apt":
            install_cmd = [
                "sudo",
                "apt-get",
                "install",
                "-y",
                "--no-install-recommends",
            ] + packages_to_install
        else:
            install_cmd = ["sudo", "dnf", "install", "-y"] + packages_to_install

        self.log(_("Running install command: {}").format(" ".join(install_cmd)))
        result = self._run_command(install_cmd, timeout=300)

        if result.returncode == 0:
            self.log(_("Successfully installed GUI dependencies in container."))
        else:
            # If the main install command fails, raise a clear error.
            error_message = (
                result.stderr
                or result.stdout
                or _("Unknown error from package manager.")
            )
            self.log(_("Error installing dependencies in container:"))
            self.log(error_message)
            raise RuntimeError(
                _(
                    "Failed to install required build dependencies in the container: {pkgs}\n\n"
                    "Error details:\n{err}"
                ).format(pkgs=", ".join(packages_needed), err=error_message)
            )

    def _create_icon_symlinks(self):
        """Create icon symlinks matching desktop file name."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).create_icon_symlinks()

    def _copy_system_libraries(self):
        """Copy system libraries to AppDir."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_system_libraries()

    def _copy_typelibs(self):
        """Copy GObject Introspection typelibs."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_typelibs()

    def _copy_gstreamer_plugins(self):
        """Copy GStreamer plugins."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_gstreamer_plugins()

    def _copy_mpv_config(self):
        """Copy MPV configuration."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_mpv_config()

    def _copy_symbolic_icons(self):
        """Copy Adwaita symbolic icons."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_symbolic_icons()

    def _copy_papirus_symbolic_icons(self):
        """Copy Papirus symbolic icons."""
        from core.library_bundler import LibraryBundler

        LibraryBundler(self).copy_papirus_symbolic_icons()

    def _bundle_external_binaries(self):
        """Bundle external binaries using linuxdeploy."""
        from core.binary_bundler import BinaryBundler

        BinaryBundler(self).bundle_external_binaries()

    def _detect_binary_dependencies(self):
        """Detect required system binaries by scanning project files."""
        from core.binary_bundler import BinaryBundler

        return BinaryBundler(self).detect_binary_dependencies()

    def download_appimagetool(self) -> bool:
        """Download or find appimagetool"""
        self.log(_("Setting up appimagetool..."))

        try:
            # Always check locally first
            self.appimagetool_path = find_executable_in_path("appimagetool")
            if self.appimagetool_path:
                self.log(_("Found appimagetool: {}").format(self.appimagetool_path))
                return True

            download_path = self.build_dir / "appimagetool-x86_64.AppImage"
            if download_path.exists():
                self.appimagetool_path = str(download_path)
                return True

            url = "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"

            self.log(_("Downloading appimagetool..."))

            def progress_cb(pct):
                self.update_progress(75 + int(pct * 0.1), _("Downloading appimagetool"))

            download_file(url, download_path, progress_cb)

            verified, sha256 = verify_download_sha256(download_path, url + ".sha256")
            self.log(f"[SHA256] appimagetool: {sha256}")
            if not verified:
                self.log(_("⚠ SHA256 checksum mismatch for appimagetool!"))
                download_path.unlink(missing_ok=True)
                return False

            make_executable(download_path)

            self.appimagetool_path = str(download_path)
            return True

        except Exception as e:
            self.log(_("Failed to setup appimagetool: {}").format(e))
            return False

    def download_linuxdeploy(self) -> bool:
        """Download or find linuxdeploy"""
        self.log(_("Setting up linuxdeploy..."))

        try:
            # Check if linuxdeploy is already in PATH
            self.linuxdeploy_path = find_executable_in_path("linuxdeploy")
            if self.linuxdeploy_path:
                self.log(_("Found linuxdeploy: {}").format(self.linuxdeploy_path))
                return True

            # Check if already downloaded in build directory
            download_path = self.build_dir / "linuxdeploy-x86_64.AppImage"
            if download_path.exists():
                self.linuxdeploy_path = str(download_path)
                make_executable(download_path)
                return True

            # Download linuxdeploy
            url = "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"

            self.log(_("Downloading linuxdeploy..."))

            def progress_cb(pct):
                self.update_progress(55 + int(pct * 0.05), _("Downloading linuxdeploy"))

            download_file(url, download_path, progress_cb)

            verified, sha256 = verify_download_sha256(download_path, url + ".sha256")
            self.log(f"[SHA256] linuxdeploy: {sha256}")
            if not verified:
                self.log(_("⚠ SHA256 checksum mismatch for linuxdeploy!"))
                download_path.unlink(missing_ok=True)
                return False

            make_executable(download_path)

            self.linuxdeploy_path = str(download_path)
            return True

        except Exception as e:
            self.log(_("Failed to setup linuxdeploy: {}").format(e))
            return False

    def build_appimage(self) -> str:
        """Build final AppImage"""
        self.log(_("Building AppImage..."))

        if not self.appimagetool_path:
            raise RuntimeError(_("appimagetool not available"))

        try:
            env = os.environ.copy()
            system_info = get_system_info()
            env["ARCH"] = system_info["architecture"]

            output_dir = Path(self.app_info.output_dir or Path.cwd())
            output_dir.mkdir(parents=True, exist_ok=True)

            output_name = f"{self.app_info.executable_name}-{self.app_info.version}-{system_info['architecture']}.AppImage"
            output_path = output_dir / output_name

            cmd = [self.appimagetool_path, str(self.appdir_path), str(output_path)]

            self.log(_("Running: {}").format(" ".join(cmd)))

            # appimagetool must run locally (needs FUSE)
            if self.container_name:
                self.log(_("Note: appimagetool runs locally (requires FUSE)"))

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
                timeout=300,
            )

            if result.returncode == 0 and output_path.exists():
                self.log(_("AppImage created: {}").format(output_path))
                return str(output_path)
            else:
                error_msg = result.stderr or result.stdout or _("Unknown error")
                self.log("appimagetool stdout:\n{}".format(result.stdout))
                self.log("appimagetool stderr:\n{}".format(result.stderr))

                raise RuntimeError(_("Build failed: {}").format(error_msg))

        except subprocess.TimeoutExpired:
            raise RuntimeError(_("Build timed out"))
        except Exception as e:
            self.log(_("Build failed: {}").format(e))
            raise

    def cleanup(self) -> None:
        """Clean up temporary files"""
        if self.build_dir and self.build_dir.exists():
            try:
                shutil.rmtree(self.build_dir)
                self.log(_("Cleaned up temporary files"))
            except Exception as e:
                self.log(_("Warning: Cleanup failed: {}").format(e))

    def build(self) -> str:
        """Main build process"""
        if not self.app_info:
            raise ValueError(_("Application information not set"))

        # Check for local build compatibility warning
        warning = self.get_compatibility_warning()
        if warning:
            self.log(_("⚠️ WARNING: Building locally - compatibility may be limited"))
            self.log(warning["message"])

        # Validate container if using one
        if self.build_environment:
            self.log(
                _("Validating build environment for {} application...").format(
                    self.app_info.app_type or "unknown"
                )
            )

            app_type = self.app_info.app_type or "binary"
            validation_failed = []

            try:
                # Validate based on app type
                if app_type in ["python", "python_wrapper", "gtk", "qt"]:
                    # Validate Python
                    result = subprocess.run(
                        [
                            "distrobox-enter",
                            self.container_name,
                            "--",
                            "python3",
                            "--version",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode != 0:
                        validation_failed.append("python3")
                    else:
                        self.log(_("✓ Python: {}").format(result.stdout.strip()))

                elif app_type == "java":
                    # Validate Java
                    result = subprocess.run(
                        [
                            "distrobox-enter",
                            self.container_name,
                            "--",
                            "java",
                            "-version",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode != 0:
                        validation_failed.append("java")
                    else:
                        self.log(_("✓ Java installed"))

                # Always validate basic tools in container
                for tool in ["git", "file"]:
                    result = subprocess.run(
                        ["distrobox-enter", self.container_name, "--", "which", tool],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode != 0:
                        validation_failed.append(tool)
                    else:
                        self.log(_("✓ {} available").format(tool))

                if validation_failed:
                    raise RuntimeError(
                        _(
                            "Missing dependencies in container '{}':\n{}\n\n"
                            "Go to Build Environment → click Setup for this container."
                        ).format(self.build_environment, ", ".join(validation_failed))
                    )

            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    _("Container '{}' is not responding.").format(self.container_name)
                )

        try:
            self.cancel_requested = False

            # Initialize the build environment
            self.update_progress(0, _("Initializing..."))
            self.create_build_directory()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))
            self.create_appdir_structure()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Copy application source files
            self.copy_application_files()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Install native GUI dependencies in the container and download plugins
            gui_deps = self._detect_gui_dependencies(self.app_info)
            if gui_deps:
                self._ensure_native_dependencies(gui_deps)

            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Process the application icon
            self.process_application_icon()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Detect Python version from container
            if self.app_info.app_type in [
                "python",
                "python_wrapper",
                "gtk",
                "qt",
            ]:
                py_cmd = [
                    "python3",
                    "-c",
                    "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
                ]
                result = self._run_command(py_cmd, capture_output=True, timeout=10)
                if result.returncode == 0:
                    self.python_version = result.stdout.strip()
                    self.log(
                        _("Detected Python version for AppRun: {}").format(
                            self.python_version
                        )
                    )
                else:
                    import sys

                    self.python_version = (
                        f"{sys.version_info.major}.{sys.version_info.minor}"
                    )
                    self.log(
                        _(
                            "Warning: Could not detect container Python, using builder Python: {}"
                        ).format(self.python_version)
                    )

            # Create the custom AppRun and desktop files
            self.create_launcher_and_desktop_files()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Copy integration helper scripts
            self.copy_integration_helpers()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Bundle all dependencies
            self.copy_dependencies()
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Download appimagetool
            if not self.download_appimagetool():
                raise RuntimeError(_("Failed to setup appimagetool"))
            if self.cancel_requested:
                raise RuntimeError(_("Build cancelled"))

            # Pre-packaging validation
            self.update_progress(82, _("Validating AppDir..."))
            validator = PrePackagingValidator(
                log_fn=self.log,
                run_command_fn=self._run_command if self.container_name else None,
            )
            validation = validator.validate_libraries(self.appdir_path)
            self.validation_result = validation
            if not validation["ok"]:
                self.log(
                    _(
                        "Warning: Some library dependencies are unresolved. "
                        "The AppImage may not work on all systems."
                    )
                )

            # Generate the final AppImage file
            self.update_progress(85, _("Building AppImage..."))
            appimage_path = self.build_appimage()

            self.update_progress(100, _("Build complete!"))
            return appimage_path

        except Exception as e:
            self.log(_("✗ Build failed: {}").format(e))
            raise
        finally:
            self.cleanup()

    def build_async(self, callback: Callable[[str, Exception], None]) -> None:
        """Build asynchronously"""

        def build_thread():
            try:
                result = self.build()
                callback(result, None)
            except Exception as e:
                callback(None, e)

        if self._build_thread and self._build_thread.is_alive():
            self.log(_("Build already in progress"))
            return self._build_thread

        self._build_thread = threading.Thread(target=build_thread, daemon=True)
        self._build_thread.start()
        return self._build_thread
