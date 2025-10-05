"""
Validation utilities for application information and files
"""

import os
import re
from utils.i18n import _


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


def validate_app_name(name):
    """Validate application name"""
    if not name or len(name.strip()) < 2:
        raise ValidationError(_("Application name must be at least 2 characters long"))
    
    if not re.match(r'^[a-zA-Z0-9\s\-_.]+$', name):
        raise ValidationError(_("Application name contains invalid characters"))
    
    return name.strip()


def validate_version(version):
    """Validate version string"""
    if not version or len(version.strip()) < 1:
        raise ValidationError(_("Version is required"))
    
    if not re.match(r'^[0-9]+(\.[0-9]+)*([a-zA-Z0-9\-_.]*)?$', version):
        raise ValidationError(_("Invalid version format"))
    
    return version.strip()


def validate_executable(file_path):
    """Validate executable file"""
    if not file_path or not os.path.exists(file_path):
        raise ValidationError(_("Executable file does not exist"))
    
    if not os.access(file_path, os.X_OK):
        raise ValidationError(_("File is not executable"))
    
    return file_path


def validate_desktop_content(content):
    """Validate desktop file content for common issues"""
    lines = content.strip().split('\n')
    
    # Check for required sections
    if not any(line.strip() == '[Desktop Entry]' for line in lines):
        print(_("Error: Missing [Desktop Entry] section"))
        return False
    
    # Check for required keys
    required_keys = ['Type', 'Name', 'Exec']
    found_keys = set()
    
    for line in lines:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            key = line.split('=')[0].strip()
            found_keys.add(key)
    
    missing_keys = set(required_keys) - found_keys
    if missing_keys:
        print(_("Error: Missing required keys: {}").format(missing_keys))
        return False
    
    # Check for empty values in important fields
    for line in lines:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            if key in ['Name', 'Exec'] and not value:
                print(_("Error: Empty value for required key: {}").format(key))
                return False
    
    return True


def validate_dependencies(dependencies):
    """Validate and check system dependencies"""
    from utils.system import find_executable_in_path
    
    missing = []
    available = []
    
    for dep in dependencies:
        if find_executable_in_path(dep):
            available.append(dep)
        else:
            missing.append(dep)
    
    return {
        'available': available,
        'missing': missing
    }