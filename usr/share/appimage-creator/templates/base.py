"""
Base template class for application types
"""

from abc import ABC, abstractmethod


class AppTemplate(ABC):
    """Base class for application templates"""
    
    def __init__(self, app_info):
        self.app_info = app_info
        
    @abstractmethod
    def get_launcher_script(self):
        """Generate launcher script content"""
        raise NotImplementedError
        
    def get_dependencies(self):
        """Get list of required dependencies"""
        return []
        
    def prepare_appdir(self, appdir_path):
        """Prepare AppDir specific to this app type"""
        pass