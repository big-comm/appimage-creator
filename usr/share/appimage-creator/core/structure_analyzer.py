"""
Application structure analysis and detection
"""

import os
import re
import glob
from pathlib import Path
from utils.file_ops import get_file_type
from utils.i18n import _


def analyze_wrapper_script(script_path):
    """Analyze wrapper script to detect underlying application type"""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        analysis = {
            'type': 'shell',
            'target_executable': None,
            'target_type': None,
            'dependencies': [],
            'additional_paths': []
        }
        
        # Look for Python calls
        if re.search(r'\bpython3?\b', content):
            analysis['type'] = 'python_wrapper'
            
            python_match = re.search(r'python3?\s+(?:"([^"]+\.py)"|\'([^\']+\.py)\'|([^\s]+\.py))', content)
            if python_match:
                # This is the raw path string from the script, e.g., '/usr/share/app/main.py'
                target_path_from_script = next(g for g in python_match.groups() if g is not None)
                
                # --- START OF CORRECTED GENERIC LOGIC ---

                # Find the project root by searching upwards from the script's location for a 'usr' directory.
                # This makes the analysis self-contained and aware of its project context.
                project_root = Path(script_path).resolve().parent
                found_root = False
                for _ in range(5): # Search up to 5 levels
                    if (project_root / 'usr').is_dir():
                        found_root = True
                        break
                    if project_root.parent == project_root: # Reached filesystem root
                        break
                    project_root = project_root.parent
                
                if not found_root:
                    # Fallback if no 'usr' dir is found: assume project root is two levels up from the script.
                    project_root = Path(script_path).resolve().parent.parent

                # Now, resolve the path of the target script correctly.
                if os.path.isabs(target_path_from_script):
                    # If the path is absolute (e.g., '/usr/share/app/main.py'),
                    # treat it as relative to the discovered project root.
                    # We strip the leading '/' to correctly join the paths.
                    path_inside_project = target_path_from_script.lstrip(os.sep)
                    target_path = project_root / path_inside_project
                else:
                    # If the path is relative (e.g., '../share/app/main.py'),
                    # resolve it relative to the wrapper script's directory.
                    script_dir = os.path.dirname(script_path)
                    target_path = Path(os.path.abspath(os.path.join(script_dir, target_path_from_script)))

                # The final target_executable is the full, correct path on the build system.
                if target_path.exists():
                    analysis['target_executable'] = str(target_path)
                    analysis['target_type'] = 'python'
                
                # --- END OF CORRECTED GENERIC LOGIC ---

        # Look for other interpreters
        elif 'node' in content or 'nodejs' in content:
            analysis['type'] = 'nodejs_wrapper'
            analysis['target_type'] = 'javascript'
        elif 'java' in content:
            analysis['type'] = 'java_wrapper'
            analysis['target_type'] = 'java'
        
        # Look for dependencies
        if 'TEXTDOMAINDIR' in content:
            analysis['dependencies'].append('locale')
        if 'LD_LIBRARY_PATH' in content:
            analysis['dependencies'].append('libraries')
        if 'QT_' in content:
            analysis['dependencies'].append('qt')
        if 'GTK_' in content or 'GSETTINGS' in content:
            analysis['dependencies'].append('gtk')
            
        return analysis
        
    except Exception as e:
        return {'type': 'shell', 'error': str(e)}


def detect_application_structure(executable_path):
    """Detect complex application structure from executable"""
    path = Path(executable_path).resolve()
    
    # First check if it's a wrapper script BEFORE anything else
    file_type = get_file_type(executable_path)
    if file_type == 'shell':
        wrapper_analysis = analyze_wrapper_script(executable_path)
        if wrapper_analysis.get('type') == 'python_wrapper':
            # Even for wrappers, we need to find the project root
            project_root = None
            current_dir = path.parent
            for _ in range(5):
                if (current_dir / 'usr').is_dir():
                    project_root = current_dir
                    break
                if current_dir.parent == current_dir:
                    break
                current_dir = current_dir.parent
            
            # Create structure for python wrapper
            structure = {
                'type': 'python_wrapper',
                'main_executable': str(path),
                'project_root': str(project_root) if project_root else str(path.parent),
                'detected_files': {'desktop_files': [], 'icons': [], 'locale_dirs': []},
                'wrapper_analysis': wrapper_analysis,
                'has_desktop_file': False
            }
            
            # Scan for desktop files, icons, etc if we found a project root
            if project_root:
                _scan_project_root(project_root, structure)
                structure['has_desktop_file'] = len(structure['detected_files']['desktop_files']) > 0
            
            return structure
    
    structure = {
        'type': 'simple',
        'main_executable': str(path),
        'project_root': None, # Key change: We will find the project root
        'detected_files': {
            'desktop_files': [],
            'icons': [],
            'locale_dirs': [],
        },
        'wrapper_analysis': None,
        'has_desktop_file': False
    }

    # Find project root by searching for a 'usr' directory in parent paths
    project_root = None
    current_dir = path.parent
    for _ in range(5): # Search up to 5 levels up
        if (current_dir / 'usr').is_dir():
            project_root = current_dir
            break
        if current_dir.parent == current_dir:
            break
        current_dir = current_dir.parent

    if project_root:
        structure['project_root'] = str(project_root)
        structure['type'] = 'structured_project'
        # Scan for files ONLY within the project root
        _scan_project_root(project_root, structure)
    else:
        # Fallback for simple cases: project root is the executable's directory
        structure['project_root'] = str(path.parent)
        _scan_project_root(path.parent, structure)
    
    structure['has_desktop_file'] = len(structure['detected_files']['desktop_files']) > 0
    
    return structure


def _scan_project_root(project_root_path, structure):
    """Scans for common files within a given project root directory."""
    root = Path(project_root_path)
    
    # Find desktop files
    for desktop_file in root.glob('**/*.desktop'):
        structure['detected_files']['desktop_files'].append(str(desktop_file))
        
    # Find icons
    for icon_file in root.glob('**/*.svg'):
        if 'icons' in str(icon_file):
            structure['detected_files']['icons'].append(str(icon_file))
    for icon_file in root.glob('**/*.png'):
        if 'icons' in str(icon_file):
            structure['detected_files']['icons'].append(str(icon_file))

    # Find locale directories
    for mo_file in root.glob('**/LC_MESSAGES/*.mo'):
        # The locale dir is typically '.../share/locale'
        locale_dir = mo_file.parent.parent.parent
        if locale_dir.name == 'locale' and str(locale_dir) not in structure['detected_files']['locale_dirs']:
            structure['detected_files']['locale_dirs'].append(str(locale_dir))