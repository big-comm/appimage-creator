"""
Application templates for different app types
"""

import os
from pathlib import Path
from templates.base import AppTemplate
from utils.file_ops import get_file_type
from core.structure_analyzer import analyze_wrapper_script


class PythonAppTemplate(AppTemplate):
    """Template for Python applications"""
    
    def get_launcher_script(self):
        main_file = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export PYTHONPATH="${{HERE}}/usr/lib/python3/site-packages:${{PYTHONPATH}}"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{self.app_info['executable_name']}"

if [ -f "${{HERE}}/usr/python/venv/bin/python3" ]; then
    exec "${{HERE}}/usr/python/venv/bin/python3" "{main_file}" "$@"
else
    echo "Error: Python virtualenv not found in AppImage"
    exit 1
fi
'''

    def get_dependencies(self):
        return ['python3', 'python3-pip']
        
    def prepare_appdir(self, appdir_path):
        python_dirs = ["usr/lib/python3/site-packages", "usr/share/python3"]
        for dir_path in python_dirs:
            (appdir_path / dir_path).mkdir(parents=True, exist_ok=True)


class PythonWrapperAppTemplate(AppTemplate):
    """Template for Python wrapper applications"""
    
    def get_launcher_script(self):
        wrapper_analysis = self.app_info.get('wrapper_analysis', {})
        target_executable = wrapper_analysis.get('target_executable', 'main.py')
        
        # Determine the relative path from the project root
        project_root = self.app_info.get('structure_analysis', {}).get('project_root')
        if project_root and target_executable:
            # This will give a path like 'usr/share/app/main.py'
            relative_script_path = os.path.relpath(target_executable, project_root)
        else:
            # Fallback
            relative_script_path = f"usr/share/{self.app_info['executable_name']}/main.py"

        # This script assumes that AppRun has already set up the environment (PATH, PYTHONHOME, etc.)
        return f'''#!/bin/sh
# Wrapper for {self.app_info['name']}

# Find the AppDir. The script is in AppDir/usr/bin, so we go up two levels.
HERE=$(dirname "$(dirname "$(readlink -f "$0")")")

# Execute the Python script using the Python from the virtual environment.
# The venv Python is expected to be in the PATH set by AppRun.
exec python3 "${{HERE}}/{relative_script_path}" "$@"
'''

    def get_dependencies(self):
        return ['python3', 'python3-pip']
        
    def prepare_appdir(self, appdir_path):
        python_dirs = ["usr/lib/python3/site-packages", "usr/share/python3", "usr/share/locale"]
        for dir_path in python_dirs:
            (appdir_path / dir_path).mkdir(parents=True, exist_ok=True)


class BinaryAppTemplate(AppTemplate):
    """Template for binary applications"""
    
    def get_launcher_script(self):
        executable_name = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{self.app_info['executable_name']}"

if [ -f "${{HERE}}/usr/bin/{executable_name}" ]; then
    exec "${{HERE}}/usr/bin/{executable_name}" "$@"
elif [ -f "./{executable_name}" ]; then
    exec "./{executable_name}" "$@"
else
    echo "Error: Executable {executable_name} not found"
    exit 1
fi
'''


class JavaAppTemplate(AppTemplate):
    """Template for Java applications"""
    
    def get_launcher_script(self):
        jar_file = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export JAVA_HOME="${{HERE}}/usr/lib/jvm/default"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{self.app_info['executable_name']}"

if command -v java >/dev/null 2>&1; then
    exec java -jar "{jar_file}" "$@"
else
    echo "Error: Java not found"
    exit 1
fi
'''

    def get_dependencies(self):
        return ['openjdk-11-jre', 'openjdk-17-jre']


class ShellAppTemplate(AppTemplate):
    """Template for shell scripts"""
    
    def get_launcher_script(self):
        script_file = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export PATH="${{HERE}}/usr/bin:${{PATH}}"
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{self.app_info['executable_name']}"

exec bash "{script_file}" "$@"
'''

    def get_dependencies(self):
        return ['bash']


class QtAppTemplate(AppTemplate):
    """Template for Qt applications"""
    
    def get_launcher_script(self):
        executable_name = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export QT_PLUGIN_PATH="${{HERE}}/usr/lib/qt6/plugins:${{HERE}}/usr/lib/qt5/plugins:${{QT_PLUGIN_PATH}}"
export QML_IMPORT_PATH="${{HERE}}/usr/qml:${{QML_IMPORT_PATH}}"
export QML2_IMPORT_PATH="${{HERE}}/usr/qml:${{QML2_IMPORT_PATH}}"
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{self.app_info['executable_name']}"

if [ -f "${{HERE}}/usr/bin/{executable_name}" ]; then
    exec "${{HERE}}/usr/bin/{executable_name}" "$@"
elif [ -f "./{executable_name}" ]; then
    exec "./{executable_name}" "$@"
else
    echo "Error: Qt application {executable_name} not found"
    exit 1
fi
'''

    def get_dependencies(self):
        return ['qt6-base', 'qt6-qml', 'qt6-quick', 'qt5-base']


class GtkAppTemplate(AppTemplate):
    """Template for GTK applications"""
    
    def get_launcher_script(self):
        executable_name = os.path.basename(self.app_info['executable'])
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export GSETTINGS_SCHEMA_DIR="${{HERE}}/usr/share/glib-2.0/schemas:${{GSETTINGS_SCHEMA_DIR}}"
export GI_TYPELIB_PATH="${{HERE}}/usr/lib/girepository-1.0:${{GI_TYPELIB_PATH}}"
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

if [ -f "${{HERE}}/usr/bin/{executable_name}" ]; then
    exec "${{HERE}}/usr/bin/{executable_name}" "$@"
elif [ -f "${{HERE}}/usr/share/{self.app_info['executable_name']}/{executable_name}" ]; then
    exec "${{HERE}}/usr/share/{self.app_info['executable_name']}/{executable_name}" "$@"
else
    echo "Error: GTK application {executable_name} not found"
    exit 1
fi
'''

    def get_dependencies(self):
        return ['gtk4', 'libadwaita-1', 'glib2', 'gtk3']


class ElectronAppTemplate(AppTemplate):
    """Template for Electron applications"""
    
    def get_launcher_script(self):
        app_name = self.app_info['executable_name']
        
        return f'''#!/bin/bash
# {self.app_info['name']} Launcher

SCRIPT_DIR="$(dirname "$(readlink -f "${{0}}")")"
HERE="$(dirname "$(dirname "${{SCRIPT_DIR}}")")"

export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"
export PATH="${{HERE}}/usr/bin:${{PATH}}"
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS}}"

cd "${{HERE}}/usr/share/{app_name}"

if [ -f "${{HERE}}/usr/lib/{app_name}/electron" ]; then
    exec "${{HERE}}/usr/lib/{app_name}/electron" . "$@"
elif [ -f "${{HERE}}/usr/bin/electron" ]; then
    exec "${{HERE}}/usr/bin/electron" . "$@"
elif command -v electron >/dev/null 2>&1; then
    exec electron . "$@"
else
    echo "Error: Electron not found"
    exit 1
fi
'''

    def get_dependencies(self):
        return ['electron', 'nodejs', 'npm']


# Template factory and utilities

def get_template_for_type(app_type, app_info):
    """Factory function to get template for app type"""
    templates = {
        'python': PythonAppTemplate,
        'python_wrapper': PythonWrapperAppTemplate,
        'binary': BinaryAppTemplate,
        'java': JavaAppTemplate,
        'shell': ShellAppTemplate,
        'qt': QtAppTemplate,
        'gtk': GtkAppTemplate,
        'electron': ElectronAppTemplate
    }
    
    template_class = templates.get(app_type, BinaryAppTemplate)
    return template_class(app_info)


def get_app_type_from_file(file_path, structure_analysis=None):
    """Detect application type from file"""
    # First, prioritize the full structure analysis if available
    if structure_analysis and structure_analysis.get('wrapper_analysis'):
        wrapper_analysis = structure_analysis['wrapper_analysis']
        if wrapper_analysis.get('type') == 'python_wrapper':
            return 'python_wrapper'
        elif wrapper_analysis.get('target_type'):
            return wrapper_analysis['target_type']

    # If no wrapper was found in the main analysis, do a quick check here
    file_type = get_file_type(file_path)
    
    if file_type == 'shell':
        # It's a shell script, let's see if it's a known wrapper type
        wrapper_analysis = analyze_wrapper_script(file_path)
        if wrapper_analysis.get('type') == 'python_wrapper':
            return 'python_wrapper'
        # Add other wrapper types here if needed (e.g., java_wrapper)
    
    # Fallback to simple mapping
    type_mapping = {
        'python': 'python',
        'shell': 'shell',
        'java': 'java',
        'binary': 'binary',
        'javascript': 'electron',
        'unknown': 'binary'
    }
    
    return type_mapping.get(file_type, 'binary')


def get_available_categories():
    """Get list of available desktop categories"""
    return [
        'AudioVideo', 'Audio', 'Video', 'Development', 'Education',
        'Game', 'Graphics', 'Network', 'Office', 'Science',
        'Settings', 'System', 'Utility'
    ]