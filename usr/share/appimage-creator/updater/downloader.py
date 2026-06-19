#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AppImage downloader and installer
"""

import os
import urllib.request
import urllib.error
import tempfile
import shutil
from pathlib import Path
from typing import Callable, Optional


class DownloadProgress:
    """Progress callback for downloads"""

    def __init__(self, callback: Optional[Callable[[int, int], None]] = None):
        """
        Args:
            callback: Function(bytes_downloaded, total_bytes) called during download
        """
        self.callback = callback
        self.downloaded = 0

    def update(self, block_count: int, block_size: int, total_size: int):
        """Called by urllib during download"""
        self.downloaded = block_count * block_size
        if self.callback:
            self.callback(self.downloaded, total_size)


class AppImageDownloader:
    """Downloads and installs AppImage updates"""

    @staticmethod
    def download_update(
        download_url: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        target_filename: Optional[str] = None,
        target_directory: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Download new AppImage to specified location

        Args:
            download_url: URL to download from
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            target_filename: Optional custom filename (uses URL filename if not provided)
            target_directory: Optional target directory (uses temp dir if not provided)

        Returns:
            Path to downloaded file, or None on error
        """
        # Only allow HTTPS downloads to avoid unauthenticated/tampered binaries
        if not isinstance(download_url, str) or not download_url.startswith("https://"):
            print(f"Refusing non-HTTPS download URL: {download_url}")
            return None

        part_file = None
        try:
            # Determine filename
            if target_filename:
                filename = target_filename
            else:
                filename = download_url.split("/")[-1]

            # Determine target directory
            if target_directory:
                download_dir = Path(target_directory)
            else:
                download_dir = Path(tempfile.gettempdir()) / "appimage-updates"

            download_dir.mkdir(parents=True, exist_ok=True)
            target_file = download_dir / filename
            # Download to a temporary .part file first, then atomically replace
            part_file = download_dir / (filename + ".part")

            req = urllib.request.Request(
                download_url, headers={"User-Agent": "AppImage-Updater/1.0"}
            )

            downloaded = 0
            with urllib.request.urlopen(req, timeout=30) as response:
                # Content-Length may be absent on some redirects
                length_header = response.headers.get("Content-Length")
                total_size = int(length_header) if length_header else 0

                with open(part_file, "wb") as out:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            # Integrity check: must not be empty, and must match Content-Length
            if downloaded == 0:
                print("Download failed: received 0 bytes")
                part_file.unlink(missing_ok=True)
                return None
            if total_size and downloaded != total_size:
                print(
                    f"Download incomplete: got {downloaded} of {total_size} bytes"
                )
                part_file.unlink(missing_ok=True)
                return None

            # Atomically move the verified file into place
            os.replace(str(part_file), str(target_file))

            # Make executable
            target_file.chmod(0o755)

            return target_file

        except urllib.error.URLError as e:
            print(f"Download failed: {e}")
            if part_file is not None:
                part_file.unlink(missing_ok=True)
            return None
        except Exception as e:
            print(f"Error downloading update: {e}")
            if part_file is not None:
                part_file.unlink(missing_ok=True)
            return None

    @staticmethod
    def install_update(
        old_path: Path, new_path: Path, new_version: Optional[str] = None
    ) -> bool:
        """
        Replace old AppImage with new one

        Strategy: Since the AppImage might be running, we:
        1. Move new version to .new file next to the original
        2. Create update script that will replace on next launch
        3. On next app start, check for .new and complete the update

        Args:
            old_path: Path to current AppImage
            new_path: Path to downloaded AppImage
            new_version: Optional version string; when provided, a "<path>.new.version"
                marker is written so a deferred update can update the marker file later.

        Returns:
            True on success, False on error
        """
        backup_path = None
        try:
            # Target for new version (next to original)
            new_version_path = Path(str(old_path) + ".new")

            # Move downloaded file to .new location
            shutil.move(str(new_path), str(new_version_path))

            # Record the staged version so complete_pending_update can update the
            # marker file on next launch (avoids re-detecting the same update).
            if new_version:
                try:
                    Path(str(old_path) + ".new.version").write_text(new_version)
                except Exception:
                    pass

            # Make executable
            new_version_path.chmod(0o755)

            # Try to replace immediately (works if AppImage is not running)
            try:
                # Create backup
                backup_path = Path(str(old_path) + ".backup")
                if old_path.exists():
                    shutil.copy2(old_path, backup_path)

                # Try to replace (this will fail if file is in use)
                shutil.move(str(new_version_path), str(old_path))

                # Make executable
                old_path.chmod(0o755)

                # Remove backup if successful
                if backup_path.exists():
                    backup_path.unlink()

                # Update completed immediately; the deferred version marker is moot
                Path(str(old_path) + ".new.version").unlink(missing_ok=True)

                return True

            except (PermissionError, OSError) as e:
                # File is in use or permission denied
                # The .new file is already in place for next launch
                print(f"Cannot replace running AppImage: {e}")
                print(f"Update staged at: {new_version_path}")
                print("Update will complete on next application launch")

                # Restore from backup if we made one
                if backup_path and backup_path.exists() and not old_path.exists():
                    shutil.move(str(backup_path), str(old_path))

                # Clean up backup
                if backup_path and backup_path.exists():
                    backup_path.unlink()

                # Return True because .new file is ready
                # The update will complete on next launch
                return True

        except Exception as e:
            print(f"Installation failed: {e}")

            # Restore backup if exists
            if backup_path and backup_path.exists() and not old_path.exists():
                try:
                    shutil.move(str(backup_path), str(old_path))
                except Exception:
                    pass

            return False

    @staticmethod
    def complete_pending_update(appimage_path: Path) -> bool:
        """
        Complete a pending update if .new file exists
        Should be called at application startup

        Args:
            appimage_path: Path to current AppImage

        Returns:
            True if update was completed, False otherwise
        """
        try:
            new_version_path = Path(str(appimage_path) + ".new")

            # Check if pending update exists
            if not new_version_path.exists():
                return False

            print(f"Completing pending update from: {new_version_path}")

            # Create backup of current version
            backup_path = Path(str(appimage_path) + ".old")
            if appimage_path.exists():
                shutil.move(str(appimage_path), str(backup_path))

            # Move new version into place
            shutil.move(str(new_version_path), str(appimage_path))

            # Make executable
            appimage_path.chmod(0o755)

            # Remove old backup
            if backup_path.exists():
                try:
                    backup_path.unlink()
                except Exception:
                    pass  # Not critical if cleanup fails

            print("Update completed successfully!")
            return True

        except Exception as e:
            print(f"Failed to complete pending update: {e}")

            # Try to restore from backup
            backup_path = Path(str(appimage_path) + ".old")
            if backup_path.exists() and not appimage_path.exists():
                try:
                    shutil.move(str(backup_path), str(appimage_path))
                except Exception:
                    pass

            return False

    @staticmethod
    def update_marker_file(marker_file: Path, new_version: str):
        """
        Update marker file with new version

        Args:
            marker_file: Path to marker file
            new_version: New version string
        """
        try:
            if not marker_file.exists():
                return

            lines = marker_file.read_text().strip().split("\n")

            # Update version (line 4)
            if len(lines) >= 4:
                lines[3] = new_version
                marker_file.write_text("\n".join(lines))

        except Exception as e:
            print(f"Failed to update marker file: {e}")
