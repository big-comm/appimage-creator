"""
File operations utilities
"""

import hashlib
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from utils.i18n import _


def copy_files_recursively(
    src: str | os.PathLike,
    dst: str | os.PathLike,
    exclude_patterns: Optional[list[str]] = None,
) -> None:
    """Copy files and directories recursively with exclusion patterns"""
    if exclude_patterns is None:
        exclude_patterns = [
            ".git",
            ".github",
            ".gitignore",
            "__pycache__",
            "*.pyc",
            ".DS_Store",
            "*.tmp",
        ]

    src_path = Path(src)
    dst_path = Path(dst)

    if src_path.is_file():
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
    else:
        # Copy directory
        for item in src_path.rglob("*"):
            try:
                rel_path = item.relative_to(src_path)

                # Check if ANY part of the path matches exclusion patterns
                if any(
                    part
                    for part in rel_path.parts
                    if any(Path(part).match(pattern) for pattern in exclude_patterns)
                ):
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


def download_file(
    url: str,
    destination: str | os.PathLike,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> None:
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


def compute_sha256(file_path: str | os.PathLike) -> str:
    """Compute SHA256 hex digest for a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_download_sha256(
    file_path: str | os.PathLike,
    sha256_url: str,
) -> tuple[bool, str]:
    """Verify a downloaded file against a remote SHA256 checksum.

    Tries to fetch ``sha256_url``.  If the remote file is available, the
    local file's hash is compared against it.

    Returns (verified, local_hash).  ``verified`` is True when the hash
    matches, False when it mismatches, and True (with just the local hash)
    when the remote checksum is unavailable (fail-open for continuous
    releases that have no checksum file).
    """
    import tempfile

    local_hash = compute_sha256(file_path)
    filename = Path(file_path).name

    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sha256")
        tmp.close()
        urllib.request.urlretrieve(sha256_url, tmp.name)

        with open(tmp.name, "r") as f:
            content = f.read().strip()

        os.unlink(tmp.name)

        # Formats: "<hash>  <filename>" or bare "<hash>"
        for line in content.splitlines():
            parts = line.strip().split()
            if not parts:
                continue
            remote_hash = parts[0].lower()
            # Either bare hash or hash matching our filename
            if len(parts) == 1 or filename in line:
                return (remote_hash == local_hash, local_hash)

        # Remote file existed but didn't contain matching entry
        return (True, local_hash)
    except Exception:
        # Remote checksum not available — fail-open
        return (True, local_hash)


def scan_directory_structure(directory_path: str | os.PathLike) -> dict:
    """Scan a directory and return its structure for preview"""
    structure = {"dirs": [], "files": [], "total_size": 0}

    try:
        dir_path = Path(directory_path)
        if not dir_path.exists():
            return structure

        for item in dir_path.rglob("*"):
            try:
                rel_path = item.relative_to(dir_path)

                if item.is_file():
                    size = item.stat().st_size
                    structure["files"].append({
                        "path": str(rel_path),
                        "size": size,
                        "type": get_file_type(str(item)),
                    })
                    structure["total_size"] += size
                elif item.is_dir():
                    structure["dirs"].append(str(rel_path))
            except (OSError, PermissionError):
                continue

    except Exception as e:
        structure["error"] = str(e)

    return structure


def get_file_type(file_path: str | os.PathLike) -> str:
    """Detect file type based on content first, then extension"""
    path = Path(file_path)

    # PRIORITY 1: Detect by file content (shebang and magic bytes)
    # This is more reliable than extension, especially for files without extensions
    try:
        with open(file_path, "rb") as f:
            header = f.read(1024)

        # Check for shebang first (highest priority for scripts)
        if header.startswith(b"#!/"):
            shebang = header.split(b"\n")[0].decode("utf-8", errors="ignore").lower()

            # Python shebangs
            if "python" in shebang:
                return "python"

            # Shell shebangs (comprehensive list)
            shell_indicators = [
                "bash",
                "sh",
                "zsh",
                "ksh",
                "csh",
                "tcsh",
                "dash",
                "/bin/sh",
                "/usr/bin/env sh",
                "/usr/bin/env bash",
            ]
            if any(indicator in shebang for indicator in shell_indicators):
                return "shell"

            # Node.js shebangs
            if "node" in shebang:
                return "javascript"

        # Check for ELF binary (Linux executables)
        if header.startswith(b"\x7fELF"):
            return "binary"

        # Check for Java class file
        if header.startswith(b"\xca\xfe\xba\xbe"):
            return "java"

    except (IOError, OSError, UnicodeDecodeError, PermissionError):
        # If we can't read the file, fall through to extension-based detection
        pass

    # PRIORITY 2: Detect by file extension (fallback)
    ext = path.suffix.lower()

    # Script files
    if ext in [".py", ".pyw"]:
        return "python"
    elif ext in [".sh", ".bash", ".zsh", ".ksh"]:
        return "shell"
    elif ext in [".js", ".mjs", ".cjs"]:
        return "javascript"
    elif ext in [".jar"]:
        return "java"
    elif ext in [".exe", ".deb", ".rpm", ".flatpak", ".appimage"]:
        return "binary"
    elif ext in [".tar.gz", ".tar.bz2", ".zip", ".tar", ".gz", ".bz2", ".xz"]:
        return "archive"

    # PRIORITY 3: If no extension and no recognizable content
    # For executable files without extension, assume binary
    try:
        if os.access(file_path, os.X_OK):  # If file is executable
            return "binary"
    except Exception:
        pass

    return "unknown"
