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
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
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
    # Remove leading/trailing underscores, dots and spaces (avoid hidden/dot-only names)
    sanitized = sanitized.strip("_ .")

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


def read_elf_needed(file_path: str | os.PathLike) -> List[str]:
    """
    Return the DT_NEEDED entries (shared libraries) an ELF executable was
    linked against, e.g. ['libgtk-4.so.1', 'libadwaita-1.so.0', ...].

    Pure-Python parser: works without external tools (readelf/objdump may
    not be installed) and never executes the target (unlike ldd). Returns
    an empty list for non-ELF files, static binaries, or on parse errors.
    """
    import struct

    PT_LOAD, PT_DYNAMIC = 1, 2
    DT_NULL, DT_NEEDED, DT_STRTAB, DT_STRSZ = 0, 1, 5, 10

    try:
        with open(file_path, "rb") as f:
            ident = f.read(16)
            if len(ident) < 16 or ident[:4] != b"\x7fELF":
                return []

            is_64 = ident[4] == 2
            end = "<" if ident[5] == 1 else ">"

            if is_64:
                header = f.read(48)
                (e_phoff,) = struct.unpack(end + "Q", header[16:24])
                e_phentsize, e_phnum = struct.unpack(end + "HH", header[38:42])
                ph_fmt, ph_size = end + "IIQQQQQQ", 56  # type,flags,off,vaddr,...
                dyn_fmt, dyn_size = end + "qQ", 16
            else:
                header = f.read(36)
                (e_phoff,) = struct.unpack(end + "I", header[12:16])
                e_phentsize, e_phnum = struct.unpack(end + "HH", header[26:30])
                ph_fmt, ph_size = end + "IIIIIIII", 32  # type,off,vaddr,...
                dyn_fmt, dyn_size = end + "iI", 8

            # Read program headers: find PT_DYNAMIC and the PT_LOAD segments
            # (needed to translate virtual addresses to file offsets)
            loads = []
            dynamic = None
            for i in range(e_phnum):
                f.seek(e_phoff + i * e_phentsize)
                fields = struct.unpack(ph_fmt, f.read(ph_size))
                if is_64:
                    p_type, _flags, p_offset, p_vaddr, _pa, p_filesz = fields[:6]
                else:
                    p_type, p_offset, p_vaddr, _pa, p_filesz = fields[:5]
                if p_type == PT_LOAD:
                    loads.append((p_vaddr, p_offset, p_filesz))
                elif p_type == PT_DYNAMIC:
                    dynamic = (p_offset, p_filesz)

            if not dynamic:
                return []  # Statically linked

            def vaddr_to_offset(vaddr):
                for seg_vaddr, seg_offset, seg_filesz in loads:
                    if seg_vaddr <= vaddr < seg_vaddr + seg_filesz:
                        return seg_offset + (vaddr - seg_vaddr)
                return None

            # Walk the dynamic section collecting DT_NEEDED string offsets
            f.seek(dynamic[0])
            dyn_data = f.read(dynamic[1])
            needed_offsets = []
            strtab_addr = strtab_size = None
            for pos in range(0, len(dyn_data) - dyn_size + 1, dyn_size):
                d_tag, d_val = struct.unpack(
                    dyn_fmt, dyn_data[pos : pos + dyn_size]
                )
                if d_tag == DT_NULL:
                    break
                if d_tag == DT_NEEDED:
                    needed_offsets.append(d_val)
                elif d_tag == DT_STRTAB:
                    strtab_addr = d_val
                elif d_tag == DT_STRSZ:
                    strtab_size = d_val

            if strtab_addr is None or not needed_offsets:
                return []

            strtab_offset = vaddr_to_offset(strtab_addr)
            if strtab_offset is None:
                # Some binaries store a file offset directly
                strtab_offset = strtab_addr
            f.seek(strtab_offset)
            strtab = f.read(strtab_size or 1048576)

            libraries = []
            for offset in needed_offsets:
                if offset >= len(strtab):
                    continue
                name_end = strtab.find(b"\x00", offset)
                if name_end == -1:
                    continue
                name = strtab[offset:name_end].decode("utf-8", errors="ignore")
                if name:
                    libraries.append(name)
            return libraries
    except (OSError, struct.error):
        return []
