"""
Core AppImage builder - orchestrates the build process
"""

import os
import sys
import re
import sysconfig
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from validators.validators import validate_app_name, validate_version, validate_executable
from core.structure_analyzer import detect_application_structure
from templates.app_templates import get_template_for_type, get_app_type_from_file
from generators.icons import process_icon, generate_default_icon
from generators.files import (create_launcher_script_file, create_desktop_file, 
                               create_apprun_file, adapt_existing_desktop_file)
from utils.file_ops import copy_files_recursively, download_file, scan_directory_structure
from utils.system import (sanitize_filename, get_system_info, 
                          find_executable_in_path, make_executable)
from core.environment_manager import EnvironmentManager
from utils.i18n import _

# Master dictionary for system dependencies
SYSTEM_DEPENDENCIES = {
    'glib': {
        'name': 'GLib/GObject',
        'libs': [
            # 'libgobject-2.0.so*', 'libglib-2.0.so*', 'libgio-2.0.so*', 'libffi.so*',
            'libgmodule-2.0.so*', 'libgirepository-1.0.so*',
            'libpcre.so.3'
        ],
        'typelibs': [
            'GLib-2.0.typelib', 
            'GObject-2.0.typelib', 
            'Gio-2.0.typelib',
            'GModule-2.0.typelib',
            'cairo-1.0.typelib',
            'Pango-1.0.typelib',
            'PangoCairo-1.0.typelib',
            'GdkPixbuf-2.0.typelib'
        ],
        'detection_keyword': 'gi',
        'essential': True
    },
    'jpeg': {
        'name': 'JPEG Library',
        # 'libs': ['libjpeg.so*', 'libjpeg.so.8*', 'libjpeg.so.62*'],
        'libs': ['libjpeg.so.8*'],
        'typelibs': [],
        'detection_keyword': 'gtk4',
        'essential': False,
        'conflicting': True
    },
    'gtk3': {
        'name': 'GTK3',
        'libs': ['libgtk-3.so*', 'libcairo.so*', 'libcairo-gobject.so*'],
        'typelibs': [
            'Gtk-3.0.typelib', 'Gdk-3.0.typelib', 'GdkPixbuf-2.0.typelib',
            'Pango-1.0.typelib', 'PangoCairo-1.0.typelib', 'cairo-1.0.typelib',
            'HarfBuzz-0.0.typelib', 'Atk-1.0.typelib'
        ],
        'detection_keyword': 'gtk3',
        'essential': False
    },
    'gtk4': {
        'name': 'GTK4',
        'libs': ['libgtk-4.so*', 'libgraphene-1.0.so*'],
        'typelibs': [
            'Gtk-4.0.typelib', 'Gdk-4.0.typelib', 'Gsk-4.0.typelib',
            'Graphene-1.0.typelib',
            'Pango-1.0.typelib',
            'PangoCairo-1.0.typelib',
            'cairo-1.0.typelib',
            'GdkPixbuf-2.0.typelib',
            'HarfBuzz-0.0.typelib',
            'freetype2-2.0.typelib'
        ],
        'detection_keyword': 'gtk4',
        'essential': False
    },
    'adwaita': {
        'name': 'Libadwaita 1',
        'libs': ['libadwaita-1.so*'],
        'typelibs': ['Adw-1.typelib'],
        'detection_keyword': 'adwaita',
        'essential': False
    },
    'vte': {
        'name': 'VTE (Terminal Widget)',
        'libs': [
            'libvte-2.91.so*', 'libvte-2.91-gtk4.so*',
            'libicuuc.so*', 'libicudata.so*', 'libicui18n.so*'
        ],
        'typelibs': ['Vte-2.91.typelib', 'Vte-3.91.typelib'],
        'detection_keyword': 'vte',
        'essential': False
    },
    'libsecret': {
        'name': 'Libsecret (Keyring)',
        'libs': ['libsecret-1.so*'],
        'typelibs': ['Secret-1.typelib'],
        'detection_keyword': 'libsecret',
        'essential': False
    },
    'gstreamer-gtk': {
        'name': 'GStreamer GTK Sink',
        'libs': ['libgstgtk.so*'],
        'typelibs': ['GstGtk-1.0.typelib'],
        'detection_keyword': 'gstreamer-gtk',
        'essential': False
    },
    'mpv': {
        'name': 'MPV Library',
        # Expanded list for selective bundling of essential MPV/FFmpeg libs
        'libs': [
            'libmpv.so*',
            'libavutil.so*',
            'libavcodec.so*',
            'libavformat.so*',
            'libswresample.so*',
            'libswscale.so*',
            'libplacebo.so*',
            'libvulkan.so*',
            'libx264.so*'
        ],
        'typelibs': [], # MPV does not use GObject Introspection
        'detection_keyword': 'mpv',
        'essential': False
    }
}

# Master dictionary for system binaries to be detected and bundled
SYSTEM_BINARIES = {
    'vainfo': {
        'name': 'VA-API Info Tool',
        'binary_name': 'vainfo',
        'detection_keyword': 'vainfo',
        'essential': False
    },
    # Add mpv
    'mpv': {
        'name': 'MPV Media Player',
        'binary_name': 'mpv',
        'detection_keyword': 'mpv',
        'essential': False,
        'manage_libs_manually': True  # This new flag prevents the aggressive 'ldd' scan
    },
    # Add other binaries here in the future, e.g., 'vdpauinfo'
}

class AppImageBuilder:
    """Main class for building AppImages"""
    
    def __init__(self):
        self.app_info = {}
        self.build_dir = None
        self.appdir_path = None
        self.appimagetool_path = None
        self.linuxdeploy_path = None
        self.progress_callback = None
        self.log_callback = None
        self.cancel_requested = False
        self._build_thread = None
        self.build_environment = None
        self.python_version = None
        self.container_name = None
        
    def is_local_build(self):
        """Check if building locally (not in container)"""
        return self.build_environment is None or self.container_name is None
    
    def get_compatibility_warning(self):
        """Get compatibility warning message for local builds"""
        if not self.is_local_build():
            return None
        
        app_type = self.app_info.get('app_type', 'binary')
        if app_type not in ['python', 'python_wrapper', 'gtk', 'qt']:
            return None
        
        import platform
        host_distro = platform.freedesktop_os_release().get('NAME', 'Unknown')
        
        return {
            'title': _("⚠️ Local Build Warning"),
            'message': _(
                "You are building locally on {distro}.\n\n"
                "AppImages built on your system may NOT work on other distributions due to:\n"
                "• Different Python versions\n"
                "• Different library versions\n"
                "• Distribution-specific dependencies\n\n"
                "For MAXIMUM COMPATIBILITY, use:\n"
                "Build Environment → Ubuntu 20.04 or 22.04\n\n"
                "Continue anyway?"
            ).format(distro=host_distro),
            'severity': 'warning'
        }
        
    def set_app_info(self, app_info: dict):
        """Set application information with structure analysis"""
        app_info = app_info.copy()
        
        # Validate required fields
        app_info['name'] = validate_app_name(app_info['name'])
        app_info['version'] = validate_version(app_info['version'])
        app_info['executable'] = validate_executable(app_info['executable'])
        
        # Analyze structure
        structure_analysis = detect_application_structure(app_info['executable'])
        app_info['structure_analysis'] = structure_analysis
        
        # Auto-detect app type
        if not app_info.get('app_type'):
            app_info['app_type'] = get_app_type_from_file(
                app_info['executable'], 
                structure_analysis
            )
        
        # Define the base name - use the actual executable filename
        if not app_info.get('executable_name'):
            executable_path = Path(app_info['executable'])
            app_info['executable_name'] = executable_path.name
        
        # Store wrapper analysis
        if structure_analysis.get('wrapper_analysis'):
            app_info['wrapper_analysis'] = structure_analysis['wrapper_analysis']
        
        # Merge suggested directories
        app_info['additional_directories'] = app_info.get('additional_directories', [])
        
        # Set defaults
        app_info.setdefault('description', f"{app_info['name']} application")
        app_info.setdefault('authors', ['Unknown'])
        app_info.setdefault('categories', ['Utility'])
        app_info.setdefault('terminal', False)
        
        self.app_info = app_info
        
        # Set build environment
        self.build_environment = app_info.get('build_environment')
        if self.build_environment:
            env_manager = EnvironmentManager()
            self.container_name = f"appimage-creator-{self.build_environment}"
            self.log(_("Will build in container: {}").format(self.container_name))
        else:
            self.container_name = None
            self.log(_("Will build in local system"))
        
    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """Set progress callback function"""
        self.progress_callback = callback
        
    def set_log_callback(self, callback: Callable[[str], None]):
        """Set log callback function"""
        self.log_callback = callback
        
    def _run_command(self, cmd, env=None, cwd=None, timeout=None, capture_output=True):
        """Run command, optionally inside container."""
        if self.container_name:
            # Run inside container using distrobox-enter
            self.log(_("Running in container: {}").format(' '.join(cmd)))
            
            # Build the full command to run inside container
            cmd_str = ' '.join(f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd)
            
            # If there's a working directory, cd into it first
            if cwd:
                cmd_str = f'cd "{cwd}" && {cmd_str}'
            
            # Build container command
            container_cmd = [
                'distrobox-enter',
                self.container_name,
                '--',
                'bash', '-c',
                cmd_str
            ]
            
            # Merge environment variables
            merged_env = os.environ.copy()
            if env:
                merged_env.update(env)
            
            return subprocess.run(
                container_cmd,
                env=merged_env,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                cwd=None
            )
        else:
            # Run locally
            return subprocess.run(cmd, env=env, capture_output=capture_output, 
                                text=True, timeout=timeout, cwd=cwd)
        
    def log(self, message: str):
        """Log a message"""
        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass
        print(message)
        
    def update_progress(self, percentage: int, message: str):
        """Update progress"""
        if self.progress_callback:
            try:
                self.progress_callback(percentage, message)
            except Exception:
                pass
            
    def cancel_build(self):
        """Cancel the current build process"""
        self.cancel_requested = True
        self.log(_("Build cancellation requested"))
        
    def create_build_directory(self):
        """Create temporary build directory"""
        try:
            self.build_dir = Path(tempfile.mkdtemp(prefix='appimage_build_'))
            self.appdir_path = self.build_dir / f"{self.app_info['executable_name']}.AppDir"
            self.log(_("Created build directory: {}").format(self.build_dir))
            return self.build_dir
        except Exception as e:
            raise RuntimeError(_("Failed to create build directory: {}").format(e))
        
    def create_appdir_structure(self):
        """Create AppDir directory structure"""
        self.log(_("Creating AppDir structure..."))
        
        try:
            if self.appdir_path.exists():
                shutil.rmtree(self.appdir_path)
            
            # A minimal structure is enough, the copy will create the rest
            self.appdir_path.mkdir(parents=True, exist_ok=True)
                
            self.update_progress(10, _("AppDir structure created"))
        except Exception as e:
            raise RuntimeError(_("Failed to create AppDir structure: {}").format(e))
        
    def copy_application_files(self):
        """Copy application files to AppDir"""
        self.log(_("Copying application files..."))
        
        try:
            structure_analysis = self.app_info.get('structure_analysis', {})
            project_root = structure_analysis.get('project_root')

            if project_root and os.path.exists(project_root):
                self.log(_("Copying structured project from: {}").format(project_root))
                exclude_patterns = [
                    # Version control and cache
                    '.git', 
                    '.github',
                    '.gitignore',
                    '__pycache__',
                    '*.pyc',
                    '.DS_Store',
                    
                    # Temporary and translation files
                    '*.tmp',
                    '*.po',
                    '*.pot',
                    
                    # Documentation and project metadata files
                    'README.md',
                    'LICENSE',
                    'requirements.txt', # The builder uses it, but it doesn't need to be in the final AppImage
                    
                    # Specific build/package directories
                    'pkgbuild'
                ]

                copy_files_recursively(project_root, self.appdir_path, exclude_patterns=exclude_patterns)
            else:
                # Fallback for simple applications without a clear root
                self.log(_("Project root not found, copying as simple application."))
                executable_path = Path(self.app_info['executable'])
                app_share_dir = self.appdir_path / "usr" / "share" / self.app_info['executable_name']
                app_share_dir.mkdir(parents=True, exist_ok=True)
                if executable_path.is_file():
                    shutil.copy2(executable_path, app_share_dir)
                else:
                    copy_files_recursively(executable_path, app_share_dir)

            # Copy any extra user-defined directories
            self._copy_additional_directories()
            
            self.update_progress(25, _("Application files copied"))
        except Exception as e:
            raise RuntimeError(_("Failed to copy application files: {}").format(e))
        
    def _copy_additional_directories(self):
        """Copy user-specified additional directories"""
        additional_dirs = self.app_info.get('additional_directories', [])
        
        for dir_path in additional_dirs:
            try:
                if not os.path.exists(dir_path):
                    self.log(_("Warning: Directory not found: {}").format(dir_path))
                    continue
                    
                src_path = Path(dir_path)
                dest_path = self.appdir_path / "usr" / "share" / src_path.name
                    
                self.log(_("Copying additional directory: {} -> {}").format(src_path, dest_path))
                copy_files_recursively(src_path, dest_path)
            except Exception as e:
                self.log(_("Warning: Failed to copy directory {}: {}").format(dir_path, e))
            
    def process_application_icon(self):
        """Process and copy icon"""
        self.log(_("Processing icon..."))
        
        try:
            icon_path = self.app_info.get('icon')

            # Auto-detect icon if not provided
            if not icon_path and self.app_info.get('structure_analysis'):
                detected_icons = self.app_info['structure_analysis']['detected_files'].get('icons', [])
                if detected_icons:
                    svg_icons = [i for i in detected_icons if i.endswith('.svg')]
                    icon_path = svg_icons[0] if svg_icons else detected_icons[0]
                    self.log(_("Using detected icon: {}").format(icon_path))

            if not icon_path or not os.path.exists(icon_path):
                self.log(_("No icon provided, will use default from project"))
                self.update_progress(35, _("Icon check complete"))
                return

            # Store icon info for later use in desktop file creation
            self.app_info['_detected_icon_path'] = icon_path

            self.update_progress(35, _("Icon processed"))
            
        except Exception as e:
            self.log(_("Warning: Icon processing failed: {}").format(e))
        
    def create_launcher_and_desktop_files(self):
        """Create launcher and desktop files"""
        self.log(_("Creating launcher and desktop files..."))
        
        try:
            # Find the desktop file that was copied into the AppDir
            appdir_desktop_files = list((self.appdir_path / "usr/share/applications").glob("*.desktop"))
            
            if not appdir_desktop_files:
                self.log(_("No desktop file found in AppDir, generating a new one."))
                create_desktop_file(self.appdir_path, self.app_info)
            else:
                source_desktop_file = appdir_desktop_files[0]
                self.log(_("Found desktop file from source project: {}").format(source_desktop_file.name))
                
                # Create symlink to desktop file in AppDir root (required by appimagetool)
                root_desktop_path = self.appdir_path / source_desktop_file.name
                relative_desktop = os.path.relpath(source_desktop_file, self.appdir_path)
                if root_desktop_path.exists():
                    root_desktop_path.unlink()
                root_desktop_path.symlink_to(relative_desktop)
                self.log(_("Created desktop symlink in AppDir root: {}").format(source_desktop_file.name))

            self.log(_("Creating custom AppRun script..."))
            
            app_info_for_apprun = self.app_info.copy()
            app_type = self.app_info.get('app_type')
            
            # Add the dynamically detected python_version to the app_info copy
            if hasattr(self, 'python_version') and self.python_version:
                app_info_for_apprun['python_version'] = self.python_version
            
            # Determine the components of the command that AppRun should execute
            if app_type in ['python', 'python_wrapper', 'gtk', 'qt']:
                structure = self.app_info.get('structure_analysis', {})
                wrapper_analysis = structure.get('wrapper_analysis', {})
                
                target_script_abs = wrapper_analysis.get('target_executable')
                project_root_abs = structure.get('project_root')

                if not target_script_abs or not project_root_abs:
                    raise RuntimeError("Could not determine target Python script from structure analysis.")

                # Calculate the script's path relative to the project root
                relative_script_path = os.path.relpath(target_script_abs, project_root_abs)
                
                app_info_for_apprun['apprun_executable'] = 'usr/python/venv/bin/python3'
                app_info_for_apprun['apprun_argument'] = relative_script_path
                self.log(_("AppRun will execute Python on: {}").format(relative_script_path))

            else:
                # For binary apps
                project_root = self.app_info.get('structure_analysis', {}).get('project_root')
                if project_root:
                    rel_path = os.path.relpath(self.app_info['executable'], project_root)
                    app_info_for_apprun['apprun_executable'] = rel_path
                else:
                    app_info_for_apprun['apprun_executable'] = f"usr/bin/{self.app_info['executable_name']}"
                
                app_info_for_apprun['apprun_argument'] = None
                self.log(_("AppRun will execute: {}").format(app_info_for_apprun['apprun_executable']))

            # Create the AppRun file
            create_apprun_file(self.appdir_path, app_info_for_apprun)
            
            self.update_progress(50, _("Launcher and desktop files created"))
        except Exception as e:
            raise RuntimeError(_("Failed to create launcher files: {}").format(e))
            
    def copy_dependencies(self):
        """Copy dependencies: Python virtualenv + external binaries"""
        if not self.app_info.get('include_dependencies', True):
            self.log(_("Skipping dependency inclusion."))
            self.update_progress(70, _("Dependencies skipped"))
            return

        # Python dependencies (if Python app)
        app_type = self.app_info.get('app_type', 'binary')
        if app_type in ['python', 'python_wrapper', 'gtk', 'qt']:
            self._setup_python_environment()
        
        # External binaries with linuxdeploy
        self._bundle_external_binaries()
        
        # Create icon symlinks matching desktop file name
        self._create_icon_symlinks()
        
        # System libraries (fallback)
        self._copy_system_libraries()
        
        # GObject Introspection typelibs (for PyGObject apps)
        self._copy_typelibs()
        
        # Copy only essential GStreamer plugins
        self._copy_gstreamer_plugins()
        
        # Copy MPV configuration if needed
        self._copy_mpv_config()
        
        # Icon theme handling based on user configuration
        include_icon_theme = self.app_info.get('include_icon_theme', True)
        icon_theme_choice = self.app_info.get('icon_theme_choice', 'papirus')
        
        if include_icon_theme:
            # Check if it's a GTK application
            is_gtk_app = False
            if app_type in ['python', 'python_wrapper', 'gtk', 'qt']:
                is_gtk_app = self._detect_gi_usage(self.app_info)
            
            # If GTK app or user explicitly enabled, copy the selected theme
            if is_gtk_app:
                if icon_theme_choice == 'papirus':
                    self.log(_("Installing Papirus icon theme for GTK application"))
                    self._copy_papirus_symbolic_icons()
                elif icon_theme_choice == 'adwaita':
                    self.log(_("Installing Adwaita icon theme for GTK application"))
                    self._copy_symbolic_icons()
            else:
                # Not a GTK app, but user enabled icon theme
                selected_deps = self.app_info.get('selected_dependencies', [])
                if 'gtk4' in selected_deps or 'adwaita' in selected_deps:
                    if icon_theme_choice == 'papirus':
                        self.log(_("Installing Papirus icon theme"))
                        self._copy_papirus_symbolic_icons()
                    elif icon_theme_choice == 'adwaita':
                        self.log(_("Installing Adwaita icon theme"))
                        self._copy_symbolic_icons()
        else:
            self.log(_("Icon theme inclusion disabled by user"))
        
        self.log(_("Dependencies installed successfully."))
        self.update_progress(70, _("Dependencies processed"))

    def _setup_python_environment(self):
        """Setup Python virtualenv for Python applications"""
        self.log(_("Setting up Python environment..."))
        
        try:
            structure_analysis = self.app_info.get('structure_analysis', {})
            project_root_str = structure_analysis.get('project_root')
            
            if project_root_str:
                project_root = Path(project_root_str)
                requirements_source = project_root / "requirements.txt"
            else:
                executable_path = Path(self.app_info['executable'])
                requirements_source = executable_path.parent / "requirements.txt"
            
            # Start with essential packages for GTK/Python applications
            packages_to_install = ['PyGObject', 'PyCairo']

            # If requirements.txt exists, add its content to the list
            if requirements_source.exists():
                with open(requirements_source, 'r') as f:
                    user_packages = [line.strip() for line in f if line.strip()]
                    packages_to_install.extend(user_packages)
            else:
                self.log(_("Warning: requirements.txt not found. Using default packages."))

            # Remove duplicates (in case user already listed PyGObject) and join everything
            requirements_content = "\n".join(list(set(packages_to_install)))
            
            python_dir = self.appdir_path / "usr" / "python"
            python_dir.mkdir(parents=True, exist_ok=True)
            
            self.update_progress(55, _("Creating Python virtualenv..."))
            
            venv_path = python_dir / "venv"
            self.log(_("Creating isolated virtualenv at: {}").format(venv_path))

            # Create a clean venv with --copies flag for AppImage compatibility
            result = self._run_command(
                ["python3", "-m", "venv", "--copies", str(venv_path)],
                timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(_("Failed to create virtualenv: {}").format(result.stderr or result.stdout))

            self.log(_("Virtualenv created successfully."))
            
            # Copy Python stdlib to venv for portability
            self.log(_("Copying Python standard library to venv..."))
            self.update_progress(57, _("Copying Python stdlib..."))
            
            try:
                # Detect Python version in build environment
                py_cmd = ["python3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]
                result = self._run_command(py_cmd, capture_output=True, timeout=10)
                
                if result.returncode == 0:
                    py_version_str = result.stdout.strip()
                    self.python_version = py_version_str
                    py_version_short = f"python{py_version_str}"
                else:
                    # Fallback to host Python version
                    host_py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                    self.log(_("Warning: Could not detect Python version in container. Falling back to host version: {}").format(host_py_version))
                    self.python_version = host_py_version
                    py_version_short = f"python{self.python_version}"
                
                # Get stdlib path from build environment
                stdlib_cmd = ["python3", "-c", "import sysconfig; print(sysconfig.get_path('stdlib'))"]
                result = self._run_command(stdlib_cmd, capture_output=True, timeout=10)
                
                if result.returncode == 0:
                    stdlib_path = result.stdout.strip()
                else:
                    import sysconfig
                    stdlib_path = sysconfig.get_path('stdlib')
                
                # venv_stdlib_dest = venv_path / "lib" / py_version_short
                venv_lib_dir = venv_path / "lib"
                venv_stdlib_dest = venv_lib_dir / py_version_short
                
                self.log(_("Copying stdlib from {} to {}").format(stdlib_path, venv_stdlib_dest))
                
                # Copy CONTENTS of stdlib
                if self.container_name:
                    # Container: use script with wildcard
                    copy_script = f"""#!/bin/bash
set -e
if [ ! -d "{stdlib_path}" ]; then
    echo "ERROR: stdlib not found at {stdlib_path}"
    exit 1
fi
mkdir -p "{venv_stdlib_dest}"
cp -r "{stdlib_path}"/* "{venv_stdlib_dest}/" || exit 1
if [ ! -d "{venv_stdlib_dest}/encodings" ]; then
    echo "ERROR: encodings module not found"
    exit 1
fi
"""
                    script_path = self.build_dir / "copy_stdlib.sh"
                    with open(script_path, "w") as f:
                        f.write(copy_script)
                    make_executable(script_path)
                    result = self._run_command([str(script_path)], timeout=120)
                    if result.returncode != 0:
                        raise RuntimeError(_("Failed to copy stdlib from container"))
                else:
                    # Local: iterate and copy contents
                    if not Path(stdlib_path).exists():
                        raise RuntimeError(_("Could not find stdlib at: {}").format(stdlib_path))
                    
                    venv_stdlib_dest.mkdir(parents=True, exist_ok=True)
                    
                    # Do NOT copy site-packages from system
                    exclude_dirs = ['site-packages', 'dist-packages']
                    
                    for item in Path(stdlib_path).iterdir():
                        if item.name in exclude_dirs:
                            self.log(_("Skipping system packages: {}").format(item.name))
                            continue
                        
                        dest_item = venv_stdlib_dest / item.name
                        if item.is_dir():
                            if dest_item.exists():
                                shutil.rmtree(dest_item)
                            shutil.copytree(item, dest_item, symlinks=False)
                        else:
                            shutil.copy2(item, dest_item)
                    
                    if not (venv_stdlib_dest / "encodings").exists():
                        raise RuntimeError(_("encodings module not found after stdlib copy"))
                
                self.log(_("Python stdlib copied successfully"))

                # Clean up unnecessary files from stdlib
                self.log(_("Cleaning up copied stdlib..."))
                
                # Remove test modules and development tools
                dirs_to_remove = [
                    "test", "tests", "idlelib", "tkinter", "turtledemo", 
                    "ensurepip", "lib2to3", "distutils", "pydoc_data", "Tools"
                ]
                
                for dirname in dirs_to_remove:
                    dir_path = venv_stdlib_dest / dirname
                    if dir_path.is_dir():
                        shutil.rmtree(dir_path, ignore_errors=True)
                
                # Remove __pycache__ from stdlib
                for pycache_dir in venv_stdlib_dest.rglob('__pycache__'):
                    shutil.rmtree(pycache_dir, ignore_errors=True)
                
                self.log(_("Stdlib cleanup complete."))
                
            except Exception as e:
                self.log(_("Error copying Python stdlib: {}").format(e))
                raise RuntimeError(_("Python stdlib required for AppImage"))
            
            # Copy Python shared libraries to AppImage
            self.log(_("Copying Python shared libraries..."))
            
            lib_dir = self.appdir_path / "usr" / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            
            # Find and copy libpython*.so files
            python_lib_patterns = [
                f"/usr/lib/libpython{py_version_str}*.so*",
                f"/usr/lib/x86_64-linux-gnu/libpython{py_version_str}*.so*",
                f"/usr/lib64/libpython{py_version_str}*.so*",
            ]
            
            for pattern in python_lib_patterns:
                try:
                    result = self._run_command(["sh", "-c", f"ls {pattern} 2>/dev/null || true"], 
                                              capture_output=True, timeout=10)
                    if result.returncode == 0 and result.stdout.strip():
                        for lib_path in result.stdout.strip().split('\n'):
                            lib_path = lib_path.strip()
                            
                            # When using container, trust the ls command result
                            # When local, verify file exists on host
                            should_copy = False
                            if self.container_name:
                                # Container: trust ls result, don't check os.path.exists
                                should_copy = bool(lib_path)
                            else:
                                # Local: verify file exists
                                should_copy = lib_path and os.path.exists(lib_path)
                            
                            if should_copy:
                                lib_name = os.path.basename(lib_path)
                                dest = lib_dir / lib_name
                                
                                # Copy the file (following symlinks)
                                copy_cmd = ["cp", "-L", lib_path, str(dest)]
                                result_cp = self._run_command(copy_cmd, timeout=10)
                                if result_cp.returncode == 0:
                                    self.log(f"  Copied: {lib_name}")
                                else:
                                    self.log(f"  Warning: Failed to copy {lib_name}")
                except Exception as e:
                    self.log(f"  Warning: Could not copy Python libs from {pattern}: {e}")
            
            self.log(_("Python shared libraries copied"))
            
            # Install required packages into the venv
            self.update_progress(60, _("Installing Python packages..."))
            
            pip_executable = venv_path / "bin" / "pip"
            packages = [pkg.strip() for pkg in requirements_content.split('\n') if pkg.strip()]
            
            self.log(_("Installing packages: {}").format(', '.join(packages)))

            # Setup environment for pip installation
            install_env = None
            if self.container_name:
                install_env = os.environ.copy()
                pkg_config_paths = [
                    "/usr/lib/x86_64-linux-gnu/pkgconfig",
                    "/usr/share/pkgconfig",
                    "/usr/lib/pkgconfig",
                ]
                existing_path = install_env.get('PKG_CONFIG_PATH', '')
                all_paths = pkg_config_paths + ([existing_path] if existing_path else [])
                install_env['PKG_CONFIG_PATH'] = ':'.join(filter(None, all_paths))
            
            for package in packages:
                self.log(_("Installing {}...").format(package))
                install_cmd = [str(pip_executable), "install", package, "--no-warn-script-location"]
                
                result = self._run_command(install_cmd, timeout=300, env=install_env)

                if result.returncode != 0:
                    self.log(_("Warning: Failed to install {}: {}").format(package, result.stderr or result.stdout))
                    
                    if package.lower() in ['pygobject', 'pygi']:
                        self.log(_("Attempting fallback: using system PyGObject bindings"))
                        self._use_system_pygobject(venv_path)
                else:
                    self.log(_("Successfully installed {}").format(package))
            
            self.log(_("Python packages installed"))
            
            # NOW perform aggressive cleanup AFTER pip installation
            self.log(_("Performing aggressive cleanup for size optimization..."))
            
            extra_dirs_to_remove = [
                "unittest",
                "__phello__",
                "turtle.py",
            ]
            
            for dirname in extra_dirs_to_remove:
                dir_path = venv_stdlib_dest / dirname
                if dir_path.is_dir():
                    shutil.rmtree(dir_path, ignore_errors=True)
                elif dir_path.is_file():
                    dir_path.unlink(missing_ok=True)
            
            # Clean up site-packages directory
            site_packages = venv_path / "lib" / py_version_short / "site-packages"
            if site_packages.exists():
                # Remove pip, setuptools, and pkg_resources
                for dirname in ["pip", "setuptools", "pkg_resources", "_distutils_hack"]:
                    pkg_dir = site_packages / dirname
                    if pkg_dir.is_dir():
                        shutil.rmtree(pkg_dir, ignore_errors=True)
                        self.log(_("  Removed: {}").format(dirname))
                
                # Remove .dist-info directories
                for dist_info in site_packages.glob("*.dist-info"):
                    if dist_info.is_dir():
                        shutil.rmtree(dist_info, ignore_errors=True)
                        
                # Remove .pth files that reference deleted modules
                for pth_file in site_packages.glob("*.pth"):
                    if pth_file.is_file():
                        try:
                            with open(pth_file, 'r') as f:
                                content = f.read()
                            if '_distutils_hack' in content or 'setuptools' in content:
                                pth_file.unlink()
                                self.log(_("  Removed: {}").format(pth_file.name))
                        except:
                            pass
            
            # Remove all __pycache__ and .pyc files from entire venv
            self.log(_("Removing bytecode cache files..."))
            removed_pycache = 0
            removed_pyc = 0
            
            for pycache_dir in venv_path.rglob('__pycache__'):
                shutil.rmtree(pycache_dir, ignore_errors=True)
                removed_pycache += 1
            
            for pyc_file in venv_path.rglob('*.pyc'):
                pyc_file.unlink(missing_ok=True)
                removed_pyc += 1
            
            self.log(_("  Removed {} __pycache__ dirs and {} .pyc files").format(removed_pycache, removed_pyc))
            self.log(_("Aggressive cleanup complete."))
            
            self.log(_("Python environment ready"))
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(_("Python setup timed out"))
        except Exception as e:
            self.log(_("Python setup failed: {}").format(e))
            raise

    def _use_system_pygobject(self, venv_path):
        """
        Fallback: Copy system PyGObject to venv when pip installation fails.
        """
        try:
            self.log(_("Copying system gi module to virtualenv..."))
            
            # Detect Python version
            py_cmd = ["python3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]
            result = self._run_command(py_cmd, capture_output=True, timeout=10)
            
            if result.returncode == 0:
                py_version = f"python{result.stdout.strip()}"
            else:
                py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            
            # Source: system site-packages (Debian/Ubuntu and Red Hat/AlmaLinux paths)
            system_gi_paths = [
                # Debian/Ubuntu paths
                f'/usr/lib/{py_version}/site-packages/gi',
                f'/usr/lib/{py_version}/dist-packages/gi',
                '/usr/lib/python3/dist-packages/gi',
                '/usr/lib/python3/site-packages/gi',
                # Red Hat/AlmaLinux/Fedora paths
                f'/usr/lib64/{py_version}/site-packages/gi',
                '/usr/lib64/python3/site-packages/gi',
            ]

            source_gi = None
            for path in system_gi_paths:
                check_cmd = ["test", "-d", path]
                result = self._run_command(check_cmd, timeout=5)
                if result.returncode == 0:
                    source_gi = path
                    break
            
            if not source_gi:
                self.log(_("Error: System gi module not found"))
                return False
            
            # Destination: venv site-packages
            venv_site_packages = venv_path / "lib" / py_version / "site-packages"
            dest_gi = venv_site_packages / "gi"
            
            # Copy using container command
            copy_script = f"""#!/bin/bash
set -e
mkdir -p "{venv_site_packages}"

# Copy gi folder
cp -r "{source_gi}" "{dest_gi}"

# Copy _gi*.so files from dist-packages (Debian/Ubuntu)
for gi_file in /usr/lib/{py_version}/dist-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib/python3/dist-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

# Copy _gi*.so files from site-packages (Arch/Fedora)
for gi_file in /usr/lib/{py_version}/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib/python3/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

# Copy _gi*.so files from lib64/site-packages (Red Hat/AlmaLinux/Fedora)
for gi_file in /usr/lib64/{py_version}/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib64/python3/site-packages/_gi*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

# Copy _gi_cairo*.so if exists (Debian/Ubuntu)
for gi_file in /usr/lib/{py_version}/dist-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib/python3/dist-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

# Copy _gi_cairo*.so from site-packages (Arch/Fedora)
for gi_file in /usr/lib/{py_version}/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib/python3/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

# Copy _gi_cairo*.so from lib64/site-packages (Red Hat/AlmaLinux/Fedora)
for gi_file in /usr/lib64/{py_version}/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

for gi_file in /usr/lib64/python3/site-packages/_gi_cairo*.so; do
    [ -f "$gi_file" ] && cp "$gi_file" "{venv_site_packages}/" && echo "Copied: $(basename $gi_file)"
done

echo "System PyGObject copied successfully"
"""
            
            script_path = self.build_dir / "copy_pygobject.sh"
            with open(script_path, "w") as f:
                f.write(copy_script)
            make_executable(script_path)
            
            result = self._run_command([str(script_path)], timeout=60)
            
            if result.returncode == 0:
                self.log(_("System PyGObject copied successfully"))
                return True
            else:
                self.log(_("Failed to copy system PyGObject"))
                return False
                
        except Exception as e:
            self.log(_("Error using system PyGObject: {}").format(e))
            return False

    def _detect_gui_dependencies(self, app_info: dict):
        """
        Detect GUI framework dependencies by analyzing Python source code.
        Returns dict with framework info: {'gtk3': True, 'gtk4': True, etc}
        """
        self.log(_("Detecting GUI framework dependencies..."))
        dependencies = {}
        
        # Find Python files in the original project source, not the AppDir
        python_files = []
        structure_analysis = app_info.get('structure_analysis', {})
        project_root = structure_analysis.get('project_root')

        if project_root and Path(project_root).exists():
            self.log(_("Analyzing Python files in: {}").format(project_root))
            python_files = list(Path(project_root).rglob("*.py"))
        else:
            # Fallback if project root is not available
            executable_path = app_info.get('executable')
            if executable_path:
                executable_dir = Path(executable_path).parent
                self.log(_("Analyzing Python files in executable's directory: {}").format(executable_dir))
                python_files = list(executable_dir.rglob("*.py"))

        if not python_files:
            self.log(_("No Python files found for dependency detection"))
            return dependencies
        
        self.log(_("Analyzing {} Python files...").format(len(python_files)))
        
        # Patterns to detect GUI frameworks
        patterns = {
            'gtk3': [
                r"gi\.require_version\(['\"]Gtk['\"],\s*['\"]3\.0['\"]",
            ],
            'gtk4': [
                r"gi\.require_version\(['\"]Gtk['\"],\s*['\"]4\.0['\"]",
            ],
            'adwaita': [
                r"gi\.require_version\(['\"]Adw['\"],\s*['\"]1['\"]",
            ],
            'vte': [
                r"gi\.require_version\(['\"]Vte['\"],\s*['\"]3\.91['\"]",
                r"gi\.require_version\(['\"]Vte['\"],\s*['\"]2\.91['\"]",
            ],
            'libsecret': [
                r"gi\.require_version\(['\"]Secret['\"],\s*['\"]1['\"]",
                r"from gi\.repository import Secret",
                r"import.*Secret"
            ],
            'qt5': [
                r"from PyQt5",
                r"import PyQt5"
            ],
            'qt6': [
                r"from PyQt6",
                r"import PyQt6"
            ],
            'gstreamer-gtk': [
                # Detects modern GStreamer GTK4 integration via gtk4paintablesink
                # as well as the older GstGtk import.
                r"gtk4paintablesink",
                r"from gi\.repository import GstGtk",
                r"gi\.require_version\(['\"]GstGtk['\"],"
            ],
            'mpv': [
                r"import\s+mpv",
                r"from\s+mpv"
            ]
        }
        
        for py_file in python_files[:50]:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    for framework, pattern_list in patterns.items():
                        for pattern in pattern_list:
                            if re.search(pattern, content):
                                dependencies[framework] = True
                                self.log(_("  Detected: {}").format(framework.upper()))
                                break
            except Exception:
                continue
        
        return dependencies
    
    def _detect_gi_usage(self, app_info: dict):
        """
        Detect if the application uses PyGObject (gi module).
        Returns True if gi is imported anywhere in the code.
        """
        self.log(_("Checking for PyGObject usage..."))
        
        python_files = []
        structure_analysis = app_info.get('structure_analysis', {})
        project_root = structure_analysis.get('project_root')

        if project_root and Path(project_root).exists():
            python_files = list(Path(project_root).rglob("*.py"))
        else:
            # Fallback if project root is not available
            executable_path = app_info.get('executable')
            if executable_path:
                executable_dir = Path(executable_path).parent
                python_files = list(executable_dir.rglob("*.py"))

        if not python_files:
            return False
        
        import re
        gi_patterns = [
            r'\bimport\s+gi\b',
            r'\bfrom\s+gi\b',
            r'\bfrom\s+gi\.repository\b'
        ]
        
        for py_file in python_files[:50]:
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    for pattern in gi_patterns:
                        if re.search(pattern, content):
                            self.log(_("  Detected PyGObject usage"))
                            return True
            except Exception:
                continue
        
        return False
    
    def _ensure_native_dependencies(self, dependencies):
        """
        Install native GUI libraries in container if missing.
        """
        if not dependencies:
            return
        
        self.log(_("Ensuring native GUI dependencies..."))
        
        # Detect package manager based on build environment
        package_manager = 'apt'  # default
        if self.build_environment:
            if any(distro in self.build_environment.lower() for distro in ['fedora', 'alma', 'rhel', 'centos']):
                package_manager = 'dnf'
        
        # Package mappings per distro family
        debian_packages = {
            'gtk3': ['libgtk-3-0', 'gir1.2-gtk-3.0', 'libgirepository-1.0-1', 'python3-gi', 'python3-gi-cairo'],
            'gtk4': ['libgtk-4-1', 'gir1.2-gtk-4.0', 'libgirepository-1.0-1', 'python3-gi', 'python3-gi-cairo'],
            'adwaita': ['libadwaita-1-0', 'gir1.2-adw-1'],
            'vte': ['libvte-2.91-0', 'gir1.2-vte-2.91', 'libvte-2.91-gtk4-0', 'gir1.2-vte-3.91', 'libvte-2.91-gtk4-dev'],
            'libsecret': ['libsecret-1-0', 'gir1.2-secret-1'],
            'qt5': ['libqt5core5a', 'libqt5gui5', 'libqt5widgets5'],
            'qt6': ['libqt6core6', 'libqt6gui6', 'libqt6widgets6']
        }

        rpm_packages = {
            'gtk3': ['gtk3', 'gtk3-devel', 'gobject-introspection', 'python3-gobject', 'python3-cairo'],
            'gtk4': ['gtk4', 'gtk4-devel', 'gobject-introspection', 'python3-gobject', 'python3-cairo'],
            'adwaita': ['libadwaita', 'libadwaita-devel'],
            'vte': ['vte291', 'vte291-devel'],
            'libsecret': ['libsecret', 'libsecret-devel'],
            'qt5': ['qt5-qtbase', 'qt5-qtbase-devel'],
            'qt6': ['qt6-qtbase', 'qt6-qtbase-devel']
        }
        
        package_map = debian_packages if package_manager == 'apt' else rpm_packages
        
        # Add specific package maps for non-GUI dependencies like media libraries
        debian_media_packages = {
            'mpv': ['libmpv-dev'],
        }
        rpm_media_packages = {
            'mpv': ['mpv-libs-devel'],
        }
        media_package_map = debian_media_packages if package_manager == 'apt' else rpm_media_packages

        packages_needed = []
        for fw in dependencies.keys():
            if fw in package_map:
                packages_needed.extend(package_map[fw])
            # Check for media dependencies as well
            if fw in media_package_map:
                packages_needed.extend(media_package_map[fw])
        
        packages_needed = list(set(packages_needed))
        self.log(_("Required packages: {}").format(', '.join(packages_needed)))
        
        # Check which packages are actually missing from the container
        packages_to_install = []
        self.log(_("Checking for missing packages in the container..."))
        for pkg in packages_needed:
            # Use dpkg-query to check package status. It returns non-zero if not installed.
            check_cmd = ["dpkg-query", "-W", "-f='${Status}'", pkg]
            result = self._run_command(check_cmd, capture_output=True)
            # A successful query contains 'install ok installed'
            if result.returncode != 0 or 'install ok installed' not in result.stdout:
                packages_to_install.append(pkg)
                self.log(f"  -> Package '{pkg}' is missing.")

        # If there's nothing to install, we can stop here.
        if not packages_to_install:
            self.log(_("All required native dependencies are already installed."))
            return
        
        self.log(_("Packages to install: {}").format(', '.join(packages_to_install)))
        
        # Check for GTK4 on Ubuntu 20.04
        if 'gtk4' in dependencies:
            if self.build_environment and 'ubuntu-20.04' in self.build_environment.lower():
                raise RuntimeError(_(
                    "GTK4 application detected, but Ubuntu 20.04 does not have GTK4 in repositories.\n\n"
                    "Solution: Use Ubuntu 22.04 or 24.04 container instead.\n"
                    "Go to: Build Environment → Select a newer Ubuntu version"
                ))
            
            self.log(_("Note: GTK4 detected - using modern container recommended"))
        
        # Update repos first
        self.log(_("Updating package lists..."))
        if package_manager == 'apt':
            self._run_command(["sudo", "apt-get", "update"], timeout=120)
        else:
            self._run_command(["sudo", "dnf", "check-update"], timeout=120)
        
        # Install packages
        self.log(_("Installing GUI libraries..."))
        if package_manager == 'apt':
            install_cmd = ["sudo", "apt-get", "install", "-y", "--no-install-recommends"] + packages_to_install
        else:
            install_cmd = ["sudo", "dnf", "install", "-y"] + packages_to_install
        
        self.log(_("Running install command: {}").format(' '.join(install_cmd)))
        result = self._run_command(install_cmd, timeout=300)
        
        if result.returncode == 0:
            self.log(_("Successfully installed GUI dependencies in container."))
        else:
            # If the main install command fails, raise a clear error.
            error_message = result.stderr or result.stdout or _("Unknown error from package manager.")
            self.log(_("Error installing dependencies in container:"))
            self.log(error_message)
            raise RuntimeError(
                _("Failed to install required build dependencies in the container: {pkgs}\n\n"
                  "Error details:\n{err}").format(pkgs=', '.join(packages_needed), err=error_message)
            )

    def _bundle_external_binaries(self):
        """Bundle external binaries (ffmpeg, etc) using linuxdeploy"""
        self.log(_("Processing external binaries with linuxdeploy..."))
        
        if not self.download_linuxdeploy():
            self.log(_("Warning: linuxdeploy not available, skipping binary bundling"))
            return

        try:
            # Backup original wrapper BEFORE linuxdeploy runs
            original_wrapper = self.appdir_path / "usr" / "bin" / self.app_info['executable_name']
            wrapper_backup = None

            if original_wrapper.exists() and not original_wrapper.is_symlink():
                wrapper_backup = original_wrapper.parent / f"{original_wrapper.name}.backup"
                shutil.copy2(original_wrapper, wrapper_backup)
                self.log(_("Backed up original wrapper: {}").format(original_wrapper.name))
            
            # Backup custom AppRun BEFORE linuxdeploy runs
            custom_apprun = self.appdir_path / "AppRun"
            apprun_backup = None
            
            if custom_apprun.exists() and not custom_apprun.is_symlink():
                try:
                    with open(custom_apprun, 'r') as f:
                        content = f.read()
                    if 'Setup Python virtualenv if it exists' in content:
                        apprun_backup = self.appdir_path / "AppRun.backup"
                        shutil.copy2(custom_apprun, apprun_backup)
                        make_executable(apprun_backup)
                        self.log(_("Backed up custom AppRun"))
                except Exception:
                    pass
            
            desktop_files = list((self.appdir_path / "usr/share/applications").glob("*.desktop"))
            if not desktop_files:
                self.log(_("Warning: No .desktop file found, skipping linuxdeploy"))
                return
            
            desktop_file_path = desktop_files[0]
            
            # Detect binaries to bundle
            detected_binaries = self._detect_binary_dependencies()
            
            cmd = [
                self.linuxdeploy_path,
                "--appdir", str(self.appdir_path),
                "--desktop-file", str(desktop_file_path),
            ]
            
            cmd.append("--create-desktop-file")
            
            # Add each detected binary
            for binary in detected_binaries:
                if binary in ['sh', 'bash']:
                    continue
                
                if SYSTEM_BINARIES.get(binary, {}).get('manage_libs_manually'):
                    self.log(_("Skipping copy of '{}' executable, as it is treated as a library provider.").format(binary))
                    continue
                    
                system_bin = shutil.which(binary)
                if system_bin:
                    dest = self.appdir_path / "usr" / "bin" / binary
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copy2(system_bin, dest)
                        make_executable(dest)
                    
                    cmd.extend(["--executable", str(dest)])
                    self.log(_("Will bundle: {}").format(binary))
            
            # Skip if no binaries or plugins to bundle
            if len(cmd) <= 4:
                self.log(_("No external binaries or plugins to process with linuxdeploy."))
                return
            
            env = os.environ.copy()
            env["DISABLE_COPYRIGHT_FILES_DEPLOYMENT"] = "1"
            env["NO_STRIP"] = "1"
            
            self.log(_("Running linuxdeploy..."))
            self.update_progress(65, _("Bundling binary dependencies..."))
            
            if self.container_name:
                self.log(_("Note: linuxdeploy runs locally but accesses container files"))
            
            process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, 
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)

            for line in iter(process.stdout.readline, ''):
                log_line = line.strip()
                if log_line and not log_line.startswith('ERROR:'):
                    self.log(f"[linuxdeploy] {log_line}")
            
            process.stdout.close()
            return_code = process.wait()

            if return_code != 0:
                self.log(_("Warning: linuxdeploy had issues but continuing..."))
            else:
                self.log(_("External binaries bundled successfully"))

            # Restore custom AppRun FIRST
            if apprun_backup and apprun_backup.exists():
                if custom_apprun.exists():
                    custom_apprun.unlink()
                
                shutil.copy2(apprun_backup, custom_apprun)
                make_executable(custom_apprun)
                apprun_backup.unlink()
                self.log(_("Restored custom AppRun"))

            # Restore original wrapper
            if wrapper_backup and wrapper_backup.exists():
                if original_wrapper.exists():
                    original_wrapper.unlink()
                
                shutil.copy2(wrapper_backup, original_wrapper)
                make_executable(original_wrapper)
                wrapper_backup.unlink()
                self.log(_("Restored original wrapper: {}").format(original_wrapper.name))
                
            # Generate icon cache inside the AppDir for better integration
            self.log(_("Generating icon cache inside AppDir..."))
            hicolor_dir = self.appdir_path / "usr/share/icons/hicolor"
            if hicolor_dir.is_dir():
                try:
                    # The command must be run from within the container to find gtk-update-icon-cache
                    cache_cmd = [
                        "gtk-update-icon-cache",
                        "-f",
                        "-t",
                        str(hicolor_dir)
                    ]
                    result = self._run_command(cache_cmd, timeout=60)
                    if result.returncode == 0:
                        self.log(_("Successfully generated icon-theme.cache."))
                    else:
                        self.log(_("Warning: Failed to generate icon-theme.cache. Icons may not appear in menus."))
                        self.log(result.stderr or result.stdout)
                except Exception as cache_error:
                    self.log(_("Warning: Could not run gtk-update-icon-cache: {}").format(cache_error))

        except Exception as e:
            self.log(_("Warning: Binary bundling failed: {}").format(e))

    def _copy_system_libraries(self):
        """
        Copy required system .so libraries to AppDir, separating conflicting ones.
        """
        lib_dir = self.appdir_path / "usr" / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        
        fallback_lib_dir = self.appdir_path / "usr" / "lib-fallback"
        fallback_lib_dir.mkdir(parents=True, exist_ok=True)

        # Build the list of required libraries dynamically
        required_libs = []
        conflicting_libs = []
        selected_deps = self.app_info.get('selected_dependencies', [])
        
        for dep_key in selected_deps:
            if dep_key in SYSTEM_DEPENDENCIES:
                dep_info = SYSTEM_DEPENDENCIES[dep_key]
                if dep_info.get('conflicting', False):
                    conflicting_libs.extend(dep_info.get('libs', []))
                else:
                    required_libs.extend(dep_info.get('libs', []))
        
        # Remove duplicates
        required_libs = sorted(list(set(required_libs)))
        conflicting_libs = sorted(list(set(conflicting_libs)))

        if required_libs:
            self.log(_("Copying standard system libraries: {}").format(', '.join(required_libs)))
            self._execute_library_copy(required_libs, lib_dir)

        if conflicting_libs:
            self.log(_("Copying conflicting system libraries to fallback dir: {}").format(', '.join(conflicting_libs)))
            self._execute_library_copy(conflicting_libs, fallback_lib_dir)

    def _execute_library_copy(self, lib_patterns, dest_dir):
        """
        Helper function to find and copy the correct SONAME-versioned library file.
        This copies only the single, correctly named file needed for compatibility,
        replicating the structure of a known-good AppImage.
        """
        system_lib_paths = [
            '/usr/lib/x86_64-linux-gnu',
            '/usr/lib64',
            '/lib/x86_64-linux-gnu',
            '/lib64',
            '/usr/lib',
            '/lib',
        ]

        self.log(_("Generating script to copy libraries to {}...").format(dest_dir))
        
        script_lines = ["#!/bin/bash", "set -e", f"DEST_DIR='{dest_dir}'", ""]
        
        for pattern in lib_patterns:
            script_lines.extend([
                f'echo "--- Processing {pattern} ---"',
                "FOUND=0",
                "for search_path in " + " ".join(f'"{p}"' for p in system_lib_paths) + "; do",
                # Find the base library file (shortest name, typically the main symlink)
                "    BASE_FILE=$(find \"$search_path\" -maxdepth 1 -name " + f"'{pattern}'" + " | sort | head -n 1)",
                '    if [ -n "$BASE_FILE" ] && [ -e "$BASE_FILE" ]; then',
                # Use readelf to find the exact SONAME the system needs
                "        SONAME=$(readelf -d \"$BASE_FILE\" 2>/dev/null | grep '(SONAME)' | awk -F'[][]' '{print $2}')",
                # Determine the final target file to copy
                '        if [ -n "$SONAME" ]; then',
                '            TARGET_FILE="$(dirname "$BASE_FILE")/$SONAME"',
                '        else',
                # If no SONAME, it's a non-versioned lib like libffi.so, use the base file
                '            TARGET_FILE="$BASE_FILE"',
                '        fi',
                
                '        if [ -e "$TARGET_FILE" ]; then',
                '            echo "Copying $(basename "$TARGET_FILE") from $search_path..."',
                # Use cp -L to copy the final content with the correct SONAME
                '            cp -vL "$TARGET_FILE" "$DEST_DIR/"',
                '            FOUND=1',
                '            break # Found it, stop searching other paths',
                '        fi',
                '    fi',
                "done",
                'if [ $FOUND -eq 0 ]; then',
                f"    echo '    -> {pattern} not found.'",
                "fi",
                ""
            ])

        script_content = "\n".join(script_lines)
        script_path = self.build_dir / f"copy_libs_{dest_dir.name}.sh"
        
        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)

        self.log(_("Executing library copy script..."))
        result = self._run_command([str(script_path)])

        if result.stdout:
            for line in result.stdout.splitlines():
                self.log(f"[copy_libs] {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                self.log(f"[copy_libs ERROR] {line}")

        if result.returncode != 0:
            self.log(_("Warning: Library copy script finished with errors."))
        else:
            self.log(_("Library copy script finished successfully."))
    
    def _copy_typelibs(self):
        """
        Copy GObject Introspection typelib files based on selected dependencies.
        """
        typelib_dir = self.appdir_path / "usr" / "lib" / "girepository-1.0"
        typelib_dir.mkdir(parents=True, exist_ok=True)

        # Build the list of required typelibs dynamically
        required_typelibs = []
        selected_deps = self.app_info.get('selected_dependencies', [])
        for dep_key in selected_deps:
            if dep_key in SYSTEM_DEPENDENCIES:
                required_typelibs.extend(SYSTEM_DEPENDENCIES[dep_key].get('typelibs', []))

        # Remove duplicates
        required_typelibs = sorted(list(set(required_typelibs)))
        if not required_typelibs:
            self.log(_("No typelibs selected for inclusion."))
            return

        self.log(_("Copying selected typelibs: {}").format(', '.join(required_typelibs)))

        system_typelib_paths = [
            '/usr/lib/x86_64-linux-gnu/girepository-1.0',
            '/usr/lib/girepository-1.0',
            '/usr/lib64/girepository-1.0',
        ]
        
        self.log(_("Generating script to copy typelibs..."))
        
        script_lines = [
            "#!/bin/bash",
            "set -e",
            f"DEST_DIR='{typelib_dir}'",
            "mkdir -p \"$DEST_DIR\"",
            "COPIED=0",
            ""
        ]
        
        for typelib in required_typelibs:
            script_lines.append(f'echo "Searching for {typelib}..."')
            script_lines.append("FOUND=0")
            for search_path in system_typelib_paths:
                script_lines.append(f'if [ -f "{search_path}/{typelib}" ]; then')
                script_lines.append(f'    cp -v "{search_path}/{typelib}" "$DEST_DIR/"')
                script_lines.append('    COPIED=$((COPIED + 1))')
                script_lines.append('    FOUND=1')
                script_lines.append('fi')
            script_lines.append('if [ $FOUND -eq 0 ]; then')
            script_lines.append(f'    echo "  -> {typelib} not found (may be optional)"')
            script_lines.append('fi')
            script_lines.append("")
        
        script_lines.append('echo "Copied $COPIED typelib files"')
        
        script_content = "\n".join(script_lines)
        script_path = self.build_dir / "copy_typelibs.sh"
        
        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)
        
        self.log(_("Executing typelib copy script..."))
        result = self._run_command([str(script_path)])
        
        if result.stdout:
            for line in result.stdout.splitlines():
                self.log(f"[typelibs] {line}")
        
        if result.returncode != 0:
            self.log(_("Warning: Some typelibs may not have been copied"))
        else:
            self.log(_("Typelib copy complete"))
            
    def _copy_gstreamer_plugins(self):
        """
        Copy only essential GStreamer plugins based on detected usage.
        This replaces the linuxdeploy plugin that copies everything.
        """
        # Check if GStreamer is being used
        selected_deps = self.app_info.get('selected_dependencies', [])
        if 'gstreamer-gtk' not in selected_deps:
            return
            
        self.log(_("Copying essential GStreamer plugins..."))
        
        # Define plugin profiles
        GSTREAMER_PLUGIN_PROFILES = {
            'audio-preview': [
                # Core elements
                'libgstcoreelements.so',
                'libgstautodetect.so',
                'libgstvolume.so',
                'libgstplayback.so',
                'libgsttypefindfunctions.so',
                # Audio decoders for preview
                'libgstaudioparsers.so',
                'libgstaudioconvert.so',
                'libgstaudioresample.so',
            ],
            'video-playback': [
                # Core elements
                'libgstcoreelements.so',
                'libgstautodetect.so',
                'libgstplayback.so',
                'libgsttypefindfunctions.so',
                # Video elements
                'libgstvideoconvert.so',
                'libgstvideoscale.so',
                'libgstvideorate.so',
                'libgstvideofilter.so',
                'libgstvideobalance.so',
                # GTK4 sink
                'libgstgtk4.so',
                # Audio elements
                'libgstaudioconvert.so',
                'libgstaudioresample.so',
                'libgstvolume.so',
                # Container parsers
                'libgstmatroska.so',
                'libgstisomp4.so',
                'libgstavi.so',
                # Basic decoders
                'libgstaudioparsers.so',
                'libgstvideoparsersbad.so',
            ]
        }
        
        # Detect which profile to use based on app analysis
        profile_to_use = 'audio-preview'  # default
        
        # Check if video elements are used
        structure_analysis = self.app_info.get('structure_analysis', {})
        if structure_analysis:
            project_root = structure_analysis.get('project_root')
            if project_root:
                # Look for gtk4paintablesink usage
                try:
                    import subprocess
                    result = subprocess.run(
                        ['grep', '-r', 'gtk4paintablesink', project_root, '--include=*.py'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0 and result.stdout:
                        profile_to_use = 'video-playback'
                        self.log(_("Detected video playback requirements"))
                except:
                    pass
        
        # Get plugins to copy
        plugins_to_copy = GSTREAMER_PLUGIN_PROFILES.get(profile_to_use, [])
        
        # Create plugin directory
        plugin_dir = self.appdir_path / "usr" / "lib" / "gstreamer-1.0"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        
        # System paths where plugins might be
        system_plugin_paths = [
            '/usr/lib/x86_64-linux-gnu/gstreamer-1.0',
            '/usr/lib64/gstreamer-1.0',
            '/usr/lib/gstreamer-1.0',
        ]
        
        # Copy script
        script_lines = [
            "#!/bin/bash",
            "set -e",
            f"DEST_DIR='{plugin_dir}'",
            "COPIED=0",
            "",
            f"echo 'Using GStreamer profile: {profile_to_use}'",
            ""
        ]
        
        for plugin in plugins_to_copy:
            script_lines.append(f'# Searching for {plugin}')
            for search_path in system_plugin_paths:
                script_lines.append(f'if [ -f "{search_path}/{plugin}" ]; then')
                script_lines.append(f'    cp -v "{search_path}/{plugin}" "$DEST_DIR/"')
                script_lines.append('    COPIED=$((COPIED + 1))')
                script_lines.append('    break')
                script_lines.append('fi')
            script_lines.append("")
        
        script_lines.append('echo "Copied $COPIED GStreamer plugins"')
        script_lines.append(f'echo "Total size: $(du -sh "$DEST_DIR" | cut -f1)"')
        
        script_content = "\n".join(script_lines)
        script_path = self.build_dir / "copy_gstreamer_plugins.sh"
        
        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)
        
        self.log(_("Copying GStreamer plugins..."))
        result = self._run_command([str(script_path)])
        
        if result.stdout:
            for line in result.stdout.splitlines():
                self.log(f"[gst-plugins] {line}")
                
        # Set GST_PLUGIN_PATH in AppRun will be handled by existing AppRun template
        
        self.log(_("GStreamer plugin copying complete"))
        
    def _copy_mpv_config(self):
        """Copies MPV configuration files if MPV is a detected dependency."""
        selected_deps = self.app_info.get('selected_dependencies', [])
        if 'mpv' not in selected_deps:
            return

        self.log("Copying MPV configuration files...")
        
        system_mpv_paths = [
            '/etc/mpv',
            '/usr/share/mpv',
        ]
        
        dest_dir = self.appdir_path / "usr" / "share" / "mpv"
        dest_dir.mkdir(parents=True, exist_ok=True)

        copied = False
        for path in system_mpv_paths:
            script = f"""
            if [ -d "{path}" ]; then
                echo "Found MPV config at {path}"
                cp -a "{path}"/* "{dest_dir}/"
                exit 0
            fi
            """
            result = self._run_command(['bash', '-c', script])
            if result.returncode == 0:
                self.log(f"MPV config copied from {path}")
                copied = True
                break
        
        if not copied:
            self.log("Warning: Could not find MPV configuration files to copy.")
            
    def _copy_symbolic_icons(self):
        """
        Copy Adwaita symbolic icons for UI elements (folder, refresh, home, etc).
        These small icons (~2.6MB) ensure UI elements display correctly across all systems.
        Automatically detects if running in container or local and copies from appropriate source.
        """
        self.log(_("Copying Adwaita symbolic icons..."))
        
        icons_dir = self.appdir_path / "usr" / "share" / "icons" / "Adwaita"
        icons_dir.mkdir(parents=True, exist_ok=True)
        
        symbolic_dest = icons_dir / "symbolic"
        
        # Check if already copied
        if symbolic_dest.exists() and (symbolic_dest / "ui").exists():
            self.log(_("Symbolic icons already present"))
            return
        
        # Determine source path based on execution environment
        if self.container_name:
            source_info = "container"
            source_path = "/usr/share/icons/Adwaita/symbolic"
        else:
            source_info = "host system"
            source_path = "/usr/share/icons/Adwaita/symbolic"
        
        self.log(_("Copying symbolic icons from {}...").format(source_info))
        
        # Script to copy symbolic icons
        script_lines = [
            "#!/bin/bash",
            "set -e",
            f"SOURCE='{source_path}'",
            f"DEST='{symbolic_dest}'",
            "",
            "if [ ! -d \"$SOURCE\" ]; then",
            "    echo 'ERROR: Adwaita symbolic icons not found at $SOURCE'",
            "    exit 1",
            "fi",
            "",
            "echo 'Copying symbolic icons...'",
            "cp -r \"$SOURCE\" \"$DEST\"",
            "",
            "# Count copied icons",
            "ICON_COUNT=$(find \"$DEST\" -name '*.svg' | wc -l)",
            "echo \"Copied $ICON_COUNT symbolic icons (~2.6MB)\"",
        ]
        
        script_content = "\n".join(script_lines)
        script_path = self.build_dir / "copy_symbolic_icons.sh"
        
        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)
        
        self.log(_("Executing symbolic icons copy script..."))
        result = self._run_command([str(script_path)])
        
        if result.stdout:
            for line in result.stdout.splitlines():
                self.log(f"[icons] {line}")
        
        if result.returncode != 0:
            self.log(_("Warning: Failed to copy symbolic icons"))
        else:
            # Create custom index.theme with ONLY symbolic directories for Adwaita
            self.log(_("Creating custom index.theme for Adwaita symbolic icons..."))
            
            icons_dir = self.appdir_path / "usr" / "share" / "icons" / "Adwaita"
            index_file = icons_dir / "index.theme"
            
            if icons_dir.exists():
                custom_index = """[Icon Theme]
Name=Adwaita
Comment=Adwaita icon theme (symbolic only)
Inherits=hicolor

# Only symbolic directory included
Directories=symbolic/actions,symbolic/apps,symbolic/categories,symbolic/devices,symbolic/emblems,symbolic/emotes,symbolic/legacy,symbolic/mimetypes,symbolic/places,symbolic/status,symbolic/ui

[symbolic/actions]
Context=Actions
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/apps]
Context=Applications
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/categories]
Context=Categories
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/devices]
Context=Devices
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emblems]
Context=Emblems
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emotes]
Context=Emotes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/legacy]
Context=Legacy
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/mimetypes]
Context=MimeTypes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/places]
Context=Places
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/status]
Context=Status
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/ui]
Context=UI
Size=16
MinSize=16
MaxSize=512
Type=Scalable
"""
                
                with open(index_file, 'w') as f:
                    f.write(custom_index)
                
                self.log("Created custom index.theme for Adwaita")
            
            self.log(_("Symbolic icons copied successfully"))
            
    def _copy_papirus_symbolic_icons(self):
        """
        Copy Papirus symbolic icons for GTK applications.
        Copies both Papirus and Papirus-Dark themes (excluding apps/ category).
        Total size: ~6.4MB for comprehensive icon coverage.
        """
        self.log(_("Copying Papirus symbolic icons..."))
        
        # Categories to copy (excluding 'apps' to save space)
        categories = [
            'actions',      # 1.4MB - UI actions (pin, refresh, delete, etc)
            'categories',   # 96K  - preferences, system categories
            'devices',      # 308K - computer, phone, printer icons
            'emblems',      # 44K  - symbolic badges
            'emotes',       # 108K - emoji fallbacks
            'mimetypes',    # 108K - file type icons
            'places',       # 112K - folder, home, network icons
            'status',       # 1.2MB - info, warning, error, battery, etc
            'up-to-32',     # 4K   - icon cache/metadata
        ]
        
        # Themes to copy (light and dark)
        themes = ['Papirus', 'Papirus-Dark']
        
        icons_base_dir = self.appdir_path / "usr" / "share" / "icons"
        icons_base_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if already copied
        papirus_test = icons_base_dir / "Papirus" / "symbolic" / "actions"
        if papirus_test.exists() and list(papirus_test.glob("*.svg")):
            self.log(_("Papirus symbolic icons already present"))
            return
        
        # Determine source path
        if self.container_name:
            source_base = "/usr/share/icons"
        else:
            source_base = "/usr/share/icons"
        
        self.log(_("Copying Papirus and Papirus-Dark symbolic icons..."))
        
        # Build copy script
        script_lines = [
            "#!/bin/bash",
            "set -e",
            f"SOURCE_BASE='{source_base}'",
            f"DEST_BASE='{icons_base_dir}'",
            "",
            "COPIED=0",
            "THEMES_COPIED=0",
            "",
        ]
        
        # Copy each theme
        for theme in themes:
            script_lines.extend([
                f"# Process {theme} theme",
                f"SOURCE_THEME=\"$SOURCE_BASE/{theme}\"",
                f"DEST_THEME=\"$DEST_BASE/{theme}\"",
                "",
                "if [ ! -d \"$SOURCE_THEME\" ]; then",
                f"    echo 'Warning: {theme} not found in container - skipping'",
                "else",
                "    THEMES_COPIED=$((THEMES_COPIED + 1))",
                "    mkdir -p \"$DEST_THEME\"",
                "",
                "    # Copy index.theme file",
                "    if [ -f \"$SOURCE_THEME/index.theme\" ]; then",
                "        cp \"$SOURCE_THEME/index.theme\" \"$DEST_THEME/\"",
                f"        echo 'Copied {theme}/index.theme'",
                "    fi",
                "",
            ])
            
            # Copy each category
            for category in categories:
                script_lines.extend([
                    f"    # Copy symbolic/{category}/",
                    f"    if [ -d \"$SOURCE_THEME/symbolic/{category}\" ]; then",
                    f"        mkdir -p \"$DEST_THEME/symbolic/{category}\"",
                    f"        cp -r \"$SOURCE_THEME/symbolic/{category}\"/* \"$DEST_THEME/symbolic/{category}/\" 2>/dev/null || true",
                    "        COUNT=$(find \"$DEST_THEME/symbolic/" + category + "\" -name '*.svg' 2>/dev/null | wc -l)",
                    "        COPIED=$((COPIED + COUNT))",
                    f"        echo '  Copied {category}/: '$COUNT' icons'",
                    "    fi",
                    "",
                ])
            
            script_lines.append("fi")
            script_lines.append("")
        
        # Final summary
        script_lines.extend([
            "if [ $THEMES_COPIED -eq 0 ]; then",
            "    echo 'ERROR: No Papirus themes found in container'",
            "    echo 'Falling back to Adwaita icons...'",
            "    exit 1",
            "fi",
            "",
            "echo ''",
            "echo '=== Summary ==='",
            "echo \"Themes copied: $THEMES_COPIED/2\"",
            "echo \"Total icons: $COPIED\"",
            "echo \"Size: ~6.4MB\"",
        ])
        
        script_content = "\n".join(script_lines)
        script_path = self.build_dir / "copy_papirus_icons.sh"
        
        with open(script_path, "w") as f:
            f.write(script_content)
        make_executable(script_path)
        
        self.log(_("Executing Papirus icons copy script..."))
        result = self._run_command([str(script_path)])
        
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    self.log(f"[papirus] {line}")
        
        if result.returncode != 0:
            # Fallback to Adwaita if Papirus not available
            self.log(_("Warning: Papirus icons not available, falling back to Adwaita"))
            self._copy_symbolic_icons()
        else:
            # Create custom index.theme with ONLY symbolic directories for Papirus
            self.log(_("Creating custom index.theme for Papirus symbolic icons..."))
            
            for theme in ['Papirus', 'Papirus-Dark']:
                theme_dir = icons_base_dir / theme
                index_file = theme_dir / "index.theme"
                
                if theme_dir.exists():
                    inherits = "breeze,hicolor" if theme == "Papirus" else "breeze-dark,hicolor"
                    
                    custom_index = f"""[Icon Theme]
Name={theme}
Comment={theme} icon theme (symbolic only)
Inherits={inherits}

# Only symbolic directories included
Directories=symbolic/actions,symbolic/categories,symbolic/devices,symbolic/emblems,symbolic/emotes,symbolic/mimetypes,symbolic/places,symbolic/status,symbolic/up-to-32

[symbolic/actions]
Context=Actions
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/categories]
Context=Categories
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/devices]
Context=Devices
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emblems]
Context=Emblems
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/emotes]
Context=Emotes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/mimetypes]
Context=MimeTypes
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/places]
Context=Places
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/status]
Context=Status
Size=16
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/up-to-32]
Context=Status
Size=16
MinSize=16
MaxSize=32
Type=Scalable
"""
                    
                    with open(index_file, 'w') as f:
                        f.write(custom_index)
                    
                    self.log(f"Created custom index.theme for {theme}")
            
            self.log(_("Papirus symbolic icons copied successfully"))
                
    def _create_icon_symlinks(self):
        """Create icon symlinks in AppDir root matching desktop file name"""
        try:
            # Find icon in usr/share/icons/
            icons_dir = self.appdir_path / "usr" / "share" / "icons"
            if not icons_dir.exists():
                return
            
            icon_file = None
            for ext in ['.svg', '.png', '.xpm']:
                for found_icon in icons_dir.rglob(f"*{ext}"):
                    if found_icon.is_file():
                        icon_file = found_icon
                        break
                if icon_file:
                    break
            
            if not icon_file:
                self.log(_("No icon found in usr/share/icons"))
                return
            
            # Reliably find the main application's desktop file.
            main_desktop_file = None
            
            all_desktop_files = list((self.appdir_path / "usr/share/applications").glob("*.desktop"))

            # Strategy 1: Find a desktop file that was copied from the source project.
            # This is often the most reliable.
            if self.app_info.get('structure_analysis'):
                detected_desktops = self.app_info['structure_analysis']['detected_files'].get('desktop_files', [])
                if detected_desktops:
                    original_desktop_name = Path(detected_desktops[0]).name
                    for f in all_desktop_files:
                        if f.name == original_desktop_name:
                            main_desktop_file = f
                            break
            
            # Strategy 2: If not found, fall back to finding one that is not auto-generated.
            if not main_desktop_file:
                for f in all_desktop_files:
                    # Ignore files created by linuxdeploy for secondary binaries
                    if 'vainfo' not in f.name:
                        main_desktop_file = f
                        break
            
            # If still no file, we can't proceed.
            if not main_desktop_file:
                self.log(_("Warning: Could not reliably determine the main desktop file to update the icon path."))
                return

            self.log(_("Using main desktop file for icon association: {}").format(main_desktop_file.name))
            desktop_name = main_desktop_file.stem  # e.g., org.communitybig.ashyterm
            icon_extension = icon_file.suffix      # e.g., .svg
            
            # Create symlink in the root of the AppDir
            symlink_name = f"{desktop_name}{icon_extension}"
            symlink_path = self.appdir_path / symlink_name
            relative_icon_path = os.path.relpath(icon_file, self.appdir_path)
            
            if symlink_path.exists():
                symlink_path.unlink()
            symlink_path.symlink_to(relative_icon_path)
            
            self.log(_("Created root icon symlink: {} -> {}").format(symlink_name, relative_icon_path))
            
            # Update the Icon= line in the main desktop file to use the base name
            desktop_file_path = main_desktop_file # Use a variável correta
            with open(desktop_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Replace Icon= line with the name (without extension)
            import re
            content = re.sub(r'^Icon=.*$', f'Icon={desktop_name}', content, flags=re.MULTILINE)
            
            with open(desktop_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.log(_("Updated 'Icon=' in {} to: {}").format(desktop_file_path.name, desktop_name))
            
        except Exception as e:
            self.log(_("Warning: Failed to create icon symlinks: {}").format(e))
                    
    def download_linuxdeploy(self):
        """Download or find linuxdeploy"""
        self.log(_("Setting up linuxdeploy..."))
        
        try:
            # Check if linuxdeploy is already in PATH
            self.linuxdeploy_path = find_executable_in_path('linuxdeploy')
            if self.linuxdeploy_path:
                self.log(_("Found linuxdeploy: {}").format(self.linuxdeploy_path))
                return True
            
            # Check if already downloaded in build directory
            download_path = self.build_dir / "linuxdeploy-x86_64.AppImage"
            if download_path.exists():
                self.linuxdeploy_path = str(download_path)
                make_executable(download_path)
                return True

            # Download linuxdeploy
            url = "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
            
            self.log(_("Downloading linuxdeploy..."))
            
            def progress_cb(pct):
                self.update_progress(55 + int(pct * 0.05), _("Downloading linuxdeploy"))
                
            download_file(url, download_path, progress_cb)
            make_executable(download_path)
            
            self.linuxdeploy_path = str(download_path)
            return True
            
        except Exception as e:
            self.log(_("Failed to setup linuxdeploy: {}").format(e))
            return False

    def _detect_binary_dependencies(self):
        """Detect required system binaries by scanning project files using SYSTEM_BINARIES."""
        detected_binaries = set()
        
        # Always include common shell utilities
        detected_binaries.update(['sh', 'bash'])

        # Determine search path for source files
        source_path = None
        structure_analysis = self.app_info.get('structure_analysis', {})
        project_root = structure_analysis.get('project_root')
        if project_root and Path(project_root).exists():
            source_path = Path(project_root)
        elif self.app_info.get('executable'):
            source_path = Path(self.app_info['executable']).parent

        if not source_path:
            self.log(_("Warning: Could not determine source path for binary detection."))
            return list(detected_binaries)

        self.log(_("Scanning for binary dependencies in: {}").format(source_path))
        
        # Scan all relevant files (.py, .sh, scripts without extension)
        files_to_scan = list(source_path.rglob("*.py")) + \
                        list(source_path.rglob("*.sh"))

        for item in source_path.rglob("*"):
            if item.is_file() and not item.suffix and os.access(item, os.X_OK):
                files_to_scan.append(item)

        for file_path in set(files_to_scan):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                for key, info in SYSTEM_BINARIES.items():
                    keyword = info['detection_keyword']
                    if keyword in content:
                        binary_name = info['binary_name']
                        if binary_name not in detected_binaries:
                            self.log(_("  Detected dependency on binary: {}").format(binary_name))
                            detected_binaries.add(binary_name)
            except Exception:
                continue
        
        return list(detected_binaries)
    
    def _copy_external_dependencies(self):
        """Copy external binaries and their dependencies"""
        bin_dir = self.appdir_path / "usr" / "bin"
        lib_dir = self.appdir_path / "usr" / "lib"
        bin_dir.mkdir(parents=True, exist_ok=True)
        lib_dir.mkdir(parents=True, exist_ok=True)
        
        detected = self._detect_binary_dependencies()
        self.log(_("Detected binary dependencies: {}").format(', '.join(detected)))
        
        copied_count = 0
        missing = []
        
        for binary in detected:
            system_bin = shutil.which(binary)
            if system_bin:
                dest = bin_dir / binary
                if not dest.exists():
                    try:
                        shutil.copy2(system_bin, dest)
                        make_executable(dest)
                        self.log(_("Copied binary: {}").format(binary))
                        copied_count += 1
                        
                        # Copy binary's shared library dependencies
                        self._copy_binary_libs(system_bin, lib_dir)
                        
                    except Exception as e:
                        self.log(_("Warning: Failed to copy {}: {}").format(binary, e))
            else:
                missing.append(binary)
                self.log(_("Warning: {} not found in system").format(binary))
        
        if missing:
            self.log(_("Missing binaries (app may not work): {}").format(', '.join(missing)))
        
        self.log(_("Copied {} external binaries").format(copied_count))
        
    def _fix_wrapper_scripts(self):
        """Fix wrapper scripts to use relative paths instead of absolute"""
        bin_dir = self.appdir_path / "usr" / "bin"
        
        if not bin_dir.exists():
            return
        
        for script_file in bin_dir.glob("*"):
            if not script_file.is_file():
                continue
                
            try:
                with open(script_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Skip if not a shell script
                if not content.startswith('#!'):
                    continue
                
                modified = False
                
                # Replace absolute paths with relative
                if '/usr/share/' in content:
                    share_dir = self.appdir_path / "usr" / "share"
                    if share_dir.exists():
                        app_dirs = [d.name for d in share_dir.iterdir() if d.is_dir()]
                        
                        for app_dir in app_dirs:
                            old_path = f'/usr/share/{app_dir}/'
                            new_path = f'"$(dirname "$(dirname "$(readlink -f "$0")")")"/share/{app_dir}/'
                            
                            if old_path in content:
                                content = content.replace(old_path, new_path)
                                modified = True
                                self.log(_("Fixed absolute path in: {}").format(script_file.name))
                
                if modified:
                    with open(script_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                        
            except Exception as e:
                self.log(_("Warning: Could not fix script {}: {}").format(script_file.name, e))

    def _copy_binary_libs(self, binary_path, lib_dir):
        """Copy shared libraries required by a binary"""
        try:
            result = subprocess.run(['ldd', binary_path], 
                                capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return
                
            for line in result.stdout.split('\n'):
                if '=>' in line:
                    parts = line.split('=>')
                    if len(parts) == 2:
                        lib_path = parts[1].strip().split()[0]
                        
                        if lib_path and os.path.exists(lib_path):
                            lib_name = os.path.basename(lib_path)
                            dest = lib_dir / lib_name
                            
                            if not dest.exists():
                                try:
                                    shutil.copy2(lib_path, dest)
                                    self.log(_("  Copied lib: {}").format(lib_name))
                                except Exception:
                                    pass
                                    
        except Exception as e:
            self.log(_("Warning: Could not analyze dependencies for {}: {}").format(binary_path, e))

    def download_appimagetool(self):
        """Download or find appimagetool"""
        self.log(_("Setting up appimagetool..."))
        
        try:
            # Always check locally first
            self.appimagetool_path = find_executable_in_path('appimagetool')
            if self.appimagetool_path:
                self.log(_("Found appimagetool: {}").format(self.appimagetool_path))
                return True
                
            download_path = self.build_dir / "appimagetool-x86_64.AppImage"
            if download_path.exists():
                self.appimagetool_path = str(download_path)
                return True

            url = "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
            
            self.log(_("Downloading appimagetool..."))
            
            def progress_cb(pct):
                self.update_progress(75 + int(pct * 0.1), _("Downloading appimagetool"))
                
            download_file(url, download_path, progress_cb)
            make_executable(download_path)
            
            self.appimagetool_path = str(download_path)
            return True
            
        except Exception as e:
            self.log(_("Failed to setup appimagetool: {}").format(e))
            return False
            
    def build_appimage(self):
        """Build final AppImage"""
        self.log(_("Building AppImage..."))
        
        if not self.appimagetool_path:
            raise RuntimeError(_("appimagetool not available"))
            
        try:
            env = os.environ.copy()
            system_info = get_system_info()
            env['ARCH'] = system_info['architecture']
            
            output_dir = Path(self.app_info.get('output_dir') or Path.cwd())
            output_dir.mkdir(parents=True, exist_ok=True)

            output_name = f"{self.app_info['executable_name']}-{self.app_info['version']}-{system_info['architecture']}.AppImage"
            output_path = output_dir / output_name
            
            cmd = [self.appimagetool_path, str(self.appdir_path), str(output_path)]
            
            self.log(_("Running: {}").format(' '.join(cmd)))
            
            # appimagetool must run locally (needs FUSE)
            if self.container_name:
                self.log(_("Note: appimagetool runs locally (requires FUSE)"))
            
            result = subprocess.run(cmd, env=env, capture_output=True, 
                                   text=True, cwd=Path.cwd(), timeout=300)
            
            if result.returncode == 0 and output_path.exists():
                self.log(_("AppImage created: {}").format(output_path))
                return str(output_path)
            else:
                error_msg = result.stderr or result.stdout or _("Unknown error")
                self.log(f"appimagetool stdout:\n{result.stdout}")
                self.log(f"appimagetool stderr:\n{result.stderr}")
                raise RuntimeError(_("Build failed: {}").format(error_msg))
                
        except subprocess.TimeoutExpired:
            raise RuntimeError(_("Build timed out"))
        except Exception as e:
            self.log(_("Build failed: {}").format(e))
            raise
            
    def cleanup(self):
        """Clean up temporary files"""
        if self.build_dir and self.build_dir.exists():
            try:
                shutil.rmtree(self.build_dir)
                self.log(_("Cleaned up temporary files"))
            except Exception as e:
                self.log(_("Warning: Cleanup failed: {}").format(e))
                
    def build(self) -> str:
        """Main build process"""
        if not self.app_info:
            raise ValueError(_("Application information not set"))
        
        # Check for local build compatibility warning
        warning = self.get_compatibility_warning()
        if warning:
            self.log(_("⚠️ WARNING: Building locally - compatibility may be limited"))
            self.log(warning['message'])
        
        # Validate container if using one
        if self.build_environment:
            self.log(_("Validating build environment for {} application...").format(
                self.app_info.get('app_type', 'unknown')
            ))
            
            app_type = self.app_info.get('app_type', 'binary')
            validation_failed = []
            
            try:
                # Validate based on app type
                if app_type in ['python', 'python_wrapper', 'gtk', 'qt']:
                    # Validate Python
                    result = subprocess.run(
                        ['distrobox-enter', self.container_name, '--', 'python3', '--version'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        validation_failed.append('python3')
                    else:
                        self.log(_("✓ Python: {}").format(result.stdout.strip()))
                
                elif app_type == 'java':
                    # Validate Java
                    result = subprocess.run(
                        ['distrobox-enter', self.container_name, '--', 'java', '-version'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        validation_failed.append('java')
                    else:
                        self.log(_("✓ Java installed"))
                
                # Always validate basic tools in container
                for tool in ['git', 'file']:
                    result = subprocess.run(
                        ['distrobox-enter', self.container_name, '--', 'which', tool],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode != 0:
                        validation_failed.append(tool)
                    else:
                        self.log(_("✓ {} available").format(tool))
                
                if validation_failed:
                    raise RuntimeError(
                        _("Missing dependencies in container '{}':\n{}\n\n"
                        "Go to Build Environment → click Setup for this container.").format(
                            self.build_environment,
                            ', '.join(validation_failed)
                        )
                    )
                    
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    _("Container '{}' is not responding.").format(self.container_name)
                )
            
        try:
            self.cancel_requested = False
            
            # Initialize the build environment
            self.update_progress(0, _("Initializing..."))
            self.create_build_directory()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))
            self.create_appdir_structure()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))

            # Copy application source files
            self.copy_application_files()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))

            # Install native GUI dependencies in the container and download plugins
            gui_deps = self._detect_gui_dependencies(self.app_info)
            if gui_deps:
                self._ensure_native_dependencies(gui_deps)

            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))

            # Process the application icon
            self.process_application_icon()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))
            
            # Detect Python version from container
            if self.app_info.get('app_type') in ['python', 'python_wrapper', 'gtk', 'qt']:
                py_cmd = ["python3", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]
                result = self._run_command(py_cmd, capture_output=True, timeout=10)
                if result.returncode == 0:
                    self.python_version = result.stdout.strip()
                    self.log(_("Detected Python version for AppRun: {}").format(self.python_version))
                else:
                    import sys
                    self.python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                    self.log(_("Warning: Could not detect container Python, using builder Python: {}").format(self.python_version))

            # Create the custom AppRun and desktop files
            self.create_launcher_and_desktop_files()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))
            
            # Bundle all dependencies
            self.copy_dependencies()
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))
            
            # Download appimagetool
            if not self.download_appimagetool():
                raise RuntimeError(_("Failed to setup appimagetool"))
            if self.cancel_requested: raise RuntimeError(_("Build cancelled"))
                
            # Generate the final AppImage file
            self.update_progress(85, _("Building AppImage..."))
            appimage_path = self.build_appimage()
            
            self.update_progress(100, _("Build complete!"))
            return appimage_path
            
        except Exception as e:
            self.log(_("✗ Build failed: {}").format(e))
            raise
        finally:
            self.cleanup()
            
    def build_async(self, callback: Callable[[str, Exception], None]):
        """Build asynchronously"""
        def build_thread():
            try:
                result = self.build()
                callback(result, None)
            except Exception as e:
                callback(None, e)
                
        if self._build_thread and self._build_thread.is_alive():
            self.log(_("Build already in progress"))
            return self._build_thread
            
        self._build_thread = threading.Thread(target=build_thread, daemon=True)
        self._build_thread.start()
        return self._build_thread