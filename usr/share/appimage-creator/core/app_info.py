"""
Application information data class
"""

import copy
from dataclasses import dataclass, field


@dataclass
class AppInfo:
    """Encapsulates application information for AppImage creation"""

    # Required fields
    name: str = ""
    version: str = "1.0.0"
    executable: str = ""

    # Optional basic info
    description: str = ""
    authors: list[str] = field(default_factory=lambda: ["Unknown"])
    websites: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=lambda: ["Utility"])

    # Application type and settings
    app_type: str = "binary"
    executable_name: str = ""
    terminal: bool = False

    # Files and resources
    icon: str | None = None
    additional_directories: list[str] = field(default_factory=list)
    additional_files: list[str] = field(default_factory=list)

    # Desktop file options
    use_existing_desktop: bool = False
    detected_desktop_file: str | None = None
    custom_desktop_file: str | None = None

    # Analysis data
    structure_analysis: dict | None = None
    wrapper_analysis: dict | None = None

    # Build options
    output_dir: str | None = None
    include_dependencies: bool = True
    selected_dependencies: list[str] = field(default_factory=list)
    extra_libraries: list[str] = field(default_factory=list)
    strip_binaries: bool = False
    build_environment: str | None = None

    # Icon theme options
    include_icon_theme: bool = False
    icon_theme_choice: str = "papirus"

    # Auto-update options
    update_url: str = ""
    update_pattern: str = ""

    # Desktop file metadata
    keywords: list[str] = field(default_factory=list)
    mime_types: list[str] = field(default_factory=list)

    # Dynamic build-time fields
    canonical_basename: str = ""
    python_version: str = ""
    apprun_executable: str = ""
    apprun_argument: str | None = None

    # Compatibility properties
    @property
    def author(self) -> str:
        """Return first author for backward compatibility"""
        return self.authors[0] if self.authors else "Unknown"

    @property
    def website(self) -> str:
        """Return first website for backward compatibility"""
        return self.websites[0] if self.websites else ""

    def copy(self) -> "AppInfo":
        """Return a shallow copy of this AppInfo instance."""
        return copy.copy(self)
