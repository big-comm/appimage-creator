#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check all installed AppImages for updates
Called periodically by systemd timer
"""

import os
import locale

# Fix for systemd/cron environments where LANG might be missing
if os.environ.get('LANG', 'C') == 'C' or not os.environ.get('LANG'):
    try:
        # Try to read system-wide locale configuration
        locale_conf = '/etc/locale.conf'
        if os.path.isfile(locale_conf):
            with open(locale_conf, 'r') as f:
                for line in f:
                    if line.strip().startswith('LANG='):
                        lang_val = line.strip().split('=')[1].strip('"').strip("'")
                        if lang_val:
                            os.environ['LANG'] = lang_val
                            os.environ['LC_ALL'] = lang_val
                            # GTK uses LANGUAGE priority, this is CRITICAL
                            os.environ['LANGUAGE'] = lang_val.split('.')[0]
                        break
    except Exception:
        pass

try:
    locale.setlocale(locale.LC_ALL, '')
except:
    pass
import sys
import time
from pathlib import Path

try:
    from updater.checker import check_appimage_update
    from updater.update_window import show_update_notification
    from updater.downloader import AppImageDownloader
except ImportError:
    from checker import check_appimage_update
    from update_window import show_update_notification
    from downloader import AppImageDownloader

# Minimum time (in seconds) to wait after integration before showing update notification
# This gives the AppImage time to complete integration and the main app to open
INTEGRATION_GRACE_PERIOD = 30


def complete_pending_updates():
    """Complete any pending AppImage updates"""
    marker_dir = Path.home() / ".local/share/appimage-integrations"

    if not marker_dir.exists():
        return

    for marker_file in marker_dir.glob("*.path"):
        try:
            lines = marker_file.read_text().strip().split('\n')
            if len(lines) < 1:
                continue

            appimage_path = Path(lines[0])

            # Try to complete pending update
            if AppImageDownloader.complete_pending_update(appimage_path):
                app_name = marker_file.stem.replace('_', ' ')
                print(f"Completed pending update for {app_name}")

                # Update marker file version if update completed
                new_version_marker = Path(str(appimage_path) + ".new.version")
                if new_version_marker.exists():
                    new_version = new_version_marker.read_text().strip()
                    AppImageDownloader.update_marker_file(marker_file, new_version)
                    new_version_marker.unlink()

        except Exception as e:
            print(f"Error completing update for {marker_file}: {e}")
            continue


def check_all_appimages():
    """Check all integrated AppImages for updates"""
    # First, complete any pending updates
    complete_pending_updates()

    marker_dir = Path.home() / ".local/share/appimage-integrations"

    if not marker_dir.exists():
        return

    for marker_file in marker_dir.glob("*.path"):
        try:
            # Check if marker file was recently created/modified (integration just happened)
            marker_age = time.time() - marker_file.stat().st_mtime

            if marker_age < INTEGRATION_GRACE_PERIOD:
                # Skip this check - integration is too recent
                # Give the AppImage time to complete integration and open the main app
                print(f"Skipping update check for {marker_file.stem} (recently integrated, waiting {INTEGRATION_GRACE_PERIOD - marker_age:.0f}s)")
                continue

            # Check if update is available
            update_info = check_appimage_update(marker_file)

            if update_info:
                # Read marker file to get info
                lines = marker_file.read_text().strip().split('\n')

                if len(lines) < 5:
                    continue

                appimage_path = Path(lines[0])
                app_name = marker_file.stem.replace('_', ' ')
                current_version = lines[3]
                filename_pattern = lines[4] if len(lines) >= 5 else ""

                # Only show if in graphical environment
                if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                    print(f"Update available for {app_name}: {current_version} -> {update_info.version}")
                    continue

                # Show update window
                print(f"Showing update notification for {app_name}")
                show_update_notification(
                    app_name,
                    update_info,
                    current_version,
                    appimage_path,
                    marker_file,
                    filename_pattern
                )

                # Only show one update at a time
                break

        except Exception as e:
            print(f"Error checking {marker_file}: {e}")
            continue


def main():
    """Main entry point"""
    check_all_appimages()


if __name__ == "__main__":
    main()
