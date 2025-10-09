"""
File operations utilities
"""

import os
import shutil
import urllib.request
from pathlib import Path
from utils.i18n import _


def copy_files_recursively(src, dst, exclude_patterns=None):
    """Copy files and directories recursively with exclusion patterns"""
    if exclude_patterns is None:
        exclude_patterns = ['.git', '.github', '.gitignore', '__pycache__', '*.pyc', '.DS_Store', '*.tmp']
    
    src_path = Path(src)
    dst_path = Path(dst)
    
    if src_path.is_file():
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
    else:
        # Copy directory
        for item in src_path.rglob('*'):
            try:
                rel_path = item.relative_to(src_path)
                
                # Check if ANY part of the path matches exclusion patterns
                if any(part for part in rel_path.parts if any(Path(part).match(pattern) for pattern in exclude_patterns)):
                    continue
                
                # Also check the file itself
                if any(item.match(pattern) for pattern in exclude_patterns):
                    continue
                    
                dest_item = dst_path / rel_path
                
                if item.is_file():
                    dest_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_item)
            except (OSError, PermissionError):
                continue


def download_file(url, destination, progress_callback=None):
    """Download file with optional progress callback"""
    def report_progress(block_num, block_size, total_size):
        if progress_callback and total_size > 0:
            downloaded = block_num * block_size
            percentage = min(100, int(downloaded * 100 / total_size))
            progress_callback(percentage)
    
    try:
        urllib.request.urlretrieve(url, destination, reporthook=report_progress)
    except Exception as e:
        raise Exception(_("Failed to download {}: {}").format(url, e))


def scan_directory_structure(directory_path):
    """Scan a directory and return its structure for preview"""
    structure = {'dirs': [], 'files': [], 'total_size': 0}
    
    try:
        dir_path = Path(directory_path)
        if not dir_path.exists():
            return structure
            
        for item in dir_path.rglob('*'):
            try:
                rel_path = item.relative_to(dir_path)
                
                if item.is_file():
                    size = item.stat().st_size
                    structure['files'].append({
                        'path': str(rel_path),
                        'size': size,
                        'type': get_file_type(str(item))
                    })
                    structure['total_size'] += size
                elif item.is_dir():
                    structure['dirs'].append(str(rel_path))
            except (OSError, PermissionError):
                continue
                
    except Exception as e:
        structure['error'] = str(e)
        
    return structure


def get_file_type(file_path):
    """Detect file type based on content first, then extension"""
    path = Path(file_path)
    
    # PRIORITY 1: Detect by file content (shebang and magic bytes)
    # This is more reliable than extension, especially for files without extensions
    try:
        with open(file_path, 'rb') as f:
            header = f.read(1024)
        
        # Check for shebang first (highest priority for scripts)
        if header.startswith(b'#!/'):
            shebang = header.split(b'\n')[0].decode('utf-8', errors='ignore').lower()
            
            # Python shebangs
            if 'python' in shebang:
                return 'python'
            
            # Shell shebangs (comprehensive list)
            shell_indicators = ['bash', 'sh', 'zsh', 'ksh', 'csh', 'tcsh', 'dash', '/bin/sh', '/usr/bin/env sh', '/usr/bin/env bash']
            if any(indicator in shebang for indicator in shell_indicators):
                return 'shell'
            
            # Node.js shebangs
            if 'node' in shebang:
                return 'javascript'
        
        # Check for ELF binary (Linux executables)
        if header.startswith(b'\x7fELF'):
            return 'binary'
        
        # Check for Java class file
        if header.startswith(b'\xca\xfe\xba\xbe'):
            return 'java'
            
    except (IOError, OSError, UnicodeDecodeError, PermissionError) as e:
        # If we can't read the file, fall through to extension-based detection
        pass
    
    # PRIORITY 2: Detect by file extension (fallback)
    ext = path.suffix.lower()
    
    # Script files
    if ext in ['.py', '.pyw']:
        return 'python'
    elif ext in ['.sh', '.bash', '.zsh', '.ksh']:
        return 'shell'
    elif ext in ['.js', '.mjs', '.cjs']:
        return 'javascript'
    elif ext in ['.jar']:
        return 'java'
    elif ext in ['.exe', '.deb', '.rpm', '.flatpak', '.appimage']:
        return 'binary'
    elif ext in ['.tar.gz', '.tar.bz2', '.zip', '.tar', '.gz', '.bz2', '.xz']:
        return 'archive'
    
    # PRIORITY 3: If no extension and no recognizable content
    # For executable files without extension, assume binary
    try:
        if os.access(file_path, os.X_OK):  # If file is executable
            return 'binary'
    except:
        pass
    
    return 'unknown'