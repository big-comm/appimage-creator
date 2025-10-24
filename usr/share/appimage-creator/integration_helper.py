#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AppImage Desktop Integration Helper - Silent Automatic Mode
Silently integrates AppImage into system menu on first launch (Wayland only)
Automatically updates desktop file if AppImage path changes
"""

import os
import sys
import shutil
import configparser
from pathlib import Path


def integrate_appimage(app_name, appimage_path, desktop_file, icon_file, force_update=False):
    """
    Silently integrate AppImage into user's local directories
    
    Args:
        app_name: Application name
        appimage_path: Current absolute path to the AppImage
        desktop_file: Path to the .desktop file inside AppDir
        icon_file: Path to the icon file inside AppDir
        force_update: Force update even if already integrated
    
    Returns:
        0 on success, 1 on skip, 2 on error
    """
    try:
        # Define target paths
        apps_dir = Path.home() / ".local/share/applications"
        icons_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
        
        apps_dir.mkdir(parents=True, exist_ok=True)
        icons_dir.mkdir(parents=True, exist_ok=True)
        
        # Target paths
        target_desktop_path = apps_dir / desktop_file.name
        target_icon_path = icons_dir / icon_file.name
        
        # Determine if we need to update
        needs_update = force_update or not target_desktop_path.exists() or not target_icon_path.exists()
        
        if not needs_update:
            # Check if Exec= path in desktop file matches current AppImage path
            try:
                existing_content = target_desktop_path.read_text()
                import re
                exec_match = re.search(r'^Exec="?([^"\n]+)"?', existing_content, flags=re.MULTILINE)
                if exec_match:
                    existing_path = exec_match.group(1).strip()
                    # Remove %F or other arguments
                    existing_path = existing_path.split()[0].strip('"')
                    if existing_path != appimage_path:
                        needs_update = True
            except Exception:
                needs_update = True
        
        if not needs_update:
            return 1  # Already integrated and up-to-date
        
        # --- Copy icon file ---
        shutil.copy2(icon_file, target_icon_path)
        
        # --- Modify and write desktop file ---
        desktop_content = desktop_file.read_text()
        
        import re
        
        # 1. Replace Exec= with the absolute path to the AppImage
        modified_content = re.sub(
            r'^Exec=.*$',
            f'Exec="{appimage_path}" %F',
            desktop_content,
            flags=re.MULTILINE
        )
        
        # 2. Replace Icon= with the absolute path to the copied icon
        modified_content = re.sub(
            r'^Icon=.*$',
            f'Icon={str(target_icon_path)}',
            modified_content,
            flags=re.MULTILINE
        )
        
        # 3. Write the modified desktop file
        target_desktop_path.write_text(modified_content)
        
        # --- Update desktop database ---
        try:
            import subprocess
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
        except Exception:
            # Silently ignore if update-desktop-database fails
            pass
        
        return 0  # Success
        
    except Exception as e:
        # Log error to stderr but don't break the application launch
        print(f"Integration error: {e}", file=sys.stderr)
        return 2  # Error


def read_marker_file(marker_file):
    """
    Read the marker file to get the last known AppImage path
    
    Returns:
        str: Last known path, or None if marker doesn't exist
    """
    try:
        if marker_file.exists():
            return marker_file.read_text().strip()
    except Exception:
        pass
    return None


def write_marker_file(marker_file, appimage_path):
    """Write the current AppImage path to the marker file"""
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.write_text(appimage_path)
    except Exception as e:
        print(f"Warning: Could not write marker file: {e}", file=sys.stderr)


def main():
    """Main entry point - silent automatic integration"""
    if len(sys.argv) != 4:
        # Invalid arguments, silently exit
        sys.exit(0)
    
    app_name = sys.argv[1]
    appimage_path = sys.argv[2]
    desktop_filename = sys.argv[3]
    
    # Only run in graphical environment (X11 or Wayland)
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        sys.exit(0)
    
    # Validate APPDIR environment variable
    appdir = os.environ.get("APPDIR")
    if not appdir:
        sys.exit(0)
    
    appdir = Path(appdir)
    desktop_file_path = appdir / "usr/share/applications" / desktop_filename
    
    if not desktop_file_path.exists():
        sys.exit(0)
    
    # Read Icon= field from desktop file
    try:
        config = configparser.ConfigParser()
        config.read(desktop_file_path)
        icon_name = config.get('Desktop Entry', 'Icon')
    except Exception:
        sys.exit(0)
    
    # Search for the icon file in the AppDir root (where symlinks are)
    icon_file = None
    for ext in ['.svg', '.png', '.xpm']:
        potential_icon = appdir / f"{icon_name}{ext}"
        if potential_icon.exists():
            icon_file = potential_icon
            break
    
    if not icon_file:
        sys.exit(0)
    
    # Check marker file to determine if integration is needed
    marker_dir = Path.home() / ".local/share/appimage-integrations"
    marker_file = marker_dir / f"{app_name.replace(' ', '_')}.path"
    
    last_known_path = read_marker_file(marker_file)
    
    # Determine if we need to integrate/update
    force_update = False
    if last_known_path is None:
        # First time integration
        force_update = True
    elif last_known_path != appimage_path:
        # Path changed, need to update
        force_update = True
    
    # Perform integration
    result = integrate_appimage(
        app_name,
        appimage_path,
        desktop_file_path,
        icon_file,
        force_update=force_update
    )
    
    # Update marker file if integration was successful
    if result == 0:
        write_marker_file(marker_file, appimage_path)
    
    sys.exit(0)


if __name__ == "__main__":
    if os.environ.get("APPDIR"):
        main()