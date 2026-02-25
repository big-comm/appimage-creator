"""
Manages application settings using a JSON file.
"""

import json
from pathlib import Path
from typing import Any


class SettingsManager:
    """Handles loading and saving application settings to a JSON file."""

    def __init__(self, app_name: str = "appimage-creator"):
        # Get the standard config directory path (e.g., ~/.config/appimage-creator)
        config_dir = Path.home() / ".config" / app_name
        config_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = config_dir / "settings.json"
        self.settings: dict[str, Any] = {}
        self._load()

    def _get_defaults(self) -> dict:
        """Returns the default settings."""
        return {
            "last-chooser-directory": str(Path.home()),
            "window-width": 820,
            "window-height": 720,
        }

    def _load(self):
        """Loads settings from the JSON file."""
        try:
            with open(self.settings_path, "r") as f:
                self.settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If file doesn't exist or is corrupted, start with defaults
            self.settings = self._get_defaults()
            self._save()

    def _save(self):
        """Saves the current settings to the JSON file."""
        try:
            with open(self.settings_path, "w") as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Warning: Could not save settings to {self.settings_path}: {e}")

    def get(self, key: str) -> Any:
        """Gets a setting value by key, falling back to default if not found."""
        return self.settings.get(key, self._get_defaults().get(key))

    def set(self, key: str, value: Any) -> None:
        """Sets a setting value by key and saves the file."""
        self.settings[key] = value
        self._save()


class LibraryProfileManager:
    """Manages reusable library profiles for AppImage builds.

    Profiles are stored as JSON files under
    ~/.config/appimage-creator/profiles/<app_type>.json
    Each profile associates an application type with a list of extra
    library patterns the user has specified for that type.
    """

    def __init__(self, app_name: str = "appimage-creator"):
        self.profiles_dir = Path.home() / ".config" / app_name / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _profile_path(self, app_type: str) -> Path:
        safe_name = app_type.replace("/", "_").replace("\\", "_")
        return self.profiles_dir / f"{safe_name}.json"

    def load(self, app_type: str) -> list[str]:
        """Load saved extra library patterns for an app type."""
        path = self._profile_path(app_type)
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return data.get("extra_libraries", [])
        except (json.JSONDecodeError, IOError):
            return []

    def save(self, app_type: str, extra_libs: list[str]) -> None:
        """Save extra library patterns for an app type."""
        path = self._profile_path(app_type)
        try:
            with open(path, "w") as f:
                json.dump(
                    {"app_type": app_type, "extra_libraries": extra_libs}, f, indent=2
                )
        except IOError:
            pass

    def list_profiles(self) -> list[str]:
        """Return list of app types that have saved profiles."""
        profiles = []
        for p in self.profiles_dir.glob("*.json"):
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                profiles.append(data.get("app_type", p.stem))
            except (json.JSONDecodeError, IOError):
                profiles.append(p.stem)
        return sorted(profiles)
