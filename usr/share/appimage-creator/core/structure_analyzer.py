"""
Application structure analysis and detection
"""

import os
import re
import glob
import sys
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
        
        # Look for Python calls (improved regex patterns)
        python_patterns = [
            r'\bpython3?\b',           # python or python3
            r'\bpython3\.\d+\b',       # python3.11, python3.12, etc.
            r'/usr/bin/python3?',      # /usr/bin/python or /usr/bin/python3
            r'/usr/bin/env\s+python3?' # /usr/bin/env python or python3
        ]
        
        if any(re.search(pattern, content, re.IGNORECASE) for pattern in python_patterns):
            analysis['type'] = 'python_wrapper'
            
            # Improved regex to capture Python script paths in various formats
            python_call_patterns = [
                r'python3?\s+(?:"([^"]+\.py)"|\'([^\']+\.py)\'|([^\s]+\.py))',  # python3 "script.py", 'script.py', or script.py
                r'python3?\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))\s+\$@',           # python3 /path/to/script "$@"
                r'python3?\s+-[mu]\s+(\S+)',                                     # python3 -m module or python3 -u script
                r'/usr/bin/python3?\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))',       # /usr/bin/python3 /path/script
                r'/usr/bin/env\s+python3?\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))'  # /usr/bin/env python3 /path/script
            ]
            
            target_path_from_script = None
            for pattern in python_call_patterns:
                python_match = re.search(pattern, content)
                if python_match:
                    # Get the first non-None group (the captured path/module)
                    groups = [g for g in python_match.groups() if g is not None]
                    if groups:
                        target_path_from_script = groups[0]
                        # If it doesn't end with .py, add it (for module paths)
                        if not target_path_from_script.endswith('.py'):
                            # Check if next line or same line has .py file
                            # This handles cases like: python3 -m package.__main__
                            if '.' in target_path_from_script:
                                # Convert module path to file path (e.g., package.main -> package/main.py)
                                target_path_from_script = target_path_from_script.replace('.', '/') + '.py'
                            else:
                                target_path_from_script += '.py'
                        break
            
            if target_path_from_script:
                # DEBUG: Log wrapper detection
                print(f"[DEBUG analyze_wrapper_script] Detected python wrapper", file=sys.stderr)
                print(f"  target_path_from_script: {target_path_from_script}", file=sys.stderr)
                
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

                # Now, search for the target script within the entire project root. This is more robust.
                # We use os.path.basename to handle cases where the script path is complex (e.g., "app/main.py").
                search_filename = os.path.basename(target_path_from_script)
                found_targets = list(project_root.rglob(search_filename))
                
                target_path = None
                if found_targets:
                    # Take the first match. A more complex heuristic could be added if needed.
                    target_path = found_targets[0]

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
    
    # DEBUG: Log file type detection
    file_type = get_file_type(executable_path)
    print(f"[DEBUG] File: {path.name}, Detected type: {file_type}", file=sys.stderr)
    
    # Check if it's a shell script by shebang OR file type
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