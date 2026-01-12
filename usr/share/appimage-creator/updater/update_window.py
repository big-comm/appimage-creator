#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GTK4/Libadwaita Update Notification Window
"""

# Configure locale BEFORE importing GTK (critical for translations)
import os
import locale

# Fix for systemd/cron environments where LANG might be missing
if os.environ.get('LANG', 'C') == 'C' or not os.environ.get('LANG'):
    try:
        # Try to read system-wide locale configuration
        locale_conf = '/etc/locale.conf'
        if os.path.isfile(locale_conf):
            with open(locale_conf, 'r') as f:
                for line in f:
                    if line.strip().startswith('LANG='):
                        lang_val = line.strip().split('=')[1].strip('"').strip("'")
                        if lang_val:
                            os.environ['LANG'] = lang_val
                            os.environ['LC_ALL'] = lang_val
                            # GTK uses LANGUAGE priority, this is CRITICAL
                            os.environ['LANGUAGE'] = lang_val.split('.')[0]
                        break
    except Exception:
        pass

try:
    locale.setlocale(locale.LC_ALL, '')
except:
    pass

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Gdk
from pathlib import Path
import threading
import subprocess
import shutil

try:
    from updater.checker import UpdateInfo
    from updater.downloader import AppImageDownloader
except ImportError:
    # When running as standalone (from AppImage)
    from checker import UpdateInfo
    from downloader import AppImageDownloader


# Translation support (same approach as tac-writer)
import gettext

# Determine locale directory (works in AppImage and system install)
locale_dir = '/usr/share/locale'  # Default fallback

# Check if we're in an AppImage
if 'APPDIR' in os.environ:
    # Running from AppImage - use APPDIR environment variable
    appdir = os.environ['APPDIR']
    appimage_locale = os.path.join(appdir, 'usr/share/locale')

    if os.path.isdir(appimage_locale):
        locale_dir = appimage_locale
else:
    # Check user local share (highest priority for installed updater)
    user_locale = os.path.expanduser('~/.local/share/locale')
    if os.path.isdir(user_locale):
        locale_dir = user_locale
    
    # Fallback: try to locate from script location (development)
    elif 'APPIMAGE' in os.environ:
        # Fallback: try to locate from script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate from updater to usr/share/locale
        # Possible locations: usr/bin/updater or usr/share/appimage-creator/updater
        parts = script_dir.split(os.sep)
        if 'usr' in parts:
            usr_index = len(parts) - 1 - parts[::-1].index('usr')
            usr_dir = os.sep.join(parts[:usr_index+1])
            appimage_locale = os.path.join(usr_dir, 'share', 'locale')

            if os.path.isdir(appimage_locale):
                locale_dir = appimage_locale
    else:
        # Running from development - check local updater/locale
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dev_locale = os.path.join(script_dir, 'locale')
        if os.path.isdir(dev_locale):
            locale_dir = dev_locale

# Configure the translation text domain for appimage-updater
gettext.bindtextdomain("appimage-updater", locale_dir)
gettext.textdomain("appimage-updater")

# Export _ directly as the translation function
_ = gettext.gettext


def markdown_to_pango(text: str) -> str:
    """
    Convert simple Markdown to Pango markup for GTK
    Supports: **bold**, *italic*, [links](url)
    """
    import re

    # Escape special characters first
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')

    # Convert **bold**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)

    # Convert *italic* (but not **bold** which was already converted)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)

    # Convert [link text](url) to clickable links
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)

    return text


class ProgressDialog(Adw.Window):
    """Separate window for showing update progress"""

    def __init__(self, parent, app_name: str, new_version: str):
        """
        Initialize progress dialog

        Args:
            parent: Parent window
            app_name: Name of the application
            new_version: Version being downloaded
        """
        super().__init__()

        self.set_title(_("Updating"))
        self.set_default_size(450, 300)
        self.set_modal(True)
        self.set_transient_for(parent)
        self.set_resizable(False)

        # Set window icon to match main update window
        self._set_window_icon()

        # Prevent closing during download
        self.can_close = False

        self.app_name = app_name
        self.new_version = new_version

        self._build_ui()

    def _set_window_icon(self):
        """Set window icon from installed location or fallback"""
        import os
        
        icon_paths = [
            # User local (installed by updater)
            Path.home() / ".local/share/icons/hicolor/scalable/apps/appimage-update.svg",
            # Development/source
            Path(__file__).parent.parent / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
            Path(__file__).parent.parent.parent.parent / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
            # System install
            Path("/usr/share/icons/hicolor/scalable/apps/appimage-update.svg"),
            # AppImage environment
            Path(os.environ.get('APPDIR', '/nonexistent')) / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
        ]

        for icon_path in icon_paths:
            if icon_path.exists():
                self.set_icon_name("appimage-update")
                return

        # Fallback to symbolic icon
        self.set_icon_name("software-update-available-symbolic")

    def _build_ui(self):
        """Build the progress dialog UI"""
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        main_box.append(header)

        # Content box with centered content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_start(48)
        content.set_margin_end(48)
        content.set_margin_top(48)
        content.set_margin_bottom(48)
        content.set_vexpand(True)
        content.set_valign(Gtk.Align.CENTER)
        main_box.append(content)

        # Status icon (will change based on state)
        self.status_icon = Gtk.Image()
        self.status_icon.set_pixel_size(64)
        self.status_icon.set_margin_bottom(12)
        content.append(self.status_icon)

        # Status label
        self.status_label = Gtk.Label()
        self.status_label.add_css_class("title-2")
        self.status_label.set_wrap(True)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        content.append(self.status_label)

        # Version label
        self.version_label = Gtk.Label()
        self.version_label.add_css_class("dim-label")
        content.append(self.version_label)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_top(12)
        content.append(self.progress_bar)

        # Progress text (MB downloaded)
        self.progress_text = Gtk.Label()
        self.progress_text.add_css_class("dim-label")
        self.progress_text.set_margin_top(6)
        content.append(self.progress_text)

        # Done button (hidden initially)
        self.done_button = Gtk.Button(label=_("Done"))
        self.done_button.add_css_class("suggested-action")
        self.done_button.set_halign(Gtk.Align.CENTER)
        self.done_button.set_margin_top(24)
        self.done_button.set_visible(False)
        self.done_button.connect("clicked", lambda b: self.close())
        content.append(self.done_button)

        # Start in downloading state
        self.show_downloading_state()

    def show_downloading_state(self):
        """Show downloading state"""
        self.status_icon.set_from_icon_name("folder-download-symbolic")
        self.status_label.set_text(_("Downloading update..."))
        self.version_label.set_text(_("Version {}").format(self.new_version))
        self.progress_bar.set_visible(True)
        self.progress_text.set_visible(True)
        self.done_button.set_visible(False)

    def show_installing_state(self):
        """Show installing state"""
        self.status_icon.set_from_icon_name("emblem-synchronizing-symbolic")
        self.status_label.set_text(_("Installing update..."))
        self.progress_bar.set_fraction(1.0)
        self.progress_text.set_visible(False)

    def show_success_state(self):
        """Show success state with checkmark"""
        # Create success icon with CSS
        self.status_icon.set_from_icon_name("emblem-ok-symbolic")
        self.status_icon.set_pixel_size(80)

        # Add custom CSS for green color
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .success-icon {
                color: #26a269;
            }
        """)
        self.status_icon.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.status_icon.add_css_class("success-icon")

        self.status_label.set_text(_("Update completed!"))
        self.version_label.set_text(_("Version {} installed successfully").format(self.new_version))
        self.progress_bar.set_visible(False)
        self.progress_text.set_visible(False)
        self.done_button.set_visible(True)
        self.can_close = True

    def show_error_state(self, error_message: str):
        """Show error state with X icon"""
        # Create error icon with CSS
        self.status_icon.set_from_icon_name("dialog-error-symbolic")
        self.status_icon.set_pixel_size(80)

        # Add custom CSS for red color
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            .error-icon {
                color: #c01c28;
            }
        """)
        self.status_icon.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.status_icon.add_css_class("error-icon")

        self.status_label.set_text(_("Update failed"))
        self.version_label.set_text(error_message)
        self.progress_bar.set_visible(False)
        self.progress_text.set_visible(False)
        self.done_button.set_label(_("Close"))
        self.done_button.set_visible(True)
        self.done_button.remove_css_class("suggested-action")
        self.can_close = True

    def update_progress(self, fraction: float, downloaded_mb: float, total_mb: float):
        """Update progress bar and text"""
        self.progress_bar.set_fraction(fraction)
        self.progress_text.set_text(
            _("{:.1f} MB of {:.1f} MB").format(downloaded_mb, total_mb)
        )


class UpdateWindow(Adw.ApplicationWindow):
    """Update notification and installer window"""

    def __init__(self, app_name: str, update_info: UpdateInfo,
                 current_version: str, appimage_path: Path,
                 marker_file: Path, filename_pattern: str):
        """
        Initialize update window

        Args:
            app_name: Name of the application
            update_info: Information about available update
            current_version: Current version
            appimage_path: Path to current AppImage
            marker_file: Path to marker file
            filename_pattern: Pattern for new filename (e.g., "app-*-x86_64.AppImage")
        """
        super().__init__()

        self.app_name = app_name
        self.update_info = update_info
        self.current_version = current_version
        self.appimage_path = appimage_path
        self.marker_file = marker_file
        self.filename_pattern = filename_pattern
        self.download_thread = None
        self.remove_old_version = False

        self.set_title(_("Update Available"))
        self.set_default_size(550, 770)
        self.set_modal(True)

        # Set window icon
        self._set_window_icon()

        self._build_ui()

    def _set_window_icon(self):
        """Set window icon from installed location or fallback"""
        try:
            import os

            # Try multiple locations for the icon
            icon_paths = [
                # If running from source/development
                Path(__file__).parent.parent.parent.parent / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
                # If installed system-wide
                Path("/usr/share/icons/hicolor/scalable/apps/appimage-update.svg"),
                # If running from AppImage
                Path(os.environ.get('APPDIR', '')) / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
            ]

            for icon_path in icon_paths:
                if icon_path.exists():
                    self.set_icon_name("appimage-update")
                    return

            # Fallback to symbolic icon
            self.set_icon_name("software-update-available-symbolic")

        except Exception:
            # Fallback to symbolic icon
            self.set_icon_name("software-update-available-symbolic")

    def _build_ui(self):
        """Build the window UI"""
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        main_box.append(header)

        # Scrolled window for all content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        main_box.append(scrolled)

        # Content box inside scroll
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        scrolled.set_child(content)

        # Icon (centered) - use custom appimage-update.svg icon
        icon = Gtk.Image()
        icon.set_pixel_size(64)
        icon.set_halign(Gtk.Align.CENTER)

        # Try to use custom appimage-update icon from various locations
        import os
        icon_paths = [
            # User local (installed by updater)
            Path.home() / ".local/share/icons/hicolor/scalable/apps/appimage-update.svg",
            # Development/source - relative to this script
            Path(__file__).parent.parent / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
            # Development - full project path
            Path(__file__).parent.parent.parent.parent / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
            # System install
            Path("/usr/share/icons/hicolor/scalable/apps/appimage-update.svg"),
            # AppImage environment
            Path(os.environ.get('APPDIR', '/nonexistent')) / "usr/share/icons/hicolor/scalable/apps/appimage-update.svg",
        ]

        icon_loaded = False
        for icon_path in icon_paths:
            if icon_path.exists():
                try:
                    # Use GdkPixbuf for reliable SVG loading
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(icon_path), 64, 64, True
                    )
                    icon.set_from_pixbuf(pixbuf)
                    icon_loaded = True
                    break
                except Exception as e:
                    print(f"Failed to load icon from {icon_path}: {e}")
                    continue

        if not icon_loaded:
            # Fallback to symbolic icon
            icon.set_from_icon_name("software-update-available-symbolic")

        content.append(icon)

        # Title (centered)
        title = Gtk.Label()
        title.set_markup(f"<span size='x-large' weight='bold'>{_('Update Available')}</span>")
        title.set_halign(Gtk.Align.CENTER)
        title.set_margin_top(12)
        content.append(title)

        # Description (centered)
        description = Gtk.Label()
        description.set_text(_("A new version of {} is available").format(self.app_name))
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.CENTER)
        description.set_margin_bottom(12)
        content.append(description)

        # Version info group
        version_group = Adw.PreferencesGroup()
        version_group.set_title(_("Version Information"))

        current_row = Adw.ActionRow()
        current_row.set_title(_("Current Version"))
        current_row.set_subtitle(self.current_version)
        version_group.add(current_row)

        new_row = Adw.ActionRow()
        new_row.set_title(_("New Version"))
        new_row.set_subtitle(self.update_info.version)
        version_group.add(new_row)

        content.append(version_group)

        # Release notes (if available)
        if self.update_info.release_notes:
            notes_group = Adw.PreferencesGroup()
            notes_group.set_title(_("What's New"))

            # Use ExpanderRow for release notes
            notes_expander = Adw.ExpanderRow()
            notes_expander.set_title(_("Release Notes"))
            notes_expander.set_subtitle(_("Click to view changes"))

            # Notes label (no nested scroll, just expandable)
            notes_label = Gtk.Label()
            formatted_notes = markdown_to_pango(self.update_info.release_notes)
            notes_label.set_markup(formatted_notes)
            notes_label.set_wrap(True)
            notes_label.set_xalign(0)
            notes_label.set_margin_start(12)
            notes_label.set_margin_end(12)
            notes_label.set_margin_top(12)
            notes_label.set_margin_bottom(12)
            notes_label.set_selectable(True)

            notes_expander.add_row(notes_label)
            notes_group.add(notes_expander)

            content.append(notes_group)

        # Options group
        options_group = Adw.PreferencesGroup()
        options_group.set_title(_("Options"))

        # Remove old version switch
        remove_row = Adw.ActionRow()
        remove_row.set_title(_("Remove old version"))
        remove_row.set_subtitle(_("Delete previous version after successful update"))

        self.remove_switch = Gtk.Switch()
        self.remove_switch.set_valign(Gtk.Align.CENTER)
        self.remove_switch.set_active(False)
        self.remove_switch.connect("notify::active", self._on_remove_switch_changed)
        remove_row.add_suffix(self.remove_switch)
        remove_row.set_activatable_widget(self.remove_switch)

        options_group.add(remove_row)
        content.append(options_group)

        # Bottom bar with buttons (outside scroll, fixed at bottom)
        bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bottom_bar.set_margin_start(24)
        bottom_bar.set_margin_end(24)
        bottom_bar.set_margin_top(12)
        bottom_bar.set_margin_bottom(24)
        main_box.append(bottom_bar)

        # Spacer to push buttons to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom_bar.append(spacer)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom_bar.append(button_box)

        self.cancel_button = Gtk.Button(label=_("Later"))
        self.cancel_button.connect("clicked", self._on_cancel)
        button_box.append(self.cancel_button)

        self.update_button = Gtk.Button(label=_("Update"))
        self.update_button.add_css_class("suggested-action")
        self.update_button.connect("clicked", self._on_update)
        button_box.append(self.update_button)

    def _on_remove_switch_changed(self, switch, param):
        """Handle remove switch state change"""
        self.remove_old_version = switch.get_active()

    def _on_cancel(self, button):
        """Handle cancel button"""
        if self.download_thread and self.download_thread.is_alive():
            return  # Don't close during download

        self.close()

    def _on_update(self, button):
        """Handle update button - open progress dialog and start download"""
        # Hide this window (don't close, so progress dialog can be transient)
        self.hide()

        # Open progress dialog
        progress_dialog = ProgressDialog(
            self,
            self.app_name,
            self.update_info.version
        )

        # Store reference to close main window after progress dialog closes
        progress_dialog.main_window = self
        progress_dialog.connect("close-request", self._on_progress_dialog_closed)

        progress_dialog.present()

        # Start download in background thread
        self.download_thread = threading.Thread(
            target=self._download_and_install,
            args=(progress_dialog,),
            daemon=True
        )
        self.download_thread.start()

    def _on_progress_dialog_closed(self, dialog):
        """Close main window when progress dialog is closed"""
        self.close()
        return False  # Allow closing

    def _download_and_install(self, progress_dialog: ProgressDialog):
        """Download and install update (runs in background thread)"""
        try:
            # Calculate new filename from pattern
            new_filename = self.filename_pattern.replace('*', self.update_info.version)
            new_appimage_path = self.appimage_path.parent / new_filename

            # Download with new filename
            downloaded_file = AppImageDownloader.download_update(
                self.update_info.download_url,
                progress_callback=lambda d, t: self._on_download_progress(progress_dialog, d, t),
                target_filename=new_filename,
                target_directory=self.appimage_path.parent
            )

            if not downloaded_file:
                GLib.idle_add(progress_dialog.show_error_state, _("Download failed"))
                return

            # Update status to installing
            GLib.idle_add(progress_dialog.show_installing_state)

            # Make executable
            downloaded_file.chmod(0o755)

            # Re-integrate silently with new path
            success = self._silent_reintegrate(downloaded_file)

            if not success:
                GLib.idle_add(progress_dialog.show_error_state, _("Integration failed"))
                return

            # Update marker file with new path and version
            self._update_marker_file(downloaded_file)

            # Remove old version if requested
            if self.remove_old_version:
                try:
                    if self.appimage_path.exists():
                        self.appimage_path.unlink()
                except Exception as e:
                    print(f"Warning: Could not remove old version: {e}")

            # Success!
            GLib.idle_add(progress_dialog.show_success_state)

        except Exception as e:
            GLib.idle_add(progress_dialog.show_error_state, str(e))

    def _on_download_progress(self, progress_dialog: ProgressDialog, downloaded: int, total: int):
        """Update progress bar (called from download thread)"""
        if total > 0:
            fraction = downloaded / total
            downloaded_mb = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            GLib.idle_add(progress_dialog.update_progress, fraction, downloaded_mb, total_mb)

    def _silent_reintegrate(self, new_appimage_path: Path) -> bool:
        """
        Re-integrate AppImage silently without launching the application

        Args:
            new_appimage_path: Path to the new AppImage file

        Returns:
            True on success, False on error
        """
        try:
            # Read marker file to get desktop filename
            if not self.marker_file.exists():
                return False

            lines = self.marker_file.read_text().strip().split('\n')
            if len(lines) < 2:
                return False

            desktop_filename = lines[1]

            # Extract AppImage to get desktop and icon files
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)

                # Extract AppImage
                result = subprocess.run(
                    [str(new_appimage_path), "--appimage-extract"],
                    cwd=tmpdir_path,
                    capture_output=True,
                    timeout=60
                )

                if result.returncode != 0:
                    return False

                squashfs_root = tmpdir_path / "squashfs-root"

                # Find desktop file
                desktop_file = squashfs_root / "usr/share/applications" / desktop_filename
                if not desktop_file.exists():
                    return False

                # Find icon file
                import configparser
                config = configparser.ConfigParser()
                config.read(desktop_file)
                icon_name = config.get('Desktop Entry', 'Icon')

                icon_file = None
                for ext in ['.svg', '.png', '.xpm']:
                    potential_icon = squashfs_root / f"{icon_name}{ext}"
                    if potential_icon.exists():
                        icon_file = potential_icon
                        break

                if not icon_file:
                    return False

                # Update integration
                apps_dir = Path.home() / ".local/share/applications"
                icons_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"

                apps_dir.mkdir(parents=True, exist_ok=True)
                icons_dir.mkdir(parents=True, exist_ok=True)

                target_desktop_path = apps_dir / desktop_file.name
                target_icon_path = icons_dir / icon_file.name

                # Copy icon
                shutil.copy2(icon_file, target_icon_path)

                # Update desktop file with new Exec path
                import re
                desktop_content = desktop_file.read_text()

                modified_content = re.sub(
                    r'^Exec=.*$',
                    f'Exec="{str(new_appimage_path)}" %F',
                    desktop_content,
                    flags=re.MULTILINE
                )

                modified_content = re.sub(
                    r'^Icon=.*$',
                    f'Icon={str(target_icon_path)}',
                    modified_content,
                    flags=re.MULTILINE
                )

                target_desktop_path.write_text(modified_content)

                # Update desktop database
                try:
                    subprocess.run(
                        ["update-desktop-database", str(apps_dir)],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5
                    )
                except:
                    pass

                return True

        except Exception as e:
            print(f"Silent reintegration failed: {e}")
            return False

    def _update_marker_file(self, new_appimage_path: Path):
        """Update marker file with new AppImage path and version"""
        try:
            if not self.marker_file.exists():
                return

            lines = self.marker_file.read_text().strip().split('\n')

            # Update path (line 1) and version (line 4)
            if len(lines) >= 1:
                lines[0] = str(new_appimage_path)
            if len(lines) >= 4:
                lines[3] = self.update_info.version

            self.marker_file.write_text('\n'.join(lines))

        except Exception as e:
            print(f"Failed to update marker file: {e}")


class UpdateApp(Adw.Application):
    """Simple application to show update window"""

    def __init__(self, app_name: str, update_info: UpdateInfo,
                 current_version: str, appimage_path: Path,
                 marker_file: Path, filename_pattern: str):
        super().__init__(application_id='org.bigcommunity.appimage.updater')

        self.app_name = app_name
        self.update_info = update_info
        self.current_version = current_version
        self.appimage_path = appimage_path
        self.marker_file = marker_file
        self.filename_pattern = filename_pattern

    def do_activate(self):
        """Called when application is activated"""
        window = self.props.active_window
        if not window:
            window = UpdateWindow(
                self.app_name,
                self.update_info,
                self.current_version,
                self.appimage_path,
                self.marker_file,
                self.filename_pattern
            )
            window.set_application(self)
        window.present()


def show_update_notification(app_name: str, update_info: UpdateInfo,
                            current_version: str, appimage_path: Path,
                            marker_file: Path, filename_pattern: str = ""):
    """
    Show update notification window

    Args:
        app_name: Application name
        update_info: Update information
        current_version: Current version
        appimage_path: Path to AppImage
        marker_file: Path to marker file
        filename_pattern: Pattern for new filename
    """
    import sys

    app = UpdateApp(
        app_name,
        update_info,
        current_version,
        appimage_path,
        marker_file,
        filename_pattern
    )
    return app.run(sys.argv)
