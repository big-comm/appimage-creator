"""
Application information data class
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class AppInfo:
    """Encapsulates application information for AppImage creation"""
    
    # Required fields
    name: str = ""
    version: str = "1.0.0"
    executable: str = ""
    
    # Optional basic info
    description: str = ""
    authors: List[str] = field(default_factory=lambda: ["Unknown"])
    websites: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=lambda: ["Utility"])
    
    # Application type and settings
    app_type: str = "binary"
    executable_name: str = ""
    terminal: bool = False
    
    # Files and resources
    icon: Optional[str] = None
    additional_directories: List[str] = field(default_factory=list)
    additional_files: List[str] = field(default_factory=list)
    
    # Desktop file options
    use_existing_desktop: bool = False
    detected_desktop_file: Optional[str] = None
    custom_desktop_file: Optional[str] = None
    
    # Analysis data
    structure_analysis: Optional[Dict] = None
    wrapper_analysis: Optional[Dict] = None
    
    # Build options
    output_dir: Optional[str] = None
    include_dependencies: bool = True
    selected_dependencies: List[str] = field(default_factory=list)
    strip_binaries: bool = False
    build_environment: Optional[str] = None
    
    # Icon theme options
    include_icon_theme: bool = False
    icon_theme_choice: str = "papirus"  # Options: "papirus", "adwaita", "none"

    # Auto-update options
    update_url: str = ""
    update_pattern: str = ""  # Pattern to match AppImage filename in releases
    
    # Compatibility properties
    @property
    def author(self) -> str:
        """Return first author for backward compatibility"""
        return self.authors[0] if self.authors else "Unknown"
    
    @property
    def website(self) -> str:
        """Return first website for backward compatibility"""
        return self.websites[0] if self.websites else ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for builder"""
        return {
            'name': self.name,
            'version': self.version,
            'executable': self.executable,
            'description': self.description,
            'authors': self.authors,
            'author': self.author,
            'websites': self.websites,
            'website': self.website,
            'categories': self.categories,
            'app_type': self.app_type,
            'executable_name': self.executable_name,
            'terminal': self.terminal,
            'icon': self.icon,
            'additional_directories': self.additional_directories,
            'additional_files': self.additional_files,
            'use_existing_desktop': self.use_existing_desktop,
            'detected_desktop_file': self.detected_desktop_file,
            'custom_desktop_file': self.custom_desktop_file,
            'structure_analysis': self.structure_analysis,
            'wrapper_analysis': self.wrapper_analysis,
            'output_dir': self.output_dir,
            'include_dependencies': self.include_dependencies,
            'selected_dependencies': self.selected_dependencies,
            'strip_binaries': self.strip_binaries,
            'build_environment': self.build_environment,
            'include_icon_theme': self.include_icon_theme,
            'icon_theme_choice': self.icon_theme_choice,
            'update_url': self.update_url,
            'update_pattern': self.update_pattern,
        }