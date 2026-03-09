#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AppImage Integration Cleanup Script
Used by systemd to automatically clean up orphaned AppImage integrations
Can also be run manually for maintenance
"""

import os
import sys
import subprocess
from pathlib import Path
import time

# For update checking
UPDATE_CHECK_INTERVAL = 60  # Check for updates every minute (in seconds) - DEBUG MODE
LAST_CHECK_FILE = Path.home() / ".local/share/appimage-integrations/.last_update_check"


def cleanup_orphaned_integrations():
    """
    Check all integrated AppImages and remove orphaned ones.
    An integration is considered orphaned if the AppImage file no longer exists.

    Returns:
        int: Number of orphaned integrations removed
    """
    marker_dir = Path.home() / ".local/share/appimage-integrations"

    if not marker_dir.exists():
        print("No AppImage integrations found")
        return 0

    removed_count = 0
    checked_count = 0

    for marker_file in marker_dir.glob("*.path"):
        checked_count += 1
        try:
            # Read marker file (format: line 1 = appimage path, line 2 = desktop filename)
            lines = marker_file.read_text().strip().split("\n")
            appimage_path = lines[0]
            desktop_filename = (
                lines[1] if len(lines) > 1 else f"{marker_file.stem}.desktop"
            )

            app_name = marker_file.stem

            # Check if AppImage still exists
            if not Path(appimage_path).exists():
                print(f"Cleaning orphaned integration: {app_name}")
                print(f"  Missing AppImage: {appimage_path}")

                # Remove desktop file using the stored filename
                desktop_file = (
                    Path.home() / ".local/share/applications" / desktop_filename
                )

                # Read icon name from desktop file before removing it
                icon_name = app_name  # fallback
                if desktop_file.exists():
                    try:
                        import configparser

                        cfg = configparser.ConfigParser()
                        cfg.read(desktop_file)
                        icon_name = cfg.get("Desktop Entry", "Icon", fallback=app_name)
                        icon_name = Path(icon_name).stem
                    except Exception:
                        pass
                    desktop_file.unlink()
                    print(f"  ✓ Removed desktop file: {desktop_filename}")

                # Remove icon files from all hicolor directories
                hicolor_base = Path.home() / ".local/share/icons/hicolor"
                icon_count = 0
                if hicolor_base.exists():
                    desktop_base = desktop_filename.replace(".desktop", "")
                    # Search all size directories for matching icons
                    for size_dir in hicolor_base.iterdir():
                        apps_dir = size_dir / "apps"
                        if not apps_dir.exists():
                            continue
                        for pattern in (icon_name, app_name, desktop_base):
                            for icon in apps_dir.glob(f"{pattern}.*"):
                                icon.unlink()
                                icon_count += 1
                if icon_count > 0:
                    print(f"  ✓ Removed {icon_count} icon(s)")

                # Remove marker file
                marker_file.unlink()
                print("  ✓ Removed marker file")

                removed_count += 1
            else:
                print(f"Valid integration: {app_name}")

        except Exception as e:
            print(f"Error processing {marker_file}: {e}", file=sys.stderr)

    print(
        f"\nChecked {checked_count} integration(s), removed {removed_count} orphaned integration(s)"
    )

    # Also clean desktop files that reference missing AppImages without marker files
    extra_removed = _cleanup_orphaned_desktop_files()
    if extra_removed > 0:
        print(
            f"Also removed {extra_removed} desktop file(s) referencing missing AppImages"
        )
        removed_count += extra_removed

    if removed_count > 0:
        # Update desktop database
        try:
            print("Updating desktop database...")
            subprocess.run(
                [
                    "update-desktop-database",
                    str(Path.home() / ".local/share/applications"),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            print("✓ Desktop database updated")
        except Exception as e:
            print(f"Warning: Failed to update desktop database: {e}", file=sys.stderr)

        # Update icon cache so removed icons are no longer referenced
        # Without this, the stale cache prevents fallback to system icons
        try:
            hicolor_dir = Path.home() / ".local/share/icons/hicolor"
            if hicolor_dir.exists():
                print("Updating icon cache...")
                subprocess.run(
                    ["gtk-update-icon-cache", "-f", "-t", str(hicolor_dir)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                print("✓ Icon cache updated")
        except Exception as e:
            print(f"Warning: Failed to update icon cache: {e}", file=sys.stderr)

    # Auto-disable systemd watcher if no integrations remain
    if checked_count == removed_count and removed_count > 0:
        print("\nAll integrations removed. Cleaning up update system...")
        try:
            # Disable and remove systemd timer
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "appimage-cleaner.timer"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            print("✓ Systemd watcher disabled")

            # Remove systemd files
            systemd_dir = Path.home() / ".config/systemd/user"
            timer_file = systemd_dir / "appimage-cleaner.timer"
            service_file = systemd_dir / "appimage-cleaner.service"

            if timer_file.exists():
                timer_file.unlink()
                print("✓ Removed systemd timer file")
            if service_file.exists():
                service_file.unlink()
                print("✓ Removed systemd service file")

            # Reload systemd
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

            # Remove updater module
            bin_dir = Path.home() / ".local/bin"
            updater_dir = bin_dir / "updater"
            if updater_dir.exists():
                import shutil

                shutil.rmtree(updater_dir)
                print("✓ Removed updater module")

            # Remove translation files
            try:
                user_locale_dir = Path.home() / ".local/share/locale"
                if user_locale_dir.exists():
                    removed_mo_count = 0
                    for mo_file in user_locale_dir.glob(
                        "*/LC_MESSAGES/appimage-updater.mo"
                    ):
                        mo_file.unlink()
                        removed_mo_count += 1
                        # Try to remove empty parent directories
                        try:
                            mo_file.parent.rmdir()  # LC_MESSAGES
                            mo_file.parent.parent.rmdir()  # lang dir
                        except OSError:
                            pass  # Directory not empty
                    if removed_mo_count > 0:
                        print(f"✓ Removed {removed_mo_count} translation files")
            except Exception:
                pass

            # Remove updater .desktop file and icon
            try:
                updater_desktop = (
                    Path.home()
                    / ".local/share/applications/org.bigcommunity.appimage.updater.desktop"
                )
                if updater_desktop.exists():
                    updater_desktop.unlink()
                    print("✓ Removed updater .desktop file")

                updater_icon = (
                    Path.home()
                    / ".local/share/icons/hicolor/scalable/apps/appimage-update.svg"
                )
                if updater_icon.exists():
                    updater_icon.unlink()
                    print("✓ Removed updater icon")
            except Exception:
                pass

            # Remove cleanup script (this script itself)
            cleanup_script = bin_dir / "appimage-cleanup.py"
            if cleanup_script.exists():
                cleanup_script.unlink()
                print("✓ Removed cleanup script")

            print("\n✓ All AppImage update system files removed")

        except Exception as e:
            print(f"Warning: Cleanup failed: {e}", file=sys.stderr)

    return removed_count


def _cleanup_orphaned_desktop_files():
    """Scan desktop files for references to missing AppImages and clean them up."""
    import configparser
    import re

    apps_dir = Path.home() / ".local/share/applications"
    if not apps_dir.exists():
        return 0

    removed = 0
    for desktop_file in apps_dir.glob("*.desktop"):
        try:
            content = desktop_file.read_text()
            # Look for Exec= referencing an .AppImage file
            match = re.search(
                r'^Exec="?([^"\n]+\.AppImage)"?\s',
                content,
                flags=re.MULTILINE | re.IGNORECASE,
            )
            if not match:
                continue

            appimage_path = match.group(1).strip()
            if Path(appimage_path).exists():
                continue

            # AppImage no longer exists — read Icon= and remove everything
            cfg = configparser.ConfigParser()
            cfg.read(desktop_file)
            icon_name = cfg.get("Desktop Entry", "Icon", fallback="")
            if icon_name:
                icon_name = Path(icon_name).stem

            # Remove icons
            if icon_name:
                hicolor_base = Path.home() / ".local/share/icons/hicolor"
                if hicolor_base.exists():
                    icon_count = 0
                    for size_dir in hicolor_base.iterdir():
                        icons_sub = size_dir / "apps"
                        if icons_sub.exists():
                            for icon in icons_sub.glob(f"{icon_name}.*"):
                                icon.unlink()
                                icon_count += 1
                    if icon_count > 0:
                        print(
                            f"  ✓ Removed {icon_count} orphaned icon(s) for {icon_name}"
                        )

            desktop_file.unlink()
            print(f"  ✓ Removed orphaned desktop file: {desktop_file.name}")
            removed += 1
        except Exception as e:
            print(f"Error scanning {desktop_file}: {e}", file=sys.stderr)

    return removed


def should_check_for_updates():
    """Check if it's time to check for updates"""
    try:
        if not LAST_CHECK_FILE.exists():
            return True

        last_check = LAST_CHECK_FILE.stat().st_mtime
        current_time = time.time()

        return (current_time - last_check) >= UPDATE_CHECK_INTERVAL

    except Exception:
        return True


def check_for_updates():
    """Check for AppImage updates"""
    try:
        # DEBUG: Print environment info
        display = os.environ.get("DISPLAY")
        wayland = os.environ.get("WAYLAND_DISPLAY")
        print(f"[DEBUG] DISPLAY={display}, WAYLAND_DISPLAY={wayland}", file=sys.stderr)

        # Only check if we're in a graphical environment
        if not (display or wayland):
            print(
                "[DEBUG] No graphical environment detected, skipping update check",
                file=sys.stderr,
            )
            return

        print("[DEBUG] Checking if should check for updates...", file=sys.stderr)
        if not should_check_for_updates():
            print(
                f"[DEBUG] Not time to check yet (interval: {UPDATE_CHECK_INTERVAL}s)",
                file=sys.stderr,
            )
            return

        print("Checking for AppImage updates...")

        # Try to import updater module
        # This will work if running from an AppImage with updater embedded
        sys.path.insert(0, str(Path.home() / ".local/bin"))

        try:
            # Check if updater module exists
            marker_dir = Path.home() / ".local/share/appimage-integrations"

            if not marker_dir.exists():
                print("[DEBUG] Marker dir doesn't exist", file=sys.stderr)
                return

            # Import check function
            print("[DEBUG] Attempting to import updater module...", file=sys.stderr)
            from updater.check_updates import check_all_appimages

            print("[DEBUG] Running check_all_appimages()...", file=sys.stderr)
            # Run update check
            check_all_appimages()

            # Update last check time
            LAST_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAST_CHECK_FILE.touch()

            print("✓ Update check complete")

        except ImportError as e:
            # Updater module not available
            print(f"[DEBUG] ImportError: {e}", file=sys.stderr)
            pass

    except Exception as e:
        print(f"Update check failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)


def main():
    """Main entry point"""
    print("=" * 60)
    print("AppImage Integration Cleanup")
    print("=" * 60)

    try:
        # Clean up orphaned integrations
        removed = cleanup_orphaned_integrations()

        if removed == 0:
            print("\n✓ All integrations are valid, nothing to clean up")
        else:
            print(f"\n✓ Cleanup complete: {removed} orphaned integration(s) removed")

        # Check for updates (if it's time)
        check_for_updates()

        sys.exit(0)

    except Exception as e:
        print(f"\n✗ Cleanup failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
