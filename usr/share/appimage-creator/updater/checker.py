#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Update checker - verifies if new AppImage versions are available
"""

import json
import urllib.request
import urllib.error
import os
from pathlib import Path
from typing import Optional, Dict, Any
import fnmatch

# Optional GitHub token to increase rate limit from 60 to 5000 requests/hour
# Set environment variable GITHUB_TOKEN to use a personal token
# Token should have NO permissions (read-only access to public repos only)
DEFAULT_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", None)


class UpdateInfo:
    """Information about an available update"""

    def __init__(self, version: str, download_url: str, release_notes: str = ""):
        self.version = version
        self.download_url = download_url
        self.release_notes = release_notes


class UpdateChecker:
    """Checks for AppImage updates from various sources"""

    def __init__(self, update_url: str, current_version: str, filename_pattern: str):
        """
        Initialize update checker

        Args:
            update_url: URL to check for updates (GitHub API, custom JSON, etc.)
            current_version: Current version of the AppImage
            filename_pattern: Pattern to match AppImage files (e.g., "app-*-x86_64.AppImage")
        """
        self.update_url = update_url
        self.current_version = current_version
        self.filename_pattern = filename_pattern
        self.github_token = self._load_github_token()

    @staticmethod
    def _load_github_token() -> Optional[str]:
        """
        Load GitHub token from environment, config file, or use shared default

        Priority:
        1. GITHUB_TOKEN environment variable (custom token)
        2. ~/.config/appimage-creator/github_token file (custom token)
        3. DEFAULT_GITHUB_TOKEN (shared public token - safe, no scopes)

        Returns:
            GitHub token (always returns a token)
        """
        # Try environment variable first (for advanced users)
        token = os.environ.get('GITHUB_TOKEN')
        if token:
            return token.strip()

        # Try config file (for advanced users)
        config_file = Path.home() / ".config/appimage-creator/github_token"
        if config_file.exists():
            try:
                token = config_file.read_text().strip()
                if token:
                    return token
            except Exception:
                pass

        # Use shared token for all users (default behavior)
        # This token has NO scopes - it's safe and public
        # Provides 5000 req/hour instead of 60 req/hour
        return DEFAULT_GITHUB_TOKEN

    def check_for_update(self) -> Optional[UpdateInfo]:
        """
        Check if an update is available

        Returns:
            UpdateInfo if update is available, None otherwise
        """
        if not self.update_url:
            return None

        try:
            # Detect source type from URL
            if "api.github.com" in self.update_url and "/releases/latest" in self.update_url:
                return self._check_github_releases()
            else:
                # Try generic JSON format
                return self._check_generic_json()
        except Exception as e:
            print(f"Update check failed: {e}")
            return None


    def _extract_version_from_tag(self, tag_name: str) -> str:
        """
        Extract version from tag using the filename pattern.
        
        Example:
            Pattern: "app-*-x86_64.AppImage"
            Tag: "app-1.2.3-x86_64" or "v1.2.3"
            Returns: "1.2.3"
        """
        import re
        
        # Remove 'v' prefix if present
        tag = tag_name.lstrip('v')
        
        # Remove .AppImage suffix from pattern for matching with tag
        pattern_base = self.filename_pattern.replace('.AppImage', '')
        
        # Convert glob pattern to regex: replace * with (.+)
        # Escape other special regex chars first
        regex_pattern = re.escape(pattern_base).replace(r'\*', '(.+)')
        
        # Try to match the tag against the pattern
        match = re.match(f'^{regex_pattern}$', tag)
        if match:
            return match.group(1)
        
        # Fallback: if tag doesn't match pattern, try to extract version-like substring
        # Look for patterns like: 26.01.12-2122, 1.2.3, v1.0
        version_match = re.search(r'(\d+\.\d+[\.\d\-]*)', tag)
        if version_match:
            return version_match.group(1)
        
        # Last resort: return tag as-is
        return tag

    def _check_github_releases(self) -> Optional[UpdateInfo]:
        """Check GitHub releases API"""
        try:
            req = urllib.request.Request(self.update_url)
            req.add_header('Accept', 'application/vnd.github.v3+json')
            req.add_header('User-Agent', 'AppImage-Updater/1.0')

            # Add authorization header if token is available
            if self.github_token:
                req.add_header('Authorization', f'token {self.github_token}')

            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            # Extract version from tag_name using smart extraction
            tag_name = data.get('tag_name', '')
            version = self._extract_version_from_tag(tag_name)

            # Check if version is newer
            if not self._is_newer_version(version):
                return None

            # Find matching AppImage asset
            assets = data.get('assets', [])
            for asset in assets:
                filename = asset.get('name', '')
                if fnmatch.fnmatch(filename, self.filename_pattern):
                    download_url = asset.get('browser_download_url', '')
                    release_notes = data.get('body', '')

                    return UpdateInfo(
                        version=version,
                        download_url=download_url,
                        release_notes=release_notes
                    )

            return None

        except urllib.error.URLError as e:
            print(f"Network error checking for updates: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Invalid JSON response: {e}")
            return None

    def _check_generic_json(self) -> Optional[UpdateInfo]:
        """
        Check generic JSON endpoint
        Expected format:
        {
            "version": "1.2.3",
            "download_url": "https://...",
            "release_notes": "..."
        }
        """
        try:
            with urllib.request.urlopen(self.update_url, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            version = data.get('version', '')
            download_url = data.get('download_url', '')
            release_notes = data.get('release_notes', '')

            if not version or not download_url:
                return None

            if not self._is_newer_version(version):
                return None

            return UpdateInfo(
                version=version,
                download_url=download_url,
                release_notes=release_notes
            )

        except Exception as e:
            print(f"Error checking generic JSON: {e}")
            return None

    def _is_newer_version(self, new_version: str) -> bool:
        """
        Compare version strings
        Simple comparison: handles formats like "1.2.3", "25.11.01-1756"
        """
        try:
            # Remove common prefixes
            new_ver = new_version.lstrip('v')
            curr_ver = self.current_version.lstrip('v')

            # Simple string comparison for now
            # For more complex versioning, use packaging.version
            return new_ver > curr_ver

        except Exception:
            return False


def check_appimage_update(marker_file_path: Path) -> Optional[UpdateInfo]:
    """
    Check for updates based on marker file

    Args:
        marker_file_path: Path to the .path marker file

    Returns:
        UpdateInfo if update available, None otherwise
    """
    try:
        if not marker_file_path.exists():
            return None

        lines = marker_file_path.read_text().strip().split('\n')

        # Format: line 1: appimage path, line 2: desktop file
        # line 3: update URL, line 4: version, line 5: pattern
        if len(lines) < 5:
            return None  # No update info

        update_url = lines[2]
        current_version = lines[3]
        filename_pattern = lines[4]

        if not update_url:
            return None

        checker = UpdateChecker(update_url, current_version, filename_pattern)
        return checker.check_for_update()

    except Exception as e:
        print(f"Error reading marker file: {e}")
        return None
