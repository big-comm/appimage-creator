"""
Desktop file, launcher script, and AppRun generation
"""

import os
import sys
import stat
from pathlib import Path
from utils.i18n import _


def generate_desktop_file(app_info):
    """Generate .desktop file content"""
    def escape_value(value):
        if not value:
            return ""
        value = str(value).replace('\\', '\\\\')
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '\\r')
        value = value.replace('\t', '\\t')
        return value
    
    app_name = escape_value(app_info.get('name', 'Application'))
    description = escape_value(app_info.get('description', app_name))
    executable_name = escape_value(app_info.get('executable_name', 'app'))
    
    categories = app_info.get('categories', ['Utility'])
    if not categories:
        categories = ['Utility']
    categories_str = ';'.join(categories) + ';'
    
    desktop_content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name={app_name}
Comment={description}
Exec={executable_name} %F
Icon={executable_name}
Categories={categories_str}
StartupNotify=true
Terminal={str(app_info.get('terminal', False)).lower()}
'''

    website = app_info.get('website', '').strip()
    if website and website.startswith(('http://', 'https://')):
        desktop_content += f"X-Website={escape_value(website)}\n"
    
    keywords = app_info.get('keywords', [])
    if keywords and isinstance(keywords, list):
        keywords_str = ';'.join([escape_value(k) for k in keywords if k]) + ';'
        if keywords_str != ';':
            desktop_content += f"Keywords={keywords_str}\n"
    
    mime_types = app_info.get('mime_types', [])
    if mime_types and isinstance(mime_types, list):
        mime_str = ';'.join([escape_value(m) for m in mime_types if m]) + ';'
        if mime_str != ';':
            desktop_content += f"MimeType={mime_str}\n"
    
    return desktop_content


def create_desktop_file(appdir_path, app_info):
    """Create .desktop file in AppDir"""
    from validators.validators import validate_desktop_content
    
    desktop_content = generate_desktop_file(app_info)
    
    if not validate_desktop_content(desktop_content):
        print(_("Warning: Desktop file may have validation issues"))
    
    # Save to usr/share/applications
    desktop_path = appdir_path / "usr" / "share" / "applications" / f"{app_info['executable_name']}.desktop"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(desktop_path, 'w', encoding='utf-8') as f:
        f.write(desktop_content)
    
    # Copy to AppDir root
    root_desktop_path = appdir_path / f"{app_info['executable_name']}.desktop"
    with open(root_desktop_path, 'w', encoding='utf-8') as f:
        f.write(desktop_content)
    
    if not root_desktop_path.exists():
        raise RuntimeError(_("Failed to create desktop file"))
    
    return desktop_path


def create_apprun_script(app_info):
    """Create AppRun script content"""
    
    executable = app_info.get('apprun_executable')
    argument = app_info.get('apprun_argument')
    
    if not executable:
        executable = f"usr/bin/{app_info.get('executable_name', 'app')}"

    if argument:
        exec_line = f'exec "${{HERE}}/{executable}" "${{HERE}}/{argument}" "$@"'
    else:
        exec_line = f'exec "${{HERE}}/{executable}" "$@"'

    py_version = app_info.get('python_version', f"{sys.version_info.major}.{sys.version_info.minor}")
    
    return f'''#!/bin/bash
# AppRun for {app_info['name']}

HERE="$(dirname "$(readlink -f "${{0}}")")"

# Set up the primary library path, always prioritizing bundled libraries
# for essential components like libvte, libadwaita, etc.
export LD_LIBRARY_PATH="${{HERE}}/usr/lib:${{LD_LIBRARY_PATH}}"

# Conditionally add the fallback library path for conflicting libraries (e.g., libjpeg).
# This path is only added if the host system does NOT have the library,
# ensuring portability on systems like Fedora without causing conflicts on systems like Manjaro.
if ! ldconfig -p 2>/dev/null | grep -q "libjpeg.so.8"; then
    export LD_LIBRARY_PATH="${{HERE}}/usr/lib-fallback:${{LD_LIBRARY_PATH}}"
fi

# Construct the PATH environment variable with correct priority.
# 1. Python venv bin (if it exists)
# 2. AppImage's main usr/bin (for tools like vainfo)
# 3. The original system PATH
APPIMAGE_BIN_PATH="${{HERE}}/usr/bin"

# GObject Introspection typelibs
export GI_TYPELIB_PATH="${{HERE}}/usr/lib/girepository-1.0:${{HERE}}/usr/lib/x86_64-linux-gnu/girepository-1.0:${{GI_TYPELIB_PATH}}"

# GStreamer plugin path
export GST_PLUGIN_PATH="${{HERE}}/usr/lib/gstreamer-1.0:${{GST_PLUGIN_PATH}}"
export GST_PLUGIN_SYSTEM_PATH="${{HERE}}/usr/lib/gstreamer-1.0"

# GTK icon and theme paths - CRITICAL for bundled icon themes
export XDG_DATA_DIRS="${{HERE}}/usr/share:${{XDG_DATA_DIRS:-/usr/local/share:/usr/share}}"
export GTK_PATH="${{HERE}}/usr/lib/gtk-4.0:${{HERE}}/usr/lib/gtk-3.0:${{GTK_PATH}}"
export GTK_DATA_PREFIX="${{HERE}}/usr"
export GTK_EXE_PREFIX="${{HERE}}/usr"

# GSettings schemas (for icon theme settings)
if [ -d "${{HERE}}/usr/share/glib-2.0/schemas" ]; then
    export GSETTINGS_SCHEMA_DIR="${{HERE}}/usr/share/glib-2.0/schemas:${{GSETTINGS_SCHEMA_DIR}}"
fi

# Setup localization
export TEXTDOMAINDIR="${{HERE}}/usr/share/locale"

# Setup Python virtualenv if it exists
if [ -d "${{HERE}}/usr/python/venv" ]; then
    export PYTHONHOME="${{HERE}}/usr/python/venv"
    export PYTHONPATH="${{HERE}}/usr/python/venv/lib/python{py_version}/site-packages"

    # Prepend the venv bin path to our custom path
    APPIMAGE_BIN_PATH="${{HERE}}/usr/python/venv/bin:${{APPIMAGE_BIN_PATH}}"
fi

# Export the final, correctly ordered PATH
export PATH="${{APPIMAGE_BIN_PATH}}:${{PATH}}"

# Execute the target application
{exec_line}
'''


def create_apprun_file(appdir_path, app_info):
    """Create AppRun file in AppDir"""
    apprun_content = create_apprun_script(app_info)
    apprun_path = appdir_path / "AppRun"
    
    with open(apprun_path, 'w', encoding='utf-8') as f:
        f.write(apprun_content)
    
    # Make AppRun executable
    apprun_path.chmod(apprun_path.stat().st_mode | stat.S_IEXEC)
    
    return apprun_path


def create_launcher_script_file(appdir_path, app_info, template):
    """Create launcher script file in AppDir"""
    script_content = template.get_launcher_script()
    script_path = appdir_path / "usr" / "bin" / app_info['executable_name']
    
    script_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)
    
    # Make script executable
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    
    return script_path


def adapt_existing_desktop_file(source_desktop_file, appdir_path, app_info, new_exec=None):
    """Copy and adapt existing desktop file without renaming it or changing icon"""
    try:
        with open(source_desktop_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        modified_lines = []
        
        for line in lines:
            # Keep Exec= and Icon= unchanged
            modified_lines.append(line)
        
        # Ensure Version field exists
        if not any(line.strip().startswith('Version=') for line in modified_lines):
            for i, line in enumerate(modified_lines):
                if line.strip() == '[Desktop Entry]':
                    modified_lines.insert(i + 1, 'Version=1.0')
                    break
        
        modified_content = '\n'.join(modified_lines)
        
        # Overwrite with modified content
        with open(source_desktop_file, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        # Copy to AppDir root, keeping original name
        root_desktop_path = appdir_path / Path(source_desktop_file).name
        with open(root_desktop_path, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        return True
        
    except Exception as e:
        print(_("Warning: Failed to adapt existing desktop file: {}").format(e))
        return False