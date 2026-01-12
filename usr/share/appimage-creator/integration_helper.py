#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AppImage Desktop Integration Helper - Silent Automatic Mode
Silently integrates AppImage into system menu on first launch (Wayland only)
Automatically updates desktop file if AppImage path changes
Includes collaborative cleanup of orphaned integrations
Optionally sets up systemd watcher for automatic cleanup
"""

import os
import sys
import shutil
import configparser
import subprocess
from pathlib import Path


def cleanup_orphaned_integrations():
    """
    Collaborative cleanup: Check all integrated AppImages and remove orphaned ones.
    This runs every time ANY AppImage is executed, cleaning up all orphans.
    
    Returns:
        int: Number of orphaned integrations removed
    """
    marker_dir = Path.home() / ".local/share/appimage-integrations"
    
    if not marker_dir.exists():
        return 0
    
    removed_count = 0
    
    for marker_file in marker_dir.glob("*.path"):
        try:
            # Read marker file (format: line 1 = appimage path, line 2 = desktop filename)
            lines = marker_file.read_text().strip().split('\n')
            appimage_path = lines[0]
            desktop_filename = lines[1] if len(lines) > 1 else f"{marker_file.stem}.desktop"
            
            app_name = marker_file.stem
            
            # Check if AppImage still exists
            if not Path(appimage_path).exists():
                # Remove desktop file using the stored filename
                desktop_file = Path.home() / ".local/share/applications" / desktop_filename
                if desktop_file.exists():
                    desktop_file.unlink()
                    print(f"Removed orphaned desktop file: {desktop_filename}", file=sys.stderr)
                
                # Remove icon files (can be .svg, .png, .xpm, etc)
                icon_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
                if icon_dir.exists():
                    for icon in icon_dir.glob(f"{app_name}.*"):
                        icon.unlink()
                        print(f"Removed orphaned icon: {icon.name}", file=sys.stderr)
                
                # Remove marker file
                marker_file.unlink()
                removed_count += 1
                
        except Exception as e:
            print(f"Error cleaning {marker_file}: {e}", file=sys.stderr)
    
    if removed_count > 0:
        # Update desktop database
        try:
            subprocess.run(
                ["update-desktop-database", str(Path.home() / ".local/share/applications")],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
        except Exception:
            pass
    
    return removed_count


def is_systemd_available():
    """Check if systemd is available and running for the current user"""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True,
            timeout=2
        )
        # 0 = running, 1 = degraded (still ok)
        return result.returncode in [0, 1]
    except Exception:
        return False

def setup_systemd_watcher():
    """
    Set up systemd timer for automatic cleanup of orphaned AppImage integrations.
    Timer runs every 7 seconds to check for orphaned integrations.
    This only needs to run once, but is safe to call multiple times.
    
    Returns:
        bool: True if systemd was set up successfully, False otherwise
    """
    if not is_systemd_available():
        return False
    
    try:
        systemd_dir = Path.home() / ".config/systemd/user"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        
        service_file = systemd_dir / "appimage-cleaner.service"
        timer_file = systemd_dir / "appimage-cleaner.timer"
        
        # Remove old path unit if it exists
        old_path_file = systemd_dir / "appimage-cleaner.path"
        if old_path_file.exists():
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "appimage-cleaner.path"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            old_path_file.unlink()

        # ALWAYS update cleanup script and updater module (even if systemd already configured)
        # This ensures the latest version is always used
        bin_dir = Path.home() / ".local/bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        cleanup_script_dest = bin_dir / "appimage-cleanup.py"

        # Get the cleanup script and updater from the AppImage
        appdir = os.environ.get("APPDIR")
        if appdir:
            # Update cleanup script
            cleanup_script_source = Path(appdir) / "usr/bin/appimage-cleanup.py"
            if cleanup_script_source.exists():
                shutil.copy2(cleanup_script_source, cleanup_script_dest)
                cleanup_script_dest.chmod(0o755)

            # Update updater module
            updater_source = Path(appdir) / "usr/bin/updater"
            updater_dest = bin_dir / "updater"
            if updater_source.exists() and updater_source.is_dir():
                # Remove old updater module if exists
                if updater_dest.exists():
                    shutil.rmtree(updater_dest)
                # Copy new updater module
                shutil.copytree(updater_source, updater_dest)
            elif updater_source.parent.exists():
                # Try alternative location (for backward compatibility)
                alt_updater_source = Path(appdir) / "usr/lib/appimage-updater"
                if alt_updater_source.exists() and alt_updater_source.is_dir():
                    if updater_dest.exists():
                        shutil.rmtree(updater_dest)
                    updater_dest.mkdir(parents=True, exist_ok=True)
                    # Copy Python files
                    for py_file in alt_updater_source.glob("*.py"):
                        shutil.copy2(py_file, updater_dest / py_file.name)

            # Copy translation files for updater
            try:
                locale_source = Path(appdir) / "usr/share/locale"
                if locale_source.exists():
                    user_locale_dir = Path.home() / ".local/share/locale"
                    user_locale_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Iterate through all languages
                    for lang_dir in locale_source.iterdir():
                        if not lang_dir.is_dir():
                            continue
                            
                        mo_file = lang_dir / "LC_MESSAGES" / "appimage-updater.mo"
                        if mo_file.exists():
                            target_dir = user_locale_dir / lang_dir.name / "LC_MESSAGES"
                            target_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(mo_file, target_dir / "appimage-updater.mo")
            except Exception as e:
                # Silently ignore if translation copy fails
                print(f"Warning: Failed to copy translations: {e}", file=sys.stderr)

            # Copy updater icon and .desktop file (for dock/taskbar integration)
            try:
                # Copy updater icon
                updater_icon_source = Path(appdir) / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg"
                target_icon_path = None
                
                if updater_icon_source.exists():
                    icons_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
                    icons_dir.mkdir(parents=True, exist_ok=True)
                    target_icon_path = icons_dir / "appimage-update.svg"
                    shutil.copy2(updater_icon_source, target_icon_path)

                # Copy and patch updater .desktop file
                updater_desktop_source = Path(appdir) / "usr/share/applications/org.bigcommunity.appimage.updater.desktop"
                if updater_desktop_source.exists():
                    apps_dir = Path.home() / ".local/share/applications"
                    apps_dir.mkdir(parents=True, exist_ok=True)
                    target_desktop_path = apps_dir / "org.bigcommunity.appimage.updater.desktop"
                    
                    # Read and patch content
                    content = updater_desktop_source.read_text()
                    import re
                    
                    # Patch Icon path if icon was installed
                    if target_icon_path:
                        content = re.sub(
                            r'^Icon=.*$',
                            f'Icon={str(target_icon_path)}',
                            content,
                            flags=re.MULTILINE
                        )
                    
                    # Patch Exec path to point to the installed checker script
                    checker_script = Path.home() / ".local/bin/updater/check_updates.py"
                    content = re.sub(
                        r'^Exec=.*$',
                        f'Exec=python3 "{str(checker_script)}"',
                        content,
                        flags=re.MULTILINE
                    )
                    
                    target_desktop_path.write_text(content)
            except Exception as e:
                # Silently ignore if updater icon/desktop copy fails
                print(f"Warning: Failed to install updater desktop file: {e}", file=sys.stderr)

        # Check if already configured
        if service_file.exists() and timer_file.exists():
            # Already set up, just ensure timer is enabled
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "appimage-cleaner.timer"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # Kickstart the timer if not running
            subprocess.run(
                ["systemctl", "--user", "start", "appimage-cleaner.service"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            return True
        
        # Create service file
        service_content = """[Unit]
Description=AppImage Integration Cleaner
Documentation=https://github.com/AppImage/AppImageKit

[Service]
Type=oneshot
ExecStart=%h/.local/bin/appimage-cleanup.py

[Install]
WantedBy=default.target
"""
        service_file.write_text(service_content)
        
        # Create timer file (runs every 5 seconds)
        timer_content = """[Unit]
Description=Timer for AppImage Integration Cleanup

[Timer]
OnBootSec=5sec
OnUnitInactiveSec=5sec
Persistent=true

[Install]
WantedBy=timers.target
"""
        timer_file.write_text(timer_content)

        # Reload systemd and enable timer
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "appimage-cleaner.timer"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        
        # Run service once to kickstart the timer cycle
        subprocess.run(
            ["systemctl", "--user", "start", "appimage-cleaner.service"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        
        print("Systemd timer configured successfully (runs every 5 seconds)", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"Failed to setup systemd timer: {e}", file=sys.stderr)
        return False

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
    Read the marker file to get the last known AppImage path and version

    Returns:
        tuple: (path, version) or (None, None) if marker doesn't exist
    """
    try:
        if marker_file.exists():
            lines = marker_file.read_text().strip().split('\n')
            path = lines[0] if len(lines) > 0 else None
            version = lines[3] if len(lines) > 3 else None
            return (path, version)
    except Exception:
        pass
    return (None, None)

def write_marker_file(marker_file, appimage_path, desktop_filename,
                      update_url="", version="", update_pattern=""):
    """Write the current AppImage path and metadata to the marker file"""
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        # Format: line 1 = appimage path, line 2 = desktop filename
        # line 3 = update URL, line 4 = version, line 5 = update pattern
        content = f"{appimage_path}\n{desktop_filename}\n{update_url}\n{version}\n{update_pattern}"
        marker_file.write_text(content)
    except Exception as e:
        print(f"Warning: Could not write marker file: {e}", file=sys.stderr)

def main():
    """Main entry point - silent automatic integration with collaborative cleanup"""
    if len(sys.argv) < 4:
        # Invalid arguments, silently exit
        sys.exit(0)

    app_name = sys.argv[1]
    appimage_path = sys.argv[2]
    desktop_filename = sys.argv[3]

    # Optional update metadata (passed by newer AppImages)
    update_url = sys.argv[4] if len(sys.argv) > 4 else ""
    version = sys.argv[5] if len(sys.argv) > 5 else ""
    update_pattern = sys.argv[6] if len(sys.argv) > 6 else ""
    
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

    last_known_path, last_known_version = read_marker_file(marker_file)

    # Determine if we need to integrate/update
    force_update = False
    version_only_update = False

    if last_known_path is None:
        # First time integration
        force_update = True
    elif last_known_path != appimage_path:
        # Path changed, need to update
        force_update = True
    elif last_known_version != version and version:
        # Only version changed, just update marker file
        version_only_update = True

    # If only version changed, just update the marker file
    if version_only_update and not force_update:
        write_marker_file(marker_file, appimage_path, desktop_filename,
                         update_url, version, update_pattern)
        result = 0  # Success
    else:
        # Perform integration for THIS AppImage
        result = integrate_appimage(
            app_name,
            appimage_path,
            desktop_file_path,
            icon_file,
            force_update=force_update
        )

        # Update marker file if integration was successful
        if result == 0:
            write_marker_file(marker_file, appimage_path, desktop_filename,
                             update_url, version, update_pattern)
    
    # --- COLLABORATIVE CLEANUP ---
    # Clean up orphaned integrations from OTHER AppImages
    try:
        removed_count = cleanup_orphaned_integrations()
        if removed_count > 0:
            print(f"Cleaned up {removed_count} orphaned AppImage integration(s)", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Collaborative cleanup failed: {e}", file=sys.stderr)
    
    # --- SYSTEMD SETUP ---
    # Try to set up systemd timer (only runs once, safe to call multiple times)
    try:
        if setup_systemd_watcher():
            print("Systemd automatic cleanup timer enabled", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Systemd setup failed: {e}", file=sys.stderr)
    
    sys.exit(0)


if __name__ == "__main__":
    if os.environ.get("APPDIR"):
        main()
