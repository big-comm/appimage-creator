#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Toolkit-free update notification fallback.

Used when neither the embedded update window (inside the AppImage) nor the
host GTK4 window is available — e.g. GTK3-only desktops (Linux Mint) or
Qt-only desktops (KDE) running an AppImage built before the embedded window
hook existed.

Uses the org.freedesktop.Notifications D-Bus interface directly via GLib/Gio
(no GTK required), with an action button that downloads and installs the
update using the pure-Python downloader. Falls back to notify-send
(informational only) when Python GObject bindings are missing entirely.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from updater.downloader import AppImageDownloader
except ImportError:
    from downloader import AppImageDownloader  # type: ignore[no-redef]

# How long to keep listening for a click on the notification's action button.
# After this the notification is closed and the check ends silently (the
# timer will offer the update again on the next cycle).
NOTIFICATION_WAIT_SECONDS = 900

_NOTIFY_BUS = "org.freedesktop.Notifications"
_NOTIFY_PATH = "/org/freedesktop/Notifications"

# Translation support — same domain as the GTK update window, so all main
# strings reuse the existing translations.
import gettext

_locale_dir = "/usr/share/locale"
_user_locale = os.path.expanduser("~/.local/share/locale")
if os.path.isdir(_user_locale):
    _locale_dir = _user_locale
gettext.bindtextdomain("appimage-updater", _locale_dir)


def _(message: str) -> str:
    return gettext.dgettext("appimage-updater", message)


def notify_update(
    app_name: str,
    update_info,
    current_version: str,
    appimage_path: Path,
    marker_file: Path,
    filename_pattern: str = "",
) -> bool:
    """
    Notify the user about an available update without any GUI toolkit.

    Returns True if the user was informed (regardless of whether they
    chose to update), False if no notification method worked.
    """
    try:
        return _notify_via_gio(
            app_name, update_info, current_version, appimage_path, marker_file
        )
    except Exception as e:
        print(f"D-Bus notification failed: {e}", file=sys.stderr)

    return _notify_via_notify_send(app_name, update_info, current_version)


def _notify_via_gio(
    app_name: str,
    update_info,
    current_version: str,
    appimage_path: Path,
    marker_file: Path,
) -> bool:
    """Rich notification via Gio D-Bus: action button downloads and installs."""
    import gi  # noqa: F401  (may raise ImportError -> caller falls back)
    from gi.repository import Gio, GLib

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    # Does the notification daemon support action buttons?
    caps = bus.call_sync(
        _NOTIFY_BUS,
        _NOTIFY_PATH,
        _NOTIFY_BUS,
        "GetCapabilities",
        None,
        GLib.VariantType("(as)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    ).unpack()[0]
    has_actions = "actions" in caps

    summary = _("Update Available")
    body = (
        _("A new version of {} is available").format(app_name)
        + f"\n{current_version} → {update_info.version}"
    )
    actions = ["update", _("Update"), "later", _("Later")] if has_actions else []

    notification_id = _send_notification(
        bus,
        GLib,
        Gio,
        replaces_id=0,
        summary=summary,
        body=body,
        actions=actions,
        # With buttons: stay until the user acts; without: default timeout
        expire_timeout=0 if has_actions else -1,
    )

    if not has_actions:
        # User informed; nothing else we can do without action support
        return True

    action = _wait_for_action(bus, GLib, Gio, notification_id)

    if action != "update":
        return True  # dismissed, "later", or timed out — user was informed

    # --- User clicked "Update": download and install (no GUI needed) ---
    progress_id = _send_notification(
        bus,
        GLib,
        Gio,
        replaces_id=notification_id,
        summary=_("Downloading update..."),
        body=_("Version {}").format(update_info.version),
        actions=[],
        expire_timeout=0,
    )

    downloaded = AppImageDownloader.download_update(update_info.download_url)

    success = False
    if downloaded:
        # Replace in place (same filename): keeps the desktop entry and the
        # marker path valid without needing to re-extract the AppImage.
        # If the app is running, the update is staged as .new and completes
        # on the next launch (handled by complete_pending_updates).
        success = AppImageDownloader.install_update(
            appimage_path, downloaded, new_version=update_info.version
        )

    if success:
        AppImageDownloader.update_marker_file(marker_file, update_info.version)
        body = _("Version {} installed successfully").format(update_info.version)
        if Path(str(appimage_path) + ".new").exists():
            body += "\n" + _(
                "The update will be applied the next time the application starts"
            )
        _send_notification(
            bus,
            GLib,
            Gio,
            replaces_id=progress_id,
            summary=_("Update completed!"),
            body=body,
            actions=[],
            expire_timeout=-1,
        )
    else:
        _send_notification(
            bus,
            GLib,
            Gio,
            replaces_id=progress_id,
            summary=_("Update failed"),
            body=_("Download failed"),
            actions=[],
            expire_timeout=-1,
        )

    return True


def _send_notification(
    bus, GLib, Gio, replaces_id, summary, body, actions, expire_timeout
):
    """Send one notification, returning its id (for updates/replacement)."""
    params = GLib.Variant(
        "(susssasa{sv}i)",
        (
            "AppImage Updater",
            replaces_id,
            "software-update-available",
            summary,
            body,
            actions,
            {"urgency": GLib.Variant("y", 1)},
            expire_timeout,
        ),
    )
    result = bus.call_sync(
        _NOTIFY_BUS,
        _NOTIFY_PATH,
        _NOTIFY_BUS,
        "Notify",
        params,
        GLib.VariantType("(u)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    return result.unpack()[0]


def _wait_for_action(bus, GLib, Gio, notification_id):
    """Wait until the user clicks an action button, closes the notification,
    or the safety timeout expires. Returns the action key or None."""
    loop = GLib.MainLoop()
    state = {"action": None}

    def on_action_invoked(_c, _s, _p, _i, _sig, params):
        nid, action_key = params.unpack()
        if nid == notification_id:
            state["action"] = action_key
            loop.quit()

    def on_notification_closed(_c, _s, _p, _i, _sig, params):
        nid, _reason = params.unpack()
        if nid == notification_id and state["action"] is None:
            loop.quit()

    sub_action = bus.signal_subscribe(
        None,
        _NOTIFY_BUS,
        "ActionInvoked",
        _NOTIFY_PATH,
        None,
        Gio.DBusSignalFlags.NONE,
        on_action_invoked,
    )
    sub_closed = bus.signal_subscribe(
        None,
        _NOTIFY_BUS,
        "NotificationClosed",
        _NOTIFY_PATH,
        None,
        Gio.DBusSignalFlags.NONE,
        on_notification_closed,
    )

    timed_out = {"value": False}

    def on_timeout():
        timed_out["value"] = True
        loop.quit()
        return GLib.SOURCE_REMOVE

    timeout_id = GLib.timeout_add_seconds(NOTIFICATION_WAIT_SECONDS, on_timeout)

    try:
        loop.run()
    finally:
        bus.signal_unsubscribe(sub_action)
        bus.signal_unsubscribe(sub_closed)
        if not timed_out["value"]:
            GLib.source_remove(timeout_id)

    if timed_out["value"]:
        # Close the stale notification: with our listener gone, its buttons
        # would no longer do anything.
        try:
            bus.call_sync(
                _NOTIFY_BUS,
                _NOTIFY_PATH,
                _NOTIFY_BUS,
                "CloseNotification",
                GLib.Variant("(u)", (notification_id,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception:
            pass

    return state["action"]


def _notify_via_notify_send(app_name, update_info, current_version) -> bool:
    """Last resort: informational notification via the notify-send binary
    (no action button — used when Python GObject bindings are missing)."""
    if not shutil.which("notify-send"):
        return False

    summary = _("Update Available")
    body = (
        _("A new version of {} is available").format(app_name)
        + f"\n{current_version} → {update_info.version}"
    )
    try:
        result = subprocess.run(
            [
                "notify-send",
                "-a",
                "AppImage Updater",
                "-i",
                "software-update-available",
                summary,
                body,
            ],
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"notify-send failed: {e}", file=sys.stderr)
        return False
