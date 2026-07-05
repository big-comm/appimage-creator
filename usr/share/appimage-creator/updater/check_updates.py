#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check all installed AppImages for updates
Called periodically by systemd timer
"""

import os
import locale

# Fix for systemd/cron environments where LANG might be missing
if os.environ.get("LANG", "C") == "C" or not os.environ.get("LANG"):
    try:
        # Try to read system-wide locale configuration
        locale_conf = "/etc/locale.conf"
        if os.path.isfile(locale_conf):
            with open(locale_conf, "r") as f:
                for line in f:
                    if line.strip().startswith("LANG="):
                        lang_val = line.strip().split("=")[1].strip('"').strip("'")
                        if lang_val:
                            os.environ["LANG"] = lang_val
                            os.environ["LC_ALL"] = lang_val
                            # GTK uses LANGUAGE priority, this is CRITICAL
                            os.environ["LANGUAGE"] = lang_val.split(".")[0]
                        break
    except Exception:
        pass

try:
    locale.setlocale(locale.LC_ALL, "")
except Exception:
    pass
import sys
import time
from pathlib import Path

# IMPORTANT: only GTK-free modules may be imported at module level.
# update_window requires GTK4 which may not exist on the host system
# (e.g. GTK3-only or Qt-only desktops); it is imported lazily inside the
# notification cascade so the update *check* itself works everywhere.
try:
    from updater.checker import check_appimage_update, UpdateInfo
    from updater.downloader import AppImageDownloader
except ImportError:
    from checker import check_appimage_update, UpdateInfo  # type: ignore[no-redef]
    from downloader import AppImageDownloader  # type: ignore[no-redef]

# Minimum time (in seconds) to wait after integration before showing update notification
# This gives the AppImage time to complete integration and the main app to open
INTEGRATION_GRACE_PERIOD = 30


# Transient systemd unit that displays the update (window or notification).
# Keeping the display OUT of the cleaner service is essential: it can wait
# minutes for the user, and while it waited inline the timer-driven cleanup
# of orphaned integrations stopped running entirely.
NOTIFIER_UNIT = "appimage-update-notify.service"


def _spawn_detached_notifier(payload) -> bool:
    """
    Run the notification cascade in its own transient systemd user unit so
    the (timer-driven) cleaner service finishes immediately.

    Returns True when the notifier was started or one is already on screen;
    False when systemd-run isn't usable (caller shows inline instead).
    """
    import json
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return False

    payload_file = None
    try:
        # One notification at a time: skip if a notifier is still active
        state = (
            subprocess.run(
                ["systemctl", "--user", "is-active", NOTIFIER_UNIT],
                capture_output=True,
                timeout=5,
            )
            .stdout.decode()
            .strip()
        )
        if state in ("active", "activating", "deactivating"):
            print("An update notification is already on screen; skipping")
            return True

        fd, payload_file = tempfile.mkstemp(
            prefix="appimage-update-notify-", suffix=".json"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        cmd = ["systemd-run", "--user", "--collect", f"--unit={NOTIFIER_UNIT}"]
        # The notifier needs the GUI session environment
        for var in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "XAUTHORITY",
            "DBUS_SESSION_BUS_ADDRESS",
            "XDG_RUNTIME_DIR",
            "LANG",
            "LANGUAGE",
            "LC_ALL",
        ):
            value = os.environ.get(var)
            if value:
                cmd.append(f"--setenv={var}={value}")
        cmd += [
            sys.executable or "python3",
            str(Path(__file__).resolve()),
            "--notify",
            payload_file,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            print(f"Could not start detached notifier: {stderr}")
            os.unlink(payload_file)
            return False
        return True
    except Exception as e:
        print(f"Detached notifier failed: {e}")
        if payload_file:
            try:
                os.unlink(payload_file)
            except OSError:
                pass
        return False


def _run_notifier_from_payload(payload_file: str) -> None:
    """Entry point for the transient notifier unit (--notify <payload.json>)."""
    import json

    try:
        with open(payload_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    finally:
        try:
            os.unlink(payload_file)
        except OSError:
            pass

    update_info = UpdateInfo(
        version=data["new_version"],
        download_url=data["download_url"],
        release_notes=data.get("release_notes", ""),
    )
    _show_notification_cascade(
        data["app_name"],
        update_info,
        data.get("current_version", ""),
        Path(data["appimage_path"]),
        Path(data["marker_file"]),
        data.get("filename_pattern", ""),
        data.get("marker_lines", []),
    )


def _detect_dark_preference() -> bool:
    """
    Detect the host's dark-theme preference, host-side (where the XDG portal,
    dconf, desktop schemas and config files are all reachable). The result is
    passed in the payload so the embedded update window — whose bundled
    libadwaita cannot see the host's theme plumbing — applies the right
    color scheme.

    Checks are desktop-agnostic and each tier degrades independently:
    portal (GNOME/KDE/Mint) -> gsettings themes (GNOME/Cinnamon/MATE/Deepin)
    -> kdeglobals (KDE) -> xfconf (XFCE) -> gtk settings.ini -> GTK_THEME env.
    """
    # 1) XDG settings portal: 1 = prefer dark, 2 = prefer light (explicit)
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            "Read",
            GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
            GLib.VariantType("(v)"),
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
        value = res.unpack()[0]
        while hasattr(value, "unpack"):
            value = value.unpack()
        if int(value) == 1:
            return True
        if int(value) == 2:
            return False
        # 0 = no explicit preference: fall through to theme names
    except Exception:
        pass

    # 2) Theme names from gsettings desktop schemas (schemas missing on a
    #    given desktop are simply skipped). Mint in particular can leave the
    #    portal at "no preference" while the Cinnamon theme is dark.
    try:
        from gi.repository import Gio

        source = Gio.SettingsSchemaSource.get_default()

        def _schema_value(schema, key):
            try:
                if source and source.lookup(schema, True):
                    return Gio.Settings.new(schema).get_string(key) or ""
            except Exception:
                pass
            return ""

        if (
            _schema_value("org.gnome.desktop.interface", "color-scheme")
            == "prefer-dark"
        ):
            return True
        for schema, key in (
            ("org.gnome.desktop.interface", "gtk-theme"),
            ("org.cinnamon.desktop.interface", "gtk-theme"),
            ("org.cinnamon.theme", "name"),
            ("org.mate.interface", "gtk-theme"),
            ("com.deepin.dde.appearance", "gtk-theme"),
        ):
            if "dark" in _schema_value(schema, key).lower():
                return True
    except Exception:
        pass

    # 3) KDE: kdeglobals color scheme (works without any GTK/GObject)
    try:
        import re as _re

        kdeglobals = Path.home() / ".config/kdeglobals"
        if kdeglobals.exists():
            content = kdeglobals.read_text(errors="replace")
            for pattern in (
                r"^ColorScheme=(.*)$",
                r"^LookAndFeelPackage=(.*)$",
            ):
                match = _re.search(pattern, content, flags=_re.MULTILINE)
                if match and "dark" in match.group(1).lower():
                    return True
    except Exception:
        pass

    # 4) XFCE: xfconf theme name
    try:
        import shutil
        import subprocess

        if shutil.which("xfconf-query"):
            result = subprocess.run(
                ["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and (
                "dark" in result.stdout.decode(errors="replace").lower()
            ):
                return True
    except Exception:
        pass

    # 5) GTK settings.ini (generic fallback used by lightweight desktops)
    try:
        import configparser

        for cfg_dir in ("gtk-4.0", "gtk-3.0"):
            ini = Path.home() / ".config" / cfg_dir / "settings.ini"
            if not ini.exists():
                continue
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(ini)
            if parser.has_section("Settings"):
                if parser.get(
                    "Settings", "gtk-application-prefer-dark-theme", fallback="0"
                ).lower() in ("1", "true", "yes"):
                    return True
                if (
                    "dark"
                    in parser.get(
                        "Settings", "gtk-theme-name", fallback=""
                    ).lower()
                ):
                    return True
    except Exception:
        pass

    # 6) Environment hint
    return "dark" in os.environ.get("GTK_THEME", "").lower()


def _marker_supports_embedded_window(marker_lines) -> bool:
    """Line 6 of the marker records that this AppImage's AppRun supports the
    APPIMAGE_SHOW_UPDATE_PAYLOAD env-var hook (written by integration_helper).
    Version 2 is required: "=1" was a short-lived variant using a command-line
    argument, which the AppImage runtime swallows (--appimage-* is reserved) —
    invoking such an AppImage would launch the actual application instead."""
    return len(marker_lines) > 5 and "embedded-update-window=2" in marker_lines[5]


def _show_via_appimage(appimage_path, payload) -> bool:
    """
    Path A: run the GTK4 update window INSIDE the app's own AppImage, using
    its bundled libraries. Works on any host, even without GTK4 installed.
    Only called when the marker says the AppRun understands the env-var hook
    (old AppImages would launch the real application instead).
    """
    import json
    import subprocess
    import tempfile

    if not appimage_path.exists() or not os.access(str(appimage_path), os.X_OK):
        return False

    payload_file = None
    try:
        fd, payload_file = tempfile.mkstemp(
            prefix="appimage-update-", suffix=".json"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        # The hook is triggered via environment variable (NOT a --appimage-*
        # argument: the AppImage runtime reserves that prefix and swallows
        # unknown options before AppRun sees them).
        # Blocks until the user closes the window (same behavior as the
        # host GTK4 window). Non-zero exit (missing GTK4 inside the
        # AppImage, no FUSE, etc.) falls through to the next method.
        env = dict(os.environ)
        env["APPIMAGE_SHOW_UPDATE_PAYLOAD"] = payload_file
        result = subprocess.run([str(appimage_path)], env=env)
        if result.returncode != 0:
            print(
                f"Embedded update window exited with code {result.returncode}, "
                "falling back"
            )
            return False
        return True
    except Exception as e:
        print(f"Embedded update window failed: {e}")
        return False
    finally:
        if payload_file:
            try:
                os.unlink(payload_file)
            except OSError:
                pass


def _show_via_host_gtk(
    app_name, update_info, current_version, appimage_path, marker_file, filename_pattern
) -> bool:
    """Path B: GTK4 update window using the host system's libraries
    (the original behavior, kept for AppImages built before path A existed)."""
    try:
        try:
            from updater.update_window import show_update_notification
        except ImportError:
            from update_window import show_update_notification  # type: ignore
    except Exception as e:
        # ValueError from gi.require_version, ImportError from missing gi, etc.
        print(f"Host GTK4 update window unavailable: {e}")
        return False

    try:
        show_update_notification(
            app_name,
            update_info,
            current_version,
            appimage_path,
            marker_file,
            filename_pattern,
        )
        return True
    except Exception as e:
        print(f"Host GTK4 update window failed: {e}")
        return False


def _show_notification_cascade(
    app_name,
    update_info,
    current_version,
    appimage_path,
    marker_file,
    filename_pattern,
    marker_lines,
) -> bool:
    """Show the update to the user, trying the richest method available:
    A) GTK4 window run inside the app's own AppImage (bundled libraries)
    B) GTK4 window using host libraries (legacy behavior)
    C) Desktop notification via D-Bus with a download action (toolkit-free)
    """
    if _marker_supports_embedded_window(marker_lines):
        payload = {
            "app_name": app_name,
            "current_version": current_version,
            "new_version": update_info.version,
            "download_url": update_info.download_url,
            "release_notes": update_info.release_notes,
            "appimage_path": str(appimage_path),
            "marker_file": str(marker_file),
            "filename_pattern": filename_pattern,
            # Detected host-side: the bundled libadwaita inside the AppImage
            # often cannot see the host's theme settings
            "prefer_dark": _detect_dark_preference(),
        }
        if _show_via_appimage(appimage_path, payload):
            return True

    if _show_via_host_gtk(
        app_name,
        update_info,
        current_version,
        appimage_path,
        marker_file,
        filename_pattern,
    ):
        return True

    try:
        try:
            from updater.notify_fallback import notify_update
        except ImportError:
            from notify_fallback import notify_update  # type: ignore
        return notify_update(
            app_name,
            update_info,
            current_version,
            appimage_path,
            marker_file,
            filename_pattern,
        )
    except Exception as e:
        print(f"Update notification fallback failed: {e}")
        return False


def complete_pending_updates():
    """Complete any pending AppImage updates"""
    marker_dir = Path.home() / ".local/share/appimage-integrations"

    if not marker_dir.exists():
        return

    for marker_file in marker_dir.glob("*.path"):
        try:
            lines = marker_file.read_text().strip().split("\n")
            if not lines or not lines[0].strip():
                continue

            appimage_path = Path(lines[0])

            # Try to complete pending update
            if AppImageDownloader.complete_pending_update(appimage_path):
                app_name = marker_file.stem.replace("_", " ")
                print(f"Completed pending update for {app_name}")

                # Update marker file version if update completed
                new_version_marker = Path(str(appimage_path) + ".new.version")
                if new_version_marker.exists():
                    new_version = new_version_marker.read_text().strip()
                    AppImageDownloader.update_marker_file(marker_file, new_version)
                    new_version_marker.unlink()

        except Exception as e:
            print(f"Error completing update for {marker_file}: {e}")
            continue


def check_all_appimages():
    """Check all integrated AppImages for updates"""
    # First, complete any pending updates
    complete_pending_updates()

    marker_dir = Path.home() / ".local/share/appimage-integrations"

    if not marker_dir.exists():
        return

    for marker_file in marker_dir.glob("*.path"):
        try:
            # Check if marker file was recently created/modified (integration just happened)
            marker_age = time.time() - marker_file.stat().st_mtime

            if marker_age < INTEGRATION_GRACE_PERIOD:
                # Skip this check - integration is too recent
                # Give the AppImage time to complete integration and open the main app
                print(
                    f"Skipping update check for {marker_file.stem} (recently integrated, waiting {INTEGRATION_GRACE_PERIOD - marker_age:.0f}s)"
                )
                continue

            # Check if update is available
            update_info = check_appimage_update(marker_file)

            if update_info:
                # Read marker file to get info
                lines = marker_file.read_text().strip().split("\n")

                if len(lines) < 5:
                    continue

                appimage_path = Path(lines[0])
                app_name = marker_file.stem.replace("_", " ")
                current_version = lines[3]
                filename_pattern = lines[4] if len(lines) >= 5 else ""

                # Only show if in graphical environment
                if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                    print(
                        f"Update available for {app_name}: {current_version} -> {update_info.version}"
                    )
                    continue

                # Show update using the richest method available on this host.
                # Prefer a detached transient unit so THIS process (the
                # timer-driven cleaner) finishes immediately and cleanup
                # keeps its fast cadence.
                print(f"Showing update notification for {app_name}")
                payload = {
                    "app_name": app_name,
                    "current_version": current_version,
                    "new_version": update_info.version,
                    "download_url": update_info.download_url,
                    "release_notes": update_info.release_notes,
                    "appimage_path": str(appimage_path),
                    "marker_file": str(marker_file),
                    "filename_pattern": filename_pattern,
                    "marker_lines": lines,
                }
                if not _spawn_detached_notifier(payload):
                    # No systemd-run available: show inline (blocks this
                    # run until the user reacts — legacy behavior)
                    _show_notification_cascade(
                        app_name,
                        update_info,
                        current_version,
                        appimage_path,
                        marker_file,
                        filename_pattern,
                        lines,
                    )

                # Only show one update at a time
                break

        except Exception as e:
            print(f"Error checking {marker_file}: {e}")
            continue


def main():
    """Main entry point"""
    check_all_appimages()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--notify":
        # Running as the detached notifier unit
        _run_notifier_from_payload(sys.argv[2])
    else:
        main()
