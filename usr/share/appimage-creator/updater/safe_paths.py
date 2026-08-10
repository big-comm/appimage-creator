#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validation of the paths stored in integration marker files.

Marker files live in ~/.local/share/appimage-integrations and are written by
integration_helper, but they are plain text in a user-writable location: their
content ends up building filesystem paths and — for the embedded update window
— *executing* a program. A tampered or stale marker must never make the updater
run something that is not an AppImage, or move files outside the marker dir.

Every value read from a marker goes through the helpers below before use.
"""

import os
import tempfile
from pathlib import Path
from typing import Optional, Union

MARKER_DIR = Path.home() / ".local/share/appimage-integrations"

# Payload files are created with tempfile.mkstemp() by check_updates
PAYLOAD_PREFIX = "appimage-update"

APPIMAGE_SUFFIX = ".appimage"

# ELF header followed by the AppImage type marker at offset 8 ("AI" + type)
_ELF_MAGIC = b"\x7fELF"
_APPIMAGE_MAGIC = b"AI"


def _has_appimage_magic(path: Path) -> bool:
    """True when the file carries the ELF + AppImage magic bytes."""
    try:
        with open(path, "rb") as f:
            header = f.read(11)
    except OSError:
        return False

    return (
        len(header) == 11
        and header.startswith(_ELF_MAGIC)
        and header[8:10] == _APPIMAGE_MAGIC
        and header[10] in (1, 2)
    )


def safe_marker_file(raw: Union[str, Path]) -> Optional[Path]:
    """
    Return the resolved marker path when it is a *.path file directly inside
    MARKER_DIR, otherwise None (symlinks and ../ escapes are resolved first).
    """
    try:
        marker = Path(raw).resolve()
        marker_dir = MARKER_DIR.resolve()
    except OSError:
        return None

    if marker.parent != marker_dir or marker.suffix != ".path":
        return None
    return marker


def safe_payload_file(raw: Union[str, Path]) -> Optional[Path]:
    """
    Return the resolved payload path when it is one of our own temp files.

    The payload name reaches the notifier through argv or an environment
    variable, so it is only accepted as a regular *.json file named like the
    ones check_updates creates, directly inside the temp dir.
    """
    try:
        payload = Path(raw).resolve()
        # The notifier may run in a unit that does not inherit TMPDIR, so /tmp
        # is accepted alongside whatever this process considers the temp dir.
        temp_dirs = {Path(tempfile.gettempdir()).resolve(), Path("/tmp")}
    except OSError:
        return None

    if payload.parent not in temp_dirs or payload.suffix != ".json":
        return None
    if not payload.name.startswith(PAYLOAD_PREFIX) or not payload.is_file():
        return None
    return payload


def safe_appimage_path(
    raw: Union[str, Path], must_exist: bool = True, executable: bool = False
) -> Optional[Path]:
    """
    Return the resolved path when it points to an AppImage file, otherwise None.

    An existing file is accepted on its magic bytes (so AppImages renamed
    without the usual extension keep updating); a file that is not there yet
    is accepted on the .AppImage extension alone.

    Args:
        raw: value read from a marker file or an update payload
        must_exist: require an existing regular file
        executable: also require the execute bit (used before running it)
    """
    text = str(raw).strip()
    # Markers always store absolute paths; a relative one is malformed and
    # must not be resolved against whatever cwd the updater happens to have.
    if not text or not Path(text).is_absolute():
        return None

    try:
        path = Path(text).resolve()
    except OSError:
        return None

    if path.is_file():
        if not _has_appimage_magic(path) and path.suffix.lower() != APPIMAGE_SUFFIX:
            return None
    elif must_exist or path.suffix.lower() != APPIMAGE_SUFFIX:
        return None

    if executable and not os.access(str(path), os.X_OK):
        return None

    return path
