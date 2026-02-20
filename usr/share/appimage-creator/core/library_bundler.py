"""
Library, typelib, icon-theme, GStreamer plugin, and MPV config bundling.

Copies system shared libraries, GObject introspection typelibs,
GStreamer plugins, MPV configuration, and symbolic icon themes
into the AppDir for AppImage packaging.
"""

import os
import re
import shutil
from pathlib import Path

from core.build_config import SYSTEM_DEPENDENCIES
from utils.system import make_executable
from utils.i18n import _


class LibraryBundler:
    """Bundles system libraries and related assets into an AppDir."""

    def __init__(self, builder):
        self._b = builder

    # ------------------------------------------------------------------
    # System libraries
    # ------------------------------------------------------------------

    def copy_system_libraries(self) -> None:
        """Copy required system .so libraries to AppDir, separating conflicting ones."""
        lib_dir = self._b.appdir_path / "usr" / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)

        fallback_lib_dir = self._b.appdir_path / "usr" / "lib-fallback"
        fallback_lib_dir.mkdir(parents=True, exist_ok=True)

        required_libs = []
        conflicting_libs = []
        selected_deps = self._b.app_info.selected_dependencies

        for dep_key in selected_deps:
            if dep_key in SYSTEM_DEPENDENCIES:
                dep_info = SYSTEM_DEPENDENCIES[dep_key]
                if dep_info.get("conflicting", False):
                    conflicting_libs.extend(dep_info.get("libs", []))
                else:
                    required_libs.extend(dep_info.get("libs", []))

        required_libs = sorted(list(set(required_libs)))
        conflicting_libs = sorted(list(set(conflicting_libs)))

        extra_libs = self._b.app_info.extra_libraries
        if extra_libs:
            self._b.log(
                _("Including user-specified extra libraries: {}").format(
                    ", ".join(extra_libs)
                )
            )
            required_libs.extend(extra_libs)
            required_libs = sorted(list(set(required_libs)))

        if required_libs:
            self._b.log(
                _("Copying standard system libraries: {}").format(
                    ", ".join(required_libs)
                )
            )
            self._execute_library_copy(required_libs, lib_dir)

        if conflicting_libs:
            self._b.log(
                _("Copying conflicting system libraries to fallback dir: {}").format(
                    ", ".join(conflicting_libs)
                )
            )
            self._execute_library_copy(conflicting_libs, fallback_lib_dir)

    def _execute_library_copy(self, lib_patterns, dest_dir):
        """Find and copy the correct SONAME-versioned library file."""
        system_lib_paths = [
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib64",
            "/lib/x86_64-linux-gnu",
            "/lib64",
            "/usr/lib",
            "/lib",
        ]

        self._b.log(_("Generating script to copy libraries to {}...").format(dest_dir))

        script_lines = ["#!/bin/bash", "set -e", f'DEST_DIR="{dest_dir}"', ""]

        for pattern in lib_patterns:
            script_lines.extend([
                f'echo "--- Processing {pattern} ---"',
                "FOUND=0",
                "for search_path in "
                + " ".join(f'"{p}"' for p in system_lib_paths)
                + "; do",
                '    BASE_FILE=$(find "$search_path" -maxdepth 1 -name '
                + f"'{pattern}'"
                + " | sort | head -n 1)",
                '    if [ -n "$BASE_FILE" ] && [ -e "$BASE_FILE" ]; then',
                "        SONAME=$(readelf -d \"$BASE_FILE\" 2>/dev/null | grep '(SONAME)' | awk -F'[][]' '{print $2}')",
                '        if [ -n "$SONAME" ]; then',
                '            TARGET_FILE="$(dirname "$BASE_FILE")/$SONAME"',
                "        else",
                '            TARGET_FILE="$BASE_FILE"',
                "        fi",
                '        if [ -e "$TARGET_FILE" ]; then',
                '            echo "Copying $(basename "$TARGET_FILE") from $search_path..."',
                '            cp -vL "$TARGET_FILE" "$DEST_DIR/"',
                "            FOUND=1",
                "            break # Found it, stop searching other paths",
                "        fi",
                "    fi",
                "done",
                "if [ $FOUND -eq 0 ]; then",
                f"    echo '    -> {pattern} not found.'",
                "fi",
                "",
            ])

        script_content = "\n".join(script_lines)
        script_path = self._b.build_dir / f"copy_libs_{dest_dir.name}.sh"

        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)

        self._b.log(_("Executing library copy script..."))
        result = self._b._run_command([str(script_path)])

        if result.stdout:
            for line in result.stdout.splitlines():
                self._b.log(f"[copy_libs] {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                self._b.log(f"[copy_libs ERROR] {line}")

        if result.returncode != 0:
            self._b.log(_("Warning: Library copy script finished with errors."))
        else:
            self._b.log(_("Library copy script finished successfully."))

    # ------------------------------------------------------------------
    # Typelibs
    # ------------------------------------------------------------------

    def copy_typelibs(self) -> None:
        """Copy GObject Introspection typelib files based on selected dependencies."""
        typelib_dir = self._b.appdir_path / "usr" / "lib" / "girepository-1.0"
        typelib_dir.mkdir(parents=True, exist_ok=True)

        required_typelibs = []
        selected_deps = self._b.app_info.selected_dependencies
        for dep_key in selected_deps:
            if dep_key in SYSTEM_DEPENDENCIES:
                required_typelibs.extend(
                    SYSTEM_DEPENDENCIES[dep_key].get("typelibs", [])
                )

        required_typelibs = sorted(list(set(required_typelibs)))
        if not required_typelibs:
            self._b.log(_("No typelibs selected for inclusion."))
            return

        self._b.log(
            _("Copying selected typelibs: {}").format(", ".join(required_typelibs))
        )

        system_typelib_paths = [
            "/usr/lib/x86_64-linux-gnu/girepository-1.0",
            "/usr/lib/girepository-1.0",
            "/usr/lib64/girepository-1.0",
        ]

        self._b.log(_("Generating script to copy typelibs..."))

        script_lines = [
            "#!/bin/bash",
            "set -e",
            f'DEST_DIR="{typelib_dir}"',
            'mkdir -p "$DEST_DIR"',
            "COPIED=0",
            "",
        ]

        for typelib in required_typelibs:
            script_lines.append(f'echo "Searching for {typelib}..."')
            script_lines.append("FOUND=0")
            for search_path in system_typelib_paths:
                script_lines.append(f'if [ -f "{search_path}/{typelib}" ]; then')
                script_lines.append(f'    cp -v "{search_path}/{typelib}" "$DEST_DIR/"')
                script_lines.append("    COPIED=$((COPIED + 1))")
                script_lines.append("    FOUND=1")
                script_lines.append("fi")
            script_lines.append("if [ $FOUND -eq 0 ]; then")
            script_lines.append(
                f'    echo "  -> {typelib} not found (may be optional)"'
            )
            script_lines.append("fi")
            script_lines.append("")

        script_lines.append('echo "Copied $COPIED typelib files"')

        script_content = "\n".join(script_lines)
        script_path = self._b.build_dir / "copy_typelibs.sh"

        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)

        self._b.log(_("Executing typelib copy script..."))
        result = self._b._run_command([str(script_path)])

        if result.stdout:
            for line in result.stdout.splitlines():
                self._b.log(f"[typelibs] {line}")

        if result.returncode != 0:
            self._b.log(_("Warning: Some typelibs may not have been copied"))
        else:
            self._b.log(_("Typelib copy complete"))

    # ------------------------------------------------------------------
    # GStreamer plugins
    # ------------------------------------------------------------------

    def copy_gstreamer_plugins(self) -> None:
        """Copy only essential GStreamer plugins based on detected usage."""
        selected_deps = self._b.app_info.selected_dependencies
        if "gstreamer-gtk" not in selected_deps:
            return

        self._b.log(_("Copying essential GStreamer plugins..."))

        GSTREAMER_PLUGIN_PROFILES = {
            "audio-preview": [
                "libgstcoreelements.so",
                "libgstautodetect.so",
                "libgstvolume.so",
                "libgstplayback.so",
                "libgsttypefindfunctions.so",
                "libgstaudioparsers.so",
                "libgstaudioconvert.so",
                "libgstaudioresample.so",
            ],
            "video-playback": [
                "libgstcoreelements.so",
                "libgstautodetect.so",
                "libgstplayback.so",
                "libgsttypefindfunctions.so",
                "libgstvideoconvert.so",
                "libgstvideoscale.so",
                "libgstvideorate.so",
                "libgstvideofilter.so",
                "libgstvideobalance.so",
                "libgstgtk4.so",
                "libgstaudioconvert.so",
                "libgstaudioresample.so",
                "libgstvolume.so",
                "libgstmatroska.so",
                "libgstisomp4.so",
                "libgstavi.so",
                "libgstaudioparsers.so",
                "libgstvideoparsersbad.so",
            ],
        }

        profile_to_use = "audio-preview"

        structure_analysis = self._b.app_info.structure_analysis or {}
        if structure_analysis:
            project_root = structure_analysis.get("project_root")
            if project_root:
                try:
                    root_path = Path(project_root)
                    for py_file in root_path.rglob("*.py"):
                        try:
                            text = py_file.read_text(errors="ignore")
                            if "gtk4paintablesink" in text:
                                profile_to_use = "video-playback"
                                self._b.log(
                                    _("Detected video playback requirements")
                                )
                                break
                        except OSError:
                            continue
                except Exception:
                    pass

        plugins_to_copy = GSTREAMER_PLUGIN_PROFILES.get(profile_to_use, [])

        plugin_dir = self._b.appdir_path / "usr" / "lib" / "gstreamer-1.0"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        system_plugin_paths = [
            "/usr/lib/x86_64-linux-gnu/gstreamer-1.0",
            "/usr/lib64/gstreamer-1.0",
            "/usr/lib/gstreamer-1.0",
        ]

        script_lines = [
            "#!/bin/bash",
            "set -e",
            f'DEST_DIR="{plugin_dir}"',
            "COPIED=0",
            "",
            f"echo 'Using GStreamer profile: {profile_to_use}'",
            "",
        ]

        for plugin in plugins_to_copy:
            script_lines.append(f"# Searching for {plugin}")
            for search_path in system_plugin_paths:
                script_lines.append(f'if [ -f "{search_path}/{plugin}" ]; then')
                script_lines.append(f'    cp -v "{search_path}/{plugin}" "$DEST_DIR/"')
                script_lines.append("    COPIED=$((COPIED + 1))")
                script_lines.append("    break")
                script_lines.append("fi")
            script_lines.append("")

        script_lines.append('echo "Copied $COPIED GStreamer plugins"')
        script_lines.append('echo "Total size: $(du -sh "$DEST_DIR" | cut -f1)"')

        script_content = "\n".join(script_lines)
        script_path = self._b.build_dir / "copy_gstreamer_plugins.sh"

        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)

        self._b.log(_("Copying GStreamer plugins..."))
        result = self._b._run_command([str(script_path)])

        if result.stdout:
            for line in result.stdout.splitlines():
                self._b.log(f"[gst-plugins] {line}")

        self._b.log(_("GStreamer plugin copying complete"))

    # ------------------------------------------------------------------
    # MPV config
    # ------------------------------------------------------------------

    def copy_mpv_config(self) -> None:
        """Copies MPV configuration files if MPV is a detected dependency."""
        selected_deps = self._b.app_info.selected_dependencies
        if "mpv" not in selected_deps:
            return

        self._b.log("Copying MPV configuration files...")

        system_mpv_paths = ["/etc/mpv", "/usr/share/mpv"]

        dest_dir = self._b.appdir_path / "usr" / "share" / "mpv"
        dest_dir.mkdir(parents=True, exist_ok=True)

        copied = False
        if self._b.container_name:
            # Container mode: use shell to access container filesystem
            for path in system_mpv_paths:
                result = self._b._run_command(
                    ["bash", "-c", f'[ -d "{path}" ] && cp -a "{path}"/* "{dest_dir}/"']
                )
                if result.returncode == 0:
                    self._b.log(f"MPV config copied from {path}")
                    copied = True
                    break
        else:
            # Local mode: use Python-native operations
            for path in system_mpv_paths:
                src = Path(path)
                if src.is_dir():
                    for item in src.iterdir():
                        dst = dest_dir / item.name
                        if item.is_dir():
                            shutil.copytree(item, dst, dirs_exist_ok=True)
                        else:
                            shutil.copy2(item, dst)
                    self._b.log(f"MPV config copied from {path}")
                    copied = True
                    break

        if not copied:
            self._b.log("Warning: Could not find MPV configuration files to copy.")

    # ------------------------------------------------------------------
    # Icon themes
    # ------------------------------------------------------------------

    def copy_symbolic_icons(self) -> None:
        """Copy Adwaita symbolic icons for UI elements."""
        self._b.log(_("Copying Adwaita symbolic icons..."))

        icons_dir = self._b.appdir_path / "usr" / "share" / "icons" / "Adwaita"
        icons_dir.mkdir(parents=True, exist_ok=True)

        symbolic_dest = icons_dir / "symbolic"

        if symbolic_dest.exists() and (symbolic_dest / "ui").exists():
            self._b.log(_("Symbolic icons already present"))
            return

        source_path = Path("/usr/share/icons/Adwaita/symbolic")
        success = False

        if self._b.container_name:
            self._b.log(_("Copying symbolic icons from container..."))
            script = (
                f'set -e; SOURCE="{source_path}"; DEST="{symbolic_dest}"; '
                f'[ -d "$SOURCE" ] && cp -r "$SOURCE" "$DEST" && '
                f'echo "Copied $(find "$DEST" -name \'*.svg\' | wc -l) icons"'
            )
            result = self._b._run_command(["bash", "-c", script])
            if result.stdout:
                for line in result.stdout.splitlines():
                    self._b.log(f"[icons] {line}")
            success = result.returncode == 0
        else:
            self._b.log(_("Copying symbolic icons from host system..."))
            if source_path.is_dir():
                shutil.copytree(source_path, symbolic_dest, dirs_exist_ok=True)
                icon_count = len(list(symbolic_dest.rglob("*.svg")))
                self._b.log(f"[icons] Copied {icon_count} symbolic icons")
                success = True
            else:
                self._b.log(
                    _("Warning: Adwaita symbolic icons not found at {}").format(
                        source_path
                    )
                )

        if not success:
            self._b.log(_("Warning: Failed to copy symbolic icons"))
        else:
            self._b.log(_("Creating custom index.theme for Adwaita symbolic icons..."))

            icons_dir = self._b.appdir_path / "usr" / "share" / "icons" / "Adwaita"
            index_file = icons_dir / "index.theme"

            if icons_dir.exists():
                custom_index = """[Icon Theme]
Name=Adwaita
Comment=Adwaita icon theme (symbolic only)
Inherits=hicolor

# Only symbolic directory included
Directories=symbolic/actions,symbolic/apps,symbolic/categories,symbolic/devices,symbolic/emblems,symbolic/emotes,symbolic/legacy,symbolic/mimetypes,symbolic/places,symbolic/status,symbolic/ui

[symbolic/actions]
Context=Actions
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/apps]
Context=Applications
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/categories]
Context=Categories
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/devices]
Context=Devices
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emblems]
Context=Emblems
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emotes]
Context=Emotes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/legacy]
Context=Legacy
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/mimetypes]
Context=MimeTypes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/places]
Context=Places
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/status]
Context=Status
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/ui]
Context=UI
Size=16
MinSize=16
MaxSize=512
Type=Scalable
"""

                with open(index_file, "w") as f:
                    f.write(custom_index)

                self._b.log("Created custom index.theme for Adwaita")

            self._b.log(_("Symbolic icons copied successfully"))

    def copy_papirus_symbolic_icons(self) -> None:
        """Copy Papirus symbolic icons for GTK applications."""
        self._b.log(_("Copying Papirus symbolic icons..."))

        categories = [
            "actions",
            "categories",
            "devices",
            "emblems",
            "emotes",
            "mimetypes",
            "places",
            "status",
            "up-to-32",
        ]

        themes = ["Papirus", "Papirus-Dark"]

        icons_base_dir = self._b.appdir_path / "usr" / "share" / "icons"
        icons_base_dir.mkdir(parents=True, exist_ok=True)

        papirus_test = icons_base_dir / "Papirus" / "symbolic" / "actions"
        if papirus_test.exists() and list(papirus_test.glob("*.svg")):
            self._b.log(_("Papirus symbolic icons already present"))
            return

        if self._b.container_name:
            source_base = "/usr/share/icons"
        else:
            source_base = "/usr/share/icons"

        self._b.log(_("Copying Papirus and Papirus-Dark symbolic icons..."))

        script_lines = [
            "#!/bin/bash",
            "set -e",
            f'SOURCE_BASE="{source_base}"',
            f'DEST_BASE="{icons_base_dir}"',
            "",
            "COPIED=0",
            "THEMES_COPIED=0",
            "",
        ]

        for theme in themes:
            script_lines.extend([
                f"# Process {theme} theme",
                f'SOURCE_THEME="$SOURCE_BASE/{theme}"',
                f'DEST_THEME="$DEST_BASE/{theme}"',
                "",
                'if [ ! -d "$SOURCE_THEME" ]; then',
                f"    echo 'Warning: {theme} not found in container - skipping'",
                "else",
                "    THEMES_COPIED=$((THEMES_COPIED + 1))",
                '    mkdir -p "$DEST_THEME"',
                "",
                "    # Copy index.theme file",
                '    if [ -f "$SOURCE_THEME/index.theme" ]; then',
                '        cp "$SOURCE_THEME/index.theme" "$DEST_THEME/"',
                f"        echo 'Copied {theme}/index.theme'",
                "    fi",
                "",
            ])

            for category in categories:
                script_lines.extend([
                    f"    # Copy symbolic/{category}/",
                    f'    if [ -d "$SOURCE_THEME/symbolic/{category}" ]; then',
                    f'        mkdir -p "$DEST_THEME/symbolic/{category}"',
                    f'        cp -r "$SOURCE_THEME/symbolic/{category}"/* "$DEST_THEME/symbolic/{category}/" 2>/dev/null || true',
                    '        COUNT=$(find "$DEST_THEME/symbolic/'
                    + category
                    + "\" -name '*.svg' 2>/dev/null | wc -l)",
                    "        COPIED=$((COPIED + COUNT))",
                    f"        echo '  Copied {category}/: '$COUNT' icons'",
                    "    fi",
                    "",
                ])

            script_lines.append("fi")
            script_lines.append("")

        script_lines.extend([
            "if [ $THEMES_COPIED -eq 0 ]; then",
            "    echo 'ERROR: No Papirus themes found in container'",
            "    echo 'Falling back to Adwaita icons...'",
            "    exit 1",
            "fi",
            "",
            "echo ''",
            "echo '=== Summary ==='",
            'echo "Themes copied: $THEMES_COPIED/2"',
            'echo "Total icons: $COPIED"',
            'echo "Size: ~6.4MB"',
        ])

        script_content = "\n".join(script_lines)
        script_path = self._b.build_dir / "copy_papirus_icons.sh"

        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)

        self._b.log(_("Executing Papirus icons copy script..."))
        result = self._b._run_command([str(script_path)])

        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    self._b.log(f"[papirus] {line}")

        if result.returncode != 0:
            self._b.log(_("Warning: Papirus icons not available, falling back to Adwaita"))
            self.copy_symbolic_icons()
        else:
            self._b.log(_("Creating custom index.theme for Papirus symbolic icons..."))

            for theme in ["Papirus", "Papirus-Dark"]:
                theme_dir = icons_base_dir / theme
                index_file = theme_dir / "index.theme"

                if theme_dir.exists():
                    inherits = (
                        "breeze,hicolor"
                        if theme == "Papirus"
                        else "breeze-dark,hicolor"
                    )

                    custom_index = f"""[Icon Theme]
Name={theme}
Comment={theme} icon theme (symbolic only)
Inherits={inherits}

# Only symbolic directories included
Directories=symbolic/actions,symbolic/categories,symbolic/devices,symbolic/emblems,symbolic/emotes,symbolic/mimetypes,symbolic/places,symbolic/status,symbolic/up-to-32

[symbolic/actions]
Context=Actions
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/categories]
Context=Categories
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/devices]
Context=Devices
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emblems]
Context=Emblems
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emotes]
Context=Emotes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/mimetypes]
Context=MimeTypes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/places]
Context=Places
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/status]
Context=Status
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/up-to-32]
Context=Status
Size=16
MinSize=16
MaxSize=32
Type=Scalable
"""

                    with open(index_file, "w") as f:
                        f.write(custom_index)

                    self._b.log(f"Created custom index.theme for {theme}")

            self._b.log(_("Papirus symbolic icons copied successfully"))

    def create_icon_symlinks(self) -> None:
        """
        Read the Icon= field from the .desktop file, rename icon files to match that name,
        create symlinks in the root, and ensure .desktop file uses the correct Icon= value.
        The .desktop filename is NOT changed - only icon files are renamed based on Icon= field.

        MINIMAL FIX: Prefer PNG over SVG for .DirIcon symlink (better AppImage icon quality)
        """
        try:
            # --- Clean up any pre-existing icon symlinks in the AppDir root ---
            # But preserve updater icon symlink
            self._b.log("Cleaning up existing icon symlinks in AppDir root...")
            root_path = self._b.appdir_path
            for item in root_path.iterdir():
                if item.is_symlink() and item.suffix.lower() in ['.svg', '.png', '.xpm']:
                    # Don't delete updater icon symlink
                    if 'appimage-update' not in item.name.lower():
                        self._b.log(f"Removing old symlink: {item.name}")
                        item.unlink()
                    else:
                        self._b.log(f"Preserving updater icon symlink: {item.name}")
            dir_icon_path = root_path / ".DirIcon"
            if dir_icon_path.is_symlink():
                self._b.log("Removing old .DirIcon symlink")
                dir_icon_path.unlink()
            # --- END OF CLEANUP LOGIC ---

            icons_dir = self._b.appdir_path / "usr" / "share" / "icons"
            if not icons_dir.exists():
                self._b.log("No icons directory found, skipping icon symlinks.")
                return

            # First, try to get the expected icon name from the .desktop file
            # Exclude updater and vainfo (created by linuxdeploy) desktop files
            expected_icon_name = None
            desktop_files_dir = self._b.appdir_path / "usr/share/applications"
            if desktop_files_dir.exists():
                for desktop_file in desktop_files_dir.glob("*.desktop"):
                    # Skip updater and vainfo desktop files
                    fname_lower = desktop_file.name.lower()
                    if 'updater' in fname_lower or 'vainfo' in fname_lower:
                        continue
                    try:
                        content = desktop_file.read_text()
                        match = re.search(r'^Icon=(.+)$', content, re.MULTILINE)
                        if match:
                            expected_icon_name = match.group(1).strip()
                            self._b.log(f"[DEBUG] Expected icon from .desktop ({desktop_file.name}): {expected_icon_name}")
                            break
                    except Exception:
                        pass

            # Find the icon file (SVG preferred, then PNG, then XPM)
            # Exclude updater icon (appimage-update.*) from the search
            icon_file = None
            all_found_icons = []

            for ext in ['.svg', '.png', '.xpm']:
                found_icons = list(icons_dir.rglob(f"*{ext}"))
                # Filter out updater icon
                found_icons = [icon for icon in found_icons if 'appimage-update' not in icon.name.lower()]
                all_found_icons.extend(found_icons)

            self._b.log(f"[DEBUG] All found icons (excluding updater): {[i.name for i in all_found_icons]}")

            if all_found_icons:
                # Prioritize icon matching expected_icon_name
                if expected_icon_name:
                    matching = [i for i in all_found_icons if i.stem.lower() == expected_icon_name.lower()]
                    if matching:
                        icon_file = matching[0]
                        self._b.log(f"[DEBUG] Using matching icon: {icon_file.name}")
                    else:
                        # Try partial match
                        partial_match = [i for i in all_found_icons if expected_icon_name.lower() in i.stem.lower()]
                        if partial_match:
                            icon_file = partial_match[0]
                            self._b.log(f"[DEBUG] Using partial matching icon: {icon_file.name}")

                # Fallback to first SVG, then PNG, then XPM
                if not icon_file:
                    for ext in ['.svg', '.png', '.xpm']:
                        ext_icons = [i for i in all_found_icons if i.suffix.lower() == ext]
                        if ext_icons:
                            icon_file = ext_icons[0]
                            self._b.log(f"[DEBUG] Using first {ext} icon: {icon_file.name}")
                            break

            if not icon_file:
                self._b.log("No icon file found in usr/share/icons to create symlinks for.")
                return

            self._b.log(f"Selected icon for symlinks: {icon_file}")

            # Find the main .desktop file
            desktop_files_dir = self._b.appdir_path / "usr/share/applications"
            if not desktop_files_dir.exists():
                self._b.log("Warning: applications directory not found, cannot create icon symlinks.")
                return

            main_desktop_file = None
            structure_analysis = self._b.app_info.structure_analysis or {}
            detected_desktops = structure_analysis.get('detected_files', {}).get('desktop_files', [])

            # Filter out updater and vainfo desktop files from analysis
            detected_desktops = [d for d in detected_desktops
                                 if 'updater' not in Path(d).name.lower()
                                 and 'vainfo' not in Path(d).name.lower()]

            # Try to find the desktop file from structure analysis
            if detected_desktops:
                original_desktop_filename = Path(detected_desktops[0]).name
                candidate_path = desktop_files_dir / original_desktop_filename
                if candidate_path.exists():
                    main_desktop_file = candidate_path
                    self._b.log(f"Found main desktop file via analysis: {original_desktop_filename}")

            # Fallback: search for any .desktop file (excluding updater and vainfo)
            if not main_desktop_file:
                all_desktop_files = [f for f in desktop_files_dir.glob("*.desktop")
                                     if 'updater' not in f.name.lower()
                                     and 'vainfo' not in f.name.lower()]
                if not all_desktop_files:
                    self._b.log("Warning: No main .desktop file found after fallback search.")
                    return

                app_exec_name = (self._b.app_info.executable_name or '').replace('-gui', '')
                preferred_file = next((f for f in all_desktop_files if app_exec_name in f.name), None)

                if preferred_file:
                    main_desktop_file = preferred_file
                else:
                    main_desktop_file = all_desktop_files[0]

                self._b.log(f"Warning: Using fallback to find main desktop file: {main_desktop_file.name}")

            # Read the .desktop file and extract the Icon= field value
            with open(main_desktop_file, 'r', encoding='utf-8') as f:
                desktop_content = f.read()

            icon_match = re.search(r'^Icon=(.+)$', desktop_content, flags=re.MULTILINE)

            if not icon_match:
                self._b.log("Warning: No Icon= field found in .desktop file, cannot determine icon name.")
                return

            # Extract the icon base name (without path or extension)
            icon_value = icon_match.group(1).strip()
            # Remove any path components if present
            icon_basename = Path(icon_value).stem

            self._b.log(f"Extracted icon name from .desktop file: {icon_basename}")

            # === Check if PNG exists alongside the icon file ===
            # If we found an SVG, check if there's a PNG version in the same directory
            icon_file_for_symlink = icon_file
            if icon_file.suffix.lower() == '.svg':
                png_alternative = icon_file.parent / f"{icon_file.stem}.png"
                if png_alternative.exists():
                    self._b.log(f"Found PNG version alongside SVG: {png_alternative.name}")
                    self._b.log("Using PNG for .DirIcon (better quality in file managers)")
                    icon_file_for_symlink = png_alternative
                else:
                    self._b.log("No PNG found alongside SVG, using SVG for symlinks")

            # Rename the icon file to match the Icon= field value
            icon_extension = icon_file_for_symlink.suffix
            new_icon_name = f"{icon_basename}{icon_extension}"
            new_icon_path = icon_file_for_symlink.parent / new_icon_name

            if icon_file_for_symlink != new_icon_path:
                self._b.log(f"Renaming icon file: {icon_file_for_symlink.name} -> {new_icon_name}")
                icon_file_for_symlink.rename(new_icon_path)
                icon_file_for_symlink = new_icon_path
            else:
                self._b.log(f"Icon file already has correct name: {new_icon_name}")

            # Create symlinks in the AppDir root
            relative_icon_path = os.path.relpath(icon_file_for_symlink, self._b.appdir_path)

            # Create main icon symlink
            root_icon_symlink = self._b.appdir_path / new_icon_name
            root_icon_symlink.symlink_to(relative_icon_path)
            self._b.log(f"Created root icon symlink: {root_icon_symlink.name} -> {relative_icon_path}")

            # Create .DirIcon symlink
            dir_icon_symlink = self._b.appdir_path / ".DirIcon"
            dir_icon_symlink.symlink_to(relative_icon_path)
            self._b.log(f"Created .DirIcon symlink: .DirIcon -> {relative_icon_path}")

            # Update the Icon= field in .desktop to use just the base name (no path, no extension)
            desktop_content = re.sub(r'^Icon=.*$', f'Icon={icon_basename}', desktop_content, flags=re.MULTILINE)

            with open(main_desktop_file, 'w', encoding='utf-8') as f:
                f.write(desktop_content)

            self._b.log(f"Updated 'Icon=' field in {main_desktop_file.name} to: {icon_basename}")

        except Exception as e:
            self._b.log(f"Warning: Failed to create icon symlinks: {e}")
