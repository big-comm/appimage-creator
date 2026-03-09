"""
System utilities and helpers
"""

import re
import subprocess
import shutil
import os
from typing import Dict, Optional, List
from utils.i18n import _


def get_system_info() -> Dict[str, str]:
    """Get system information for AppImage creation"""
    try:
        arch = subprocess.check_output(["uname", "-m"], text=True, timeout=5).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        arch = "x86_64"

    return {"architecture": arch, "platform": "linux"}


def get_distro_info() -> Dict[str, Optional[str]]:
    """Detect host distribution information"""
    distro_info: Dict[str, Optional[str]] = {"id": None, "base": None}

    # Try reading /etc/os-release
    try:
        with open("/etc/os-release", "r") as f:
            lines = f.readlines()

        for line in lines:
            if line.startswith("ID="):
                distro_info["id"] = line.strip().split("=")[1].strip('"')
            elif line.startswith("ID_LIKE="):
                # ID_LIKE can have multiple values, e.g., "debian arch"
                bases = line.strip().split("=")[1].strip('"').split()
                if "arch" in bases:
                    distro_info["base"] = "arch"
                elif "debian" in bases:
                    distro_info["base"] = "debian"
                elif "fedora" in bases or "rhel" in bases:
                    distro_info["base"] = "rpm"
    except FileNotFoundError:
        pass  # Could not find os-release file

    # Fallback for base detection if ID_LIKE is not present
    if not distro_info["base"]:
        if distro_info["id"] in ["arch", "manjaro", "endeavouros"]:
            distro_info["base"] = "arch"
        elif distro_info["id"] in ["debian", "ubuntu", "linuxmint", "pop"]:
            distro_info["base"] = "debian"
        elif distro_info["id"] in ["fedora", "centos", "rhel", "nobara"]:
            distro_info["base"] = "rpm"

    return distro_info


def check_host_dependencies(dependencies: List[str]) -> Dict[str, bool]:
    """Check for the existence of required host executables"""
    status = {}
    for dep in dependencies:
        status[dep] = find_executable_in_path(dep) is not None
    return status


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for AppImage creation"""
    # Remove invalid characters
    sanitized = re.sub(r"[^\w\s\-_.]", "", filename)
    # Replace spaces with underscores
    sanitized = re.sub(r"\s+", "_", sanitized)
    # Remove multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")

    return sanitized if sanitized else "MyApp"


def format_size(size_bytes: int | float) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"

    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def find_executable_in_path(executable: str) -> Optional[str]:
    """Find executable in system PATH"""
    return shutil.which(executable)


def get_host_env() -> Dict[str, str]:
    """Return a clean copy of the environment without AppImage pollution.

    When running inside an AppImage, variables like LD_LIBRARY_PATH,
    PYTHONHOME, PYTHONPATH, and PATH are modified to point to the
    AppImage mount point. These break host tools like distrobox/podman.
    """
    env = os.environ.copy()
    appdir = env.get("APPDIR", "")

    if not appdir:
        return env

    # Remove AppImage-specific variables
    for var in ("APPDIR", "APPIMAGE", "OWD", "PYTHONHOME", "PYTHONPATH"):
        env.pop(var, None)

    # Clean PATH: remove entries under the AppImage mount point
    if "PATH" in env:
        clean_paths = [
            p for p in env["PATH"].split(os.pathsep)
            if not p.startswith(appdir)
        ]
        env["PATH"] = os.pathsep.join(clean_paths)

    # Clean LD_LIBRARY_PATH: remove entries under the AppImage mount point
    if "LD_LIBRARY_PATH" in env:
        clean_ld = [
            p for p in env["LD_LIBRARY_PATH"].split(os.pathsep)
            if p and not p.startswith(appdir)
        ]
        if clean_ld:
            env["LD_LIBRARY_PATH"] = os.pathsep.join(clean_ld)
        else:
            del env["LD_LIBRARY_PATH"]

    # Clean GI_TYPELIB_PATH
    if "GI_TYPELIB_PATH" in env:
        clean_gi = [
            p for p in env["GI_TYPELIB_PATH"].split(os.pathsep)
            if p and not p.startswith(appdir)
        ]
        if clean_gi:
            env["GI_TYPELIB_PATH"] = os.pathsep.join(clean_gi)
        else:
            del env["GI_TYPELIB_PATH"]

    return env


def make_executable(file_path: str | os.PathLike) -> None:
    """Make file executable"""
    try:
        current_permissions = os.stat(file_path).st_mode
        os.chmod(file_path, current_permissions | 0o111)
    except OSError as e:
        raise Exception(_("Failed to make file executable: {}").format(e))
