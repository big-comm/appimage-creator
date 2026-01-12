"""
Dialog windows for the AppImage Creator UI
"""

import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Vte', '3.91')

from gi.repository import Gtk, Adw, Gio, Vte, GLib, Pango
from pathlib import Path
import subprocess
from utils.i18n import _


class BuildProgressDialog(Adw.Window):
    """Modal dialog showing build progress"""
    
    def __init__(self, parent):
        super().__init__()
        print(f"[DIALOG] BuildProgressDialog.__init__ chamado - ID: {id(self)}")
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Building AppImage"))
        self.set_default_size(500, 200)
        self.set_resizable(False)
        self.set_deletable(False)
        
        # Layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header
        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)
        
        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_top(24)
        content_box.set_margin_bottom(24)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        main_box.append(content_box)
        
        # Progress label
        self.progress_label = Gtk.Label(label=_("Preparing..."))
        self.progress_label.set_halign(Gtk.Align.START)
        self.progress_label.add_css_class("title-4")
        content_box.append(self.progress_label)
        
        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_top(12)
        content_box.append(self.progress_bar)
        
        # Cancel button
        self.cancel_button = Gtk.Button(label=_("Cancel Build"))
        self.cancel_button.add_css_class("destructive-action")
        self.cancel_button.set_halign(Gtk.Align.CENTER)
        self.cancel_button.set_margin_top(24)
        content_box.append(self.cancel_button)
        
    def update_progress(self, percentage, message):
        """Update progress bar and message"""
        self.progress_bar.set_fraction(percentage / 100.0)
        self.progress_label.set_text(message)
        
    def __del__(self):
        print(f"[DIALOG] BuildProgressDialog.__del__ chamado - objeto sendo destruído - ID: {id(self)}")


def show_error_dialog(parent, title, message):
    """Show error dialog"""
    dialog = Adw.MessageDialog(transient_for=parent)
    dialog.set_heading(title)
    dialog.set_body(message)
    dialog.add_response("ok", _("OK"))
    dialog.set_default_response("ok")
    dialog.present()


def show_success_dialog(parent, title, message, on_response=None):
    """Show success dialog with optional open folder button"""
    dialog = Adw.MessageDialog(transient_for=parent)
    dialog.set_heading(title)
    dialog.set_body(message)
    dialog.add_response("ok", _("OK"))
    dialog.add_response("open", _("Open Folder"))
    dialog.set_default_response("ok")
    
    if on_response:
        dialog.connect("response", on_response)
    
    dialog.present()


def show_info_dialog(parent, title, message):
    """Show info dialog"""
    dialog = Adw.MessageDialog(transient_for=parent)
    dialog.set_heading(title)
    dialog.set_body(message)
    dialog.add_response("ok", _("OK"))
    dialog.set_default_response("ok")
    dialog.present()


def create_file_chooser(parent, title, action, filters=None, on_response=None, settings_manager=None):
    """Create and show file chooser dialog"""
    dialog = Gtk.FileChooserDialog(
        title=title,
        transient_for=parent,
        action=action,
        modal=True
    )
    
    # Set initial directory from settings
    if settings_manager:
        last_path = settings_manager.get('last-chooser-directory')
        if last_path and os.path.exists(last_path):
            dialog.set_current_folder(Gio.File.new_for_path(last_path))
    
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    if action == Gtk.FileChooserAction.OPEN:
        dialog.add_button(_("Open"), Gtk.ResponseType.OK)
    elif action == Gtk.FileChooserAction.SELECT_FOLDER:
        dialog.add_button(_("Select"), Gtk.ResponseType.OK)
    else:
        dialog.add_button(_("Save"), Gtk.ResponseType.OK)
    
    dialog.set_default_response(Gtk.ResponseType.OK)
    
    # Add filters
    if filters:
        for filter_name, patterns in filters.items():
            file_filter = Gtk.FileFilter()
            file_filter.set_name(filter_name)
            for pattern in patterns:
                file_filter.add_pattern(pattern)
            dialog.add_filter(file_filter)
    
    def on_response_wrapper(dlg, response):
        # Save last used directory
        if settings_manager and response == Gtk.ResponseType.OK:
            file = dlg.get_file()
            if file:
                if action == Gtk.FileChooserAction.SELECT_FOLDER:
                    path = file.get_path()
                else:
                    path = file.get_parent().get_path()
                
                if path:
                    settings_manager.set('last-chooser-directory', path)
        
        # Call original callback
        if on_response:
            on_response(dlg, response)
    
    dialog.connect("response", on_response_wrapper)
    
    dialog.present()
    return dialog


def show_structure_viewer(parent, title, structure_text):
    """Show structure viewer window"""
    window = Adw.Window()
    window.set_transient_for(parent)
    window.set_modal(True)
    window.set_title(title)
    window.set_default_size(800, 600)
    window.set_size_request(500, 400)
    
    # Header
    header_bar = Adw.HeaderBar()
    
    # Main box
    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    main_box.append(header_bar)
    
    # Scrolled window
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_vexpand(True)
    
    # Text view
    text_view = Gtk.TextView()
    text_view.set_editable(False)
    text_view.set_cursor_visible(False)
    text_view.add_css_class("monospace")
    text_view.set_margin_top(12)
    text_view.set_margin_bottom(12)
    text_view.set_margin_start(12)
    text_view.set_margin_end(12)
    
    buffer = text_view.get_buffer()
    buffer.set_text(structure_text)
    
    scrolled.set_child(text_view)
    main_box.append(scrolled)
    
    # Copy button
    copy_button = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
    copy_button.set_tooltip_text(_("Copy to clipboard"))
    
    def on_copy(btn):
        clipboard = window.get_display().get_clipboard()
        clipboard.set(structure_text)
    
    copy_button.connect("clicked", on_copy)
    header_bar.pack_end(copy_button)
    
    window.set_content(main_box)
    window.present()


def show_desktop_file_viewer(parent, desktop_file_path):
    """Show desktop file content viewer"""
    try:
        with open(desktop_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        show_structure_viewer(parent, _("Desktop File Content"), content)
    except Exception as e:
        show_error_dialog(parent, _("Error"), _("Failed to read file: {}").format(e))
        
        
class LogProgressDialog(Adw.Window):
    """Modal dialog showing progress for a long-running task with live logs."""

    def __init__(self, parent, title):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(title)
        self.set_default_size(700, 450)
        self.set_resizable(True)
        self.set_deletable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        main_box.append(content_box)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content_box.append(status_box)

        self.spinner = Gtk.Spinner()
        self.spinner.start()
        status_box.append(self.spinner)

        self.status_label = Gtk.Label(label=_("Starting..."))
        self.status_label.set_halign(Gtk.Align.START)
        status_box.append(self.status_label)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        content_box.append(scrolled_window)

        self.terminal = Vte.Terminal()
        self.terminal.set_scroll_on_output(True)
        self.terminal.set_scroll_on_keystroke(False)
        self.terminal.set_mouse_autohide(True)
        
        # Set terminal font
        font_desc = Pango.FontDescription.from_string("Monospace 10")
        self.terminal.set_font(font_desc)
        
        scrolled_window.set_child(self.terminal)

        self.close_button = Gtk.Button(label=_("Close"))
        self.close_button.set_sensitive(False)
        self.close_button.connect("clicked", lambda btn: self.destroy())
        header_bar.pack_start(self.close_button)

    def add_log(self, message):
        """Append a message to the terminal."""
        self.terminal.feed((message + "\r\n").encode('utf-8'))

    def set_status(self, status_text):
        """Update the status label."""
        self.status_label.set_text(status_text)

    def finish(self, success=True):
        """Mark the task as finished."""
        self.spinner.stop()
        self.close_button.set_sensitive(True)
        if success:
            self.set_status(_("Completed successfully!"))
        else:
            self.set_status(_("Finished with errors."))
            

class InstallPackagesDialog(Adw.Window):
    """Dialog for installing system packages with VTE terminal."""

    def __init__(self, parent, packages_info):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Install Required Packages"))
        self.set_default_size(700, 500)
        self.set_resizable(True)
        
        self.packages_info = packages_info
        self.installation_complete = False
        self.installation_success = False
        self.current_command_is_pre = False
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header
        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)

        # Content
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        main_box.append(content_box)

        # Info section
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Installation Information"))
        content_box.append(info_group)

        # Packages to install
        packages_row = Adw.ActionRow()
        packages_row.set_title(_("Packages to Install"))
        packages_list = ", ".join(packages_info['packages'])
        packages_row.set_subtitle(packages_list)
        info_group.add(packages_row)

        # Command that will be executed
        command_row = Adw.ActionRow()
        command_row.set_title(_("Command"))
        command_row.set_subtitle(packages_info['display'])
        info_group.add(command_row)

        # Warning message
        warning_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        warning_box.set_margin_top(8)
        warning_box.add_css_class("card")
        warning_box.set_margin_start(12)
        warning_box.set_margin_end(12)
        
        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_icon.set_margin_top(12)
        warning_icon.set_margin_bottom(12)
        warning_icon.set_margin_start(12)
        warning_box.append(warning_icon)
        
        warning_label = Gtk.Label()
        warning_label.set_markup(_("<b>Administrator privileges required</b>\nYou will be asked for your password to install system packages."))
        warning_label.set_halign(Gtk.Align.START)
        warning_label.set_margin_top(12)
        warning_label.set_margin_bottom(12)
        warning_label.set_margin_end(12)
        warning_box.append(warning_label)
        
        content_box.append(warning_box)

        # Terminal section
        terminal_group = Adw.PreferencesGroup()
        terminal_group.set_title(_("Installation Output"))
        terminal_group.set_margin_top(12)
        content_box.append(terminal_group)

        # VTE Terminal in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(250)
        
        self.terminal = Vte.Terminal()
        self.terminal.set_scroll_on_output(True)
        self.terminal.set_scroll_on_keystroke(True)
        self.terminal.set_mouse_autohide(True)
        
        # Set terminal font
        font_desc = Pango.FontDescription.from_string("Monospace 10")
        self.terminal.set_font(font_desc)
        
        # Connect to child-exited signal
        self.terminal.connect("child-exited", self._on_child_exited)
        
        scrolled.set_child(self.terminal)
        terminal_group.add(scrolled)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_top(12)
        content_box.append(button_box)

        self.cancel_button = Gtk.Button(label=_("Cancel"))
        self.cancel_button.connect("clicked", self._on_cancel_clicked)
        button_box.append(self.cancel_button)

        self.install_button = Gtk.Button(label=_("Install"))
        self.install_button.add_css_class("suggested-action")
        self.install_button.connect("clicked", self._on_install_clicked)
        button_box.append(self.install_button)

        self.close_button = Gtk.Button(label=_("Close"))
        self.close_button.set_visible(False)
        self.close_button.connect("clicked", lambda btn: self.destroy())
        button_box.append(self.close_button)

    def _on_cancel_clicked(self, button):
        """Handle cancel button click."""
        if not self.installation_complete:
            self.destroy()

    def _on_install_clicked(self, button):
        """Handle install button click and start installation."""
        self.install_button.set_sensitive(False)
        self.cancel_button.set_sensitive(False)
        
        self._write_to_terminal(_("Starting installation...\n\n"))
        
        # Run pre-command if exists (like apt-get update)
        if 'pre_command' in self.packages_info:
            self._run_command(self.packages_info['pre_command'], is_pre_command=True)
        else:
            self._run_main_command()

    def _run_command(self, command, is_pre_command=False):
        """Run a command in the VTE terminal."""
        self.current_command_is_pre = is_pre_command
        command_str = ' '.join(command)
        self._write_to_terminal(f"$ {command_str}\n")
        
        try:
            # Spawn the command in the terminal
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                None,  # working directory
                command,
                None,  # environment
                GLib.SpawnFlags.DEFAULT,  # Changed from DO_NOT_REAP_CHILD
                None,  # child_setup
                None,  # child_setup_data
                -1,    # timeout
                None,  # cancellable
                None,  # callback (we use child-exited signal instead)
                None   # user_data
            )
        except Exception as e:
            self._write_to_terminal(f"\n{_('Error running command')}: {str(e)}\n")
            self._finish_installation(False)

    def _on_child_exited(self, terminal, exit_status):
        """Called when the spawned command exits."""
        self._write_to_terminal("\n")
        
        if exit_status == 0:
            if self.current_command_is_pre:
                self._write_to_terminal(f"{_('Pre-command completed successfully.')}\n\n")
                # Run main command
                self._run_main_command()
            else:
                self._write_to_terminal(f"{_('Installation completed successfully!')}\n")
                self._finish_installation(True)
        else:
            self._write_to_terminal(f"{_('Command failed with exit code')}: {exit_status}\n")
            self._finish_installation(False)

    def _run_main_command(self):
        """Run the main installation command."""
        self._run_command(self.packages_info['command'], is_pre_command=False)

    def _write_to_terminal(self, text):
        """Write text to terminal."""
        self.terminal.feed(text.encode('utf-8'))

    def _finish_installation(self, success):
        """Finish installation process."""
        self.installation_complete = True
        self.installation_success = success
        
        if success:
            self._write_to_terminal("\n")
            self._write_to_terminal("=" * 50 + "\n")
            self._write_to_terminal(_("Installation completed successfully!") + "\n")
            self._write_to_terminal("=" * 50 + "\n")
            
            # Close dialog automatically after success
            GLib.timeout_add(500, lambda: self.close())
        else:
            self._write_to_terminal("\n")
            self._write_to_terminal("=" * 50 + "\n")
            self._write_to_terminal(_("Installation failed.") + "\n")
            self._write_to_terminal(_("Please check the errors above and try again.") + "\n")
            self._write_to_terminal("=" * 50 + "\n")
            
            self.install_button.set_visible(False)
            self.cancel_button.set_visible(False)
            self.close_button.set_visible(True)

    def get_result(self):
        """Get installation result."""
        return self.installation_success