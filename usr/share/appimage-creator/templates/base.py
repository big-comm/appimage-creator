"""
Base template class for application types
"""

from abc import ABC, abstractmethod
from pathlib import Path

from core.app_info import AppInfo


class AppTemplate(ABC):
    """Base class for application templates"""

    def __init__(self, app_info: AppInfo):
        self.app_info = app_info

    @abstractmethod
    def get_launcher_script(self) -> str:
        """Generate launcher script content"""
        raise NotImplementedError

    def get_dependencies(self) -> list[str]:
        """Get list of required dependencies"""
        return []

    def prepare_appdir(self, appdir_path: str | Path) -> None:
        """Prepare AppDir specific to this app type"""
        pass
