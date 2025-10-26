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
            lines = marker_file.read_text().strip().split('\n')
            appimage_path = lines[0]
            desktop_filename = lines[1] if len(lines) > 1 else f"{marker_file.stem}.desktop"
            
            app_name = marker_file.stem
            
            # Check if AppImage still exists
            if not Path(appimage_path).exists():
                print(f"Cleaning orphaned integration: {app_name}")
                print(f"  Missing AppImage: {appimage_path}")
                
                # Remove desktop file using the stored filename
                desktop_file = Path.home() / ".local/share/applications" / desktop_filename
                if desktop_file.exists():
                    desktop_file.unlink()
                    print(f"  ✓ Removed desktop file: {desktop_filename}")
                
                # Remove icon files (can be .svg, .png, .xpm, etc)
                icon_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
                if icon_dir.exists():
                    icon_count = 0
                    for icon in icon_dir.glob(f"{app_name}.*"):
                        icon.unlink()
                        icon_count += 1
                    # Also try to remove icons matching desktop file base name
                    desktop_base = desktop_filename.replace('.desktop', '')
                    for icon in icon_dir.glob(f"{desktop_base}.*"):
                        icon.unlink()
                        icon_count += 1
                    if icon_count > 0:
                        print(f"  ✓ Removed {icon_count} icon(s)")
                
                # Remove marker file
                marker_file.unlink()
                print(f"  ✓ Removed marker file")
                
                removed_count += 1
            else:
                print(f"Valid integration: {app_name}")
                
        except Exception as e:
            print(f"Error processing {marker_file}: {e}", file=sys.stderr)
    
    print(f"\nChecked {checked_count} integration(s), removed {removed_count} orphaned integration(s)")
    
    if removed_count > 0:
        # Update desktop database
        try:
            print("Updating desktop database...")
            subprocess.run(
                ["update-desktop-database", str(Path.home() / ".local/share/applications")],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            print("✓ Desktop database updated")
        except Exception as e:
            print(f"Warning: Failed to update desktop database: {e}", file=sys.stderr)
    
    # Auto-disable systemd watcher if no integrations remain
    if checked_count == removed_count and removed_count > 0:
        print("\nAll integrations removed. Disabling systemd watcher...")
        try:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "appimage-cleaner.timer"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            print("✓ Systemd watcher disabled")
        except Exception:
            pass
    
    return removed_count


def main():
    """Main entry point"""
    print("=" * 60)
    print("AppImage Integration Cleanup")
    print("=" * 60)
    
    try:
        removed = cleanup_orphaned_integrations()
        
        if removed == 0:
            print("\n✓ All integrations are valid, nothing to clean up")
            sys.exit(0)
        else:
            print(f"\n✓ Cleanup complete: {removed} orphaned integration(s) removed")
            sys.exit(0)
            
    except Exception as e:
        print(f"\n✗ Cleanup failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
