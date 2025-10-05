"""
Manages application settings using a JSON file.
"""

import os
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
        self.settings = {}
        self._load()

    def _get_defaults(self) -> dict:
        """Returns the default settings."""
        return {
            'last-chooser-directory': str(Path.home())
        }

    def _load(self):
        """Loads settings from the JSON file."""
        try:
            with open(self.settings_path, 'r') as f:
                self.settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If file doesn't exist or is corrupted, start with defaults
            self.settings = self._get_defaults()
            self._save()

    def _save(self):
        """Saves the current settings to the JSON file."""
        try:
            with open(self.settings_path, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Warning: Could not save settings to {self.settings_path}: {e}")

    def get(self, key: str) -> Any:
        """Gets a setting value by key, falling back to default if not found."""
        return self.settings.get(key, self._get_defaults().get(key))

    def set(self, key: str, value: Any):
        """Sets a setting value by key and saves the file."""
        self.settings[key] = value
        self._save()