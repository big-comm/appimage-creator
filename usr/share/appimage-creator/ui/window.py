"""
Main window for AppImage Creator - Refactored
"""

import os
import threading
from pathlib import Path
from gi.repository import Gtk, Adw, GLib, Gio

from core.builder import AppImageBuilder
from core.app_info import AppInfo
from core.structure_analyzer import detect_application_structure
from core.environment_manager import EnvironmentManager, SUPPORTED_ENVIRONMENTS
from core.settings import SettingsManager
from templates.app_templates import get_app_type_from_file, get_available_categories
from ui.pages import AppInfoPage, FilesPage, BuildPage, EnvironmentPage
from ui.dialogs import (BuildProgressDialog, LogProgressDialog, InstallPackagesDialog,
                        show_error_dialog, show_success_dialog, show_info_dialog, 
                        create_file_chooser, show_structure_viewer, show_desktop_file_viewer)
from utils.system import sanitize_filename, format_size
from utils.file_ops import scan_directory_structure
from validators.validators import ValidationError
from utils.i18n import _


class AppImageCreatorWindow(Adw.ApplicationWindow):
    """Main application window"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Data
        self.app_info = AppInfo()
        self.builder = AppImageBuilder()
        self.env_manager = EnvironmentManager()
        self.settings = SettingsManager()
        self.structure_analysis = None
        self.progress_dialog = None
        self.preferences_window = None
        
        # Create pages once
        self.app_info_page = AppInfoPage()
        self.files_page = FilesPage()
        self.build_page = BuildPage()
        self.env_page = EnvironmentPage()
        
        # Setup
        self.set_title(_("AppImage Creator"))
        self.set_default_size(820, 755)
        self.set_size_request(700, 500)
        self.set_resizable(True)
        
        self._setup_ui()
        self._setup_builder_callbacks()
        self._connect_signals()
        
    def _get_last_chooser_path(self) -> str:
        """Gets the last used path from JSON settings"""
        return self.settings.get('last-chooser-directory')

    def _set_last_chooser_path(self, file: Gio.File, is_folder: bool):
        """Sets the last used path in JSON settings from a Gio.File object"""
        if is_folder:
            path = file.get_path()
        else:
            path = file.get_parent().get_path()
        
        if path:
            self.settings.set('last-chooser-directory', path)
        
    def _setup_ui(self):
        """Setup the user interface"""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)
        
        # Header bar
        header_bar = Adw.HeaderBar()
        main_box.append(header_bar)
        
        # Preferences button in header
        prefs_button = Gtk.Button.new_from_icon_name("preferences-system-symbolic")
        prefs_button.set_tooltip_text(_("Advanced Settings"))
        prefs_button.connect("clicked", self._on_preferences_clicked)
        header_bar.pack_end(prefs_button)
        
        # Main content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        main_box.append(scrolled)
        
        clamp = Adw.Clamp()
        clamp.set_maximum_size(700)
        clamp.set_tightening_threshold(600)
        scrolled.set_child(clamp)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        clamp.set_child(content_box)
        
        # Welcome card
        self._create_welcome_card(content_box)
        
        # Quick setup card
        self._create_quick_setup_card(content_box)

    def _connect_signals(self):
        """Connect UI signals"""
        self.name_row.connect("changed", self._validate_inputs)
        self._connect_preferences_signals()
        
    def _create_welcome_card(self, parent):
        """Create welcome card"""
        welcome_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        welcome_container.add_css_class("card")
        welcome_container.set_margin_top(10)
        welcome_container.set_margin_bottom(16)
        welcome_container.set_margin_start(32)
        welcome_container.set_margin_end(32)
        
        icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_margin_top(5)
        
        app_icon = Gtk.Image.new_from_icon_name("appimage-creator")
        app_icon.set_pixel_size(64)
        app_icon.add_css_class("accent")
        icon_box.append(app_icon)
        welcome_container.append(icon_box)
        
        title = Gtk.Label(label=_("AppImage Creator"))
        title.add_css_class("title-1")
        title.set_margin_top(8)
        title.set_halign(Gtk.Align.CENTER)
        welcome_container.append(title)
        
        desc = Gtk.Label()
        desc.set_markup(_("Create distributable AppImages from any Linux application.\n<span size='large'>Supports Python, Qt, GTK, Java, and binary applications.</span>"))
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_halign(Gtk.Align.CENTER)
        desc.add_css_class("body")
        desc.set_margin_top(4)
        desc.set_margin_bottom(16)
        welcome_container.append(desc)
        
        parent.append(welcome_container)
        
    def _create_quick_setup_card(self, parent):
        """Create quick setup card"""
        # Main group
        group = Adw.PreferencesGroup()
        group.set_title(_("Quick Setup"))
        group.set_description(_("Get started quickly with basic information"))
        group.set_margin_start(16)
        group.set_margin_end(16)
        
        # App name
        self.name_row = Adw.EntryRow()
        self.name_row.set_title(_("Application Name"))
        group.add(self.name_row)
        
        # Executable
        self.executable_row = Adw.ActionRow()
        self.executable_row.set_title(_("Main Executable"))
        self.executable_row.set_subtitle(_("Select the main application file"))
        
        self.executable_button = Gtk.Button(label=_("Choose File"))
        self.executable_button.set_valign(Gtk.Align.CENTER)
        self.executable_button.connect("clicked", self._on_choose_executable)
        self.executable_row.add_suffix(self.executable_button)
        group.add(self.executable_row)
        
        # Icon
        self.icon_row = Adw.ActionRow()
        self.icon_row.set_title(_("Application Icon"))
        self.icon_row.set_subtitle(_("Optional: Choose an icon for your application"))
        
        self.icon_button = Gtk.Button(label=_("Choose Icon"))
        self.icon_button.set_valign(Gtk.Align.CENTER)
        self.icon_button.connect("clicked", self._on_choose_icon)
        self.icon_row.add_suffix(self.icon_button)
        group.add(self.icon_row)
        
        # Status
        self.status_row = Adw.ActionRow()
        self.status_row.set_title(_("Configuration Status"))
        self.status_row.set_subtitle(_("Complete setup to enable AppImage creation"))
        self.status_row.set_visible(False)
        group.add(self.status_row)
        
        parent.append(group)
        
        # Action buttons group
        buttons_group = Adw.PreferencesGroup()
        buttons_group.set_margin_top(24)
        buttons_group.set_margin_start(16)
        buttons_group.set_margin_end(16)
        
        # Build button
        build_row = Adw.ActionRow()
        build_row.set_title(_("Create AppImage"))
        build_row.set_subtitle(_("Generate your distributable AppImage file"))
        
        self.build_button = Gtk.Button(label=_("Create AppImage"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.set_valign(Gtk.Align.CENTER)
        self.build_button.connect("clicked", self._on_build_clicked)
        self.build_button.set_sensitive(False)
        build_row.add_suffix(self.build_button)
        buttons_group.add(build_row)
        
        # Advanced settings
        advanced_row = Adw.ActionRow()
        advanced_row.set_title(_("Advanced Settings"))
        advanced_row.set_subtitle(_("Configure authors, categories, and build options"))
        
        advanced_button = Gtk.Button(label=_("Open Settings"))
        advanced_button.set_valign(Gtk.Align.CENTER)
        advanced_button.connect("clicked", self._on_preferences_clicked)
        advanced_row.add_suffix(advanced_button)
        buttons_group.add(advanced_row)
        
        parent.append(buttons_group)
        
    def _setup_builder_callbacks(self):
        """Setup callbacks for the builder"""
        self.builder.set_progress_callback(self._on_build_progress)
        self.builder.set_log_callback(self._on_build_log)
        
    def _on_preferences_clicked(self, button):
        """Show preferences window"""
        self.preferences_window = Adw.PreferencesWindow()
        self.preferences_window.set_transient_for(self)
        self.preferences_window.set_modal(True)
        self.preferences_window.set_title(_("AppImage Creator Settings"))
        self.preferences_window.set_default_size(750, 700)
        
        # Create pages
        self.app_info_page = AppInfoPage()
        self.files_page = FilesPage()
        self.env_page = EnvironmentPage()
        self.build_page = BuildPage()
        
        self.preferences_window.add(self.app_info_page.page)
        self.preferences_window.add(self.files_page.page)
        self.preferences_window.add(self.env_page.page)
        self.preferences_window.add(self.build_page.page)
        
        # Connect signals after pages are created
        self._connect_preferences_signals()
        
        # Connect close handler to sync data back
        self.preferences_window.connect("close-request", self._on_preferences_closed)
        
        # Update data and show
        self._sync_to_preferences()
        self.env_page.update_status(self.env_manager)
        self._update_build_environments_list()
        
        # Restore previously selected build environment
        if self.app_info.build_environment:
            environments = self.env_manager.get_supported_environments()
            ready_envs = [env for env in environments if env['status'] == 'ready']
            for idx, env in enumerate(ready_envs):
                if env['id'] == self.app_info.build_environment:
                    self.build_page.environment_row.set_selected(idx + 1)
                    break
        else:
            self.build_page.environment_row.set_selected(0)
        
        self.preferences_window.present()
        
    def _connect_preferences_signals(self):
        """Connect signals for preferences window pages"""
        # App info page signals
        self.app_info_page.add_author_button.connect("clicked", 
            lambda btn: self.app_info_page.authors_list.add_entry())
        self.app_info_page.add_website_button.connect("clicked", 
            lambda btn: self.app_info_page.websites_list.add_entry())
        self.app_info_page.name_row.connect("changed", self._validate_inputs)
        
        # Files page signals
        self.files_page.executable_button.connect("clicked", self._on_choose_executable)
        self.files_page.icon_button.connect("clicked", self._on_choose_icon)
        self.files_page.add_dir_button.connect("clicked", self._on_add_directory)
        self.files_page.full_structure_button.connect("clicked", self._on_view_full_structure)
        self.files_page.view_desktop_button.connect("clicked", self._on_view_desktop_file)
        self.files_page.choose_desktop_button.connect("clicked", self._on_choose_desktop_file)
        self.files_page.use_existing_desktop_row.connect("notify::active", 
            self._on_use_existing_desktop_changed)
        
        # Environment page signals
        self.env_page.on_setup_clicked_callback = self._on_setup_environment_clicked
        self.env_page.on_install_packages_callback = self._on_install_packages_clicked
        self.env_page.on_remove_clicked_callback = self._on_remove_environment_clicked
        
        # Build page signals
        self.build_page.output_button.connect("clicked", self._on_choose_output_dir)
        self.build_page.build_button.connect("clicked", self._on_preferences_build_clicked)
        
    def _on_setup_environment_clicked(self, env_id: str):
        """Handles the click on the 'Setup' button for an environment"""
        env_spec = next((env for env in SUPPORTED_ENVIRONMENTS if env['id'] == env_id), None)
        if not env_spec:
            return
        
        # Create custom confirmation dialog
        dialog = Adw.Window()
        dialog.set_transient_for(self.preferences_window)
        dialog.set_modal(True)
        dialog.set_default_size(450, 400)
        dialog.set_resizable(False)
        
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)
        
        # Header with title centered
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        main_box.append(header)
        
        # Title label
        title_label = Gtk.Label(label=_("Setup Build Environment?"))
        title_label.add_css_class("title-2")
        header.set_title_widget(title_label)
        
        # Content box
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        main_box.append(content)
        
        # Info text - left aligned
        info_text = _("This will download and setup '{}'.\n\n"
                    "This process may take 5-15 minutes depending on your internet connection.\n\n"
                    "The following will be installed:").format(env_spec['name'])
        
        info_label = Gtk.Label(label=info_text)
        info_label.set_wrap(True)
        info_label.set_xalign(0)  # Left align
        info_label.set_justify(Gtk.Justification.LEFT)
        content.append(info_label)
        
        # Details in a card
        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details_box.add_css_class("card")
        details_box.set_margin_start(12)
        details_box.set_margin_end(12)
        details_box.set_margin_top(8)
        details_box.set_margin_bottom(8)
        content.append(details_box)
        
        image_label = Gtk.Label(label=f"• Container image: {env_spec['image']}")
        image_label.set_xalign(0)
        image_label.set_margin_start(12)
        image_label.set_margin_top(8)
        details_box.append(image_label)
        
        deps_label = Gtk.Label(label=f"• Build dependencies: {len(env_spec['build_deps'])} packages")
        deps_label.set_xalign(0)
        deps_label.set_margin_start(12)
        deps_label.set_margin_bottom(8)
        details_box.append(deps_label)
        
        # Question
        question_label = Gtk.Label(label=_("Do you want to continue?"))
        question_label.set_xalign(0)
        question_label.set_margin_top(8)
        content.append(question_label)
        
        # Buttons side by side at the bottom
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(16)
        content.append(button_box)
        
        cancel_button = Gtk.Button(label=_("Cancelar"))
        cancel_button.set_size_request(140, -1)
        cancel_button.connect("clicked", lambda btn: dialog.close())
        button_box.append(cancel_button)
        
        setup_button = Gtk.Button(label=_("Setup Environment"))
        setup_button.set_size_request(180, -1)
        setup_button.add_css_class("suggested-action")
        button_box.append(setup_button)
        
        def on_setup_clicked(btn):
            dialog.close()
            progress_dialog = LogProgressDialog(self.preferences_window, _("Setting Up Environment"))
            progress_dialog.present()
            
            thread = threading.Thread(
                target=self._run_environment_setup, 
                args=(env_id, progress_dialog), 
                daemon=True
            )
            thread.start()
        
        setup_button.connect("clicked", on_setup_clicked)
        
        dialog.present()

    def _run_environment_setup(self, env_id: str, dialog: LogProgressDialog):
        """The actual setup logic that runs in a thread"""
        try:
            def log_to_dialog(message):
                GLib.idle_add(dialog.add_log, message)

            GLib.idle_add(dialog.set_status, _("Creating container..."))
            self.env_manager.create_environment(env_id, log_callback=log_to_dialog)

            GLib.idle_add(dialog.set_status, _("Installing dependencies..."))
            self.env_manager.setup_environment_dependencies(env_id, log_callback=log_to_dialog)

            GLib.idle_add(dialog.finish, True)

        except Exception as e:
            error_message = _("Error: {}").format(e)
            GLib.idle_add(dialog.add_log, error_message)
            GLib.idle_add(dialog.finish, False)
        finally:
            GLib.idle_add(self.env_page.update_status, self.env_manager)
            GLib.idle_add(self._update_build_environments_list)
            
    def _on_remove_environment_clicked(self, env_id: str):
        """Handle remove environment button click"""
        env_spec = next((env for env in SUPPORTED_ENVIRONMENTS if env['id'] == env_id), None)
        if not env_spec:
            return
        
        # Confirmation dialog
        dialog = Adw.MessageDialog(transient_for=self.preferences_window)
        dialog.set_heading(_("Remove Environment?"))
        dialog.set_body(_("Are you sure you want to remove '{}'?\nThis will delete the container and all its data.").format(env_spec['name']))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        
        def on_response(dlg, response):
            if response == "remove":
                progress_dialog = LogProgressDialog(self.preferences_window, _("Removing Environment"))
                progress_dialog.present()
                
                thread = threading.Thread(
                    target=self._run_environment_removal,
                    args=(env_id, progress_dialog),
                    daemon=True
                )
                thread.start()
        
        dialog.connect("response", on_response)
        dialog.present()
    
    def _run_environment_removal(self, env_id: str, dialog: LogProgressDialog):
        """Run environment removal in thread"""
        try:
            def log_to_dialog(message):
                GLib.idle_add(dialog.add_log, message)
            
            GLib.idle_add(dialog.set_status, _("Removing container..."))
            self.env_manager.remove_environment(env_id, log_callback=log_to_dialog)
            
            GLib.idle_add(dialog.finish, True)
        except Exception as e:
            error_message = _("Error: {}").format(e)
            GLib.idle_add(dialog.add_log, error_message)
            GLib.idle_add(dialog.finish, False)
        finally:
            GLib.idle_add(self.env_page.update_status, self.env_manager)
            GLib.idle_add(self._update_build_environments_list)
            
    def _on_install_packages_clicked(self, env_manager):
        """Handle install packages button click"""
        install_info = env_manager.get_install_command()
        
        if not install_info:
            show_error_dialog(
                self.preferences_window,
                _("Cannot Install"),
                _("Unable to determine package manager for your distribution.")
            )
            return
        
        # Create and show install dialog
        dialog = InstallPackagesDialog(self.preferences_window, install_info)
        
        def on_dialog_destroy(widget):
            if hasattr(dialog, 'installation_success') and dialog.installation_success:
                # Refresh environment manager state
                self.env_manager = EnvironmentManager()
                GLib.idle_add(self.env_page.update_status, self.env_manager)
                
                def show_restart_dialog():
                    dialog = Adw.MessageDialog(transient_for=self.preferences_window)
                    dialog.set_heading(_("Installation Complete"))
                    dialog.set_body(_("Required packages were installed successfully!\n\n"
                                     "Please restart the application to use the new features."))
                    dialog.add_response("ok", _("OK"))
                    dialog.set_default_response("ok")
                    dialog.present()
                
                GLib.idle_add(show_restart_dialog)
        
        dialog.connect("close-request", on_dialog_destroy)
        dialog.present()
        
    def _validate_inputs(self, *args):
        """Validate inputs and update UI"""
        name = self.name_row.get_text().strip()
        executable = self.app_info.executable
        
        valid = len(name) > 0 and executable and os.path.exists(executable)
        
        self.build_button.set_sensitive(valid)
        self.build_page.build_button.set_sensitive(valid)
        
        # Update status
        if valid:
            self.status_row.set_visible(True)
            self.status_row.set_title(_("Ready to Build"))
            self.status_row.set_subtitle(_("All requirements met"))
        elif executable and os.path.exists(executable) and not name:
            self.status_row.set_visible(True)
            self.status_row.set_title(_("Almost Ready!"))
            self.status_row.set_subtitle(_("Please enter an Application Name"))
            self.name_row.add_css_class("error")
        elif name and not (executable and os.path.exists(executable)):
            self.status_row.set_visible(True)
            self.status_row.set_title(_("Select Executable"))
            self.status_row.set_subtitle(_("Please choose the main executable file"))
        else:
            self.status_row.set_visible(True)
            self.status_row.set_title(_("Getting Started"))
            self.status_row.set_subtitle(_("Enter name and select executable"))
        
        if name:
            self.name_row.remove_css_class("error")
        
    def _on_preferences_closed(self, window):
        """Handle preferences window close"""
        self._sync_from_preferences()
        return False
        
    def _update_build_environments_list(self):
        """Update the list of available build environments"""
        self.build_page.env_model.splice(0, self.build_page.env_model.get_n_items())
        
        # Always add local system as first option
        self.build_page.env_model.append(_("Local System (Current Python)"))
        
        # Add available containers
        environments = self.env_manager.get_supported_environments()
        for env in environments:
            if env['status'] == 'ready':
                self.build_page.env_model.append(f"{env['name']} (Container)")
        
        self.build_page.environment_row.set_selected(0)
        
    def _sync_to_preferences(self):
        """Sync main window data to preferences"""
        self.app_info_page.name_row.set_text(self.name_row.get_text())
        
        if self.app_info.executable:
            filename = os.path.basename(self.app_info.executable)
            self.files_page.executable_row.set_subtitle(filename)
        
        # Restore app type selection
        if self.app_info.app_type:
            types = ['binary', 'python', 'python_wrapper', 'shell', 'java', 'qt', 'gtk', 'electron']
            try:
                index = types.index(self.app_info.app_type)
                self.files_page.app_type_row.set_selected(index)
            except ValueError:
                pass
            
        if self.app_info.icon:
            filename = os.path.basename(self.app_info.icon)
            self.files_page.icon_row.set_subtitle(filename)
            
    def _sync_from_preferences(self):
        """Sync preferences back to main window"""
        self.name_row.set_text(self.app_info_page.name_row.get_text())
        
        # Save selected app type
        if self.files_page and self.files_page.app_type_row:
            types = ['binary', 'python', 'python_wrapper', 'shell', 'java', 'qt', 'gtk', 'electron']
            selected = self.files_page.app_type_row.get_selected()
            if selected < len(types):
                self.app_info.app_type = types[selected]
        
        # Save selected build environment
        if self.build_page and self.build_page.environment_row:
            selected_idx = self.build_page.environment_row.get_selected()
            if selected_idx == 0:
                self.app_info.build_environment = None
            else:
                environments = self.env_manager.get_supported_environments()
                ready_envs = [env for env in environments if env['status'] == 'ready']
                if selected_idx - 1 < len(ready_envs):
                    self.app_info.build_environment = ready_envs[selected_idx - 1]['id']
        
        self._validate_inputs()
        
    def _on_choose_executable(self, button):
        """Handle executable file selection"""
        parent = self.preferences_window if (self.preferences_window and self.preferences_window.is_visible()) else self
        
        filters = {
            _("Executable Files"): ["*.py", "*.sh", "*.jar", "*"],
            _("All Files"): ["*"]
        }
        
        create_file_chooser(parent, _("Choose Executable"), 
                        Gtk.FileChooserAction.OPEN, filters,
                        self._on_executable_selected, self.settings)
        
    def _on_executable_selected(self, dialog, response):
        """Handle executable file selection response"""
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.executable = path
                
                # Update UI - main window
                filename = os.path.basename(path)
                self.executable_row.set_subtitle(_("Selected: {}").format(filename))
                
                # Update UI - preferences window
                self.files_page.executable_row.set_subtitle(filename)
                
                # Analyze structure
                self.structure_analysis = detect_application_structure(path)
                
                # Auto-detect app type and store it
                app_type = get_app_type_from_file(path, self.structure_analysis)
                self.app_info.app_type = app_type  # Store in app_info
                
                # Update UI if preferences window exists
                if self.files_page:
                    type_mapping = {'binary': 0, 'python': 1, 'python_wrapper': 2, 
                                'shell': 3, 'java': 4, 'qt': 5, 'gtk': 6, 'electron': 7}
                    if app_type in type_mapping:
                        self.files_page.app_type_row.set_selected(type_mapping[app_type])
                
                # Auto-fill name if empty
                if not self.name_row.get_text().strip():
                    suggested_name = os.path.splitext(filename)[0]
                    suggested_name = suggested_name.replace('-gui', '').replace('-cli', '')
                    suggested_name = suggested_name.replace('_', ' ').title()
                    
                    if suggested_name and len(suggested_name) > 2:
                        self.name_row.set_text(suggested_name)
                        if self.app_info_page:
                            self.app_info_page.name_row.set_text(suggested_name)
                
                # Update UI with detected files
                if self.files_page:
                    self._update_detected_files()
                    self._update_additional_directories_from_analysis()
                    self._update_desktop_file_options()
                    self._update_structure_preview()
                
                self._show_next_steps_message()
                self._validate_inputs()
                
        dialog.destroy()
        
    def _on_choose_icon(self, button):
        """Handle icon file selection"""
        parent = self.preferences_window if (self.preferences_window and self.preferences_window.is_visible()) else self
        
        filters = {_("Image Files"): ["*.png", "*.svg", "*.jpg", "*.ico"]}
        
        create_file_chooser(parent, _("Choose Icon"), 
                        Gtk.FileChooserAction.OPEN, filters,
                        self._on_icon_selected, self.settings)
        
    def _on_icon_selected(self, dialog, response):
        """Handle icon selection response"""
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.icon = path
                
                filename = os.path.basename(path)
                self.icon_row.set_subtitle(_("Selected: {}").format(filename))
                
                if self.files_page:
                    self.files_page.icon_row.set_subtitle(filename)
                
        dialog.destroy()
        
    def _on_add_directory(self, button):
        """Handle add directory"""
        create_file_chooser(self.preferences_window, _("Add Directory"), 
                           Gtk.FileChooserAction.SELECT_FOLDER, None,
                           self._on_directory_selected, self.settings)
        
    def _on_directory_selected(self, dialog, response):
        """Handle directory selection response"""
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                if self.files_page:
                    self.files_page.directory_list.add_directory(path)
                    self._update_structure_preview()
                
        dialog.destroy()
        
    def _on_choose_output_dir(self, button):
        """Handle output directory selection"""
        create_file_chooser(self.preferences_window, _("Choose Output Directory"), 
                           Gtk.FileChooserAction.SELECT_FOLDER, None,
                           self._on_output_dir_selected, self.settings)
        
    def _on_output_dir_selected(self, dialog, response):
        """Handle output directory selection response"""
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.output_dir = path
                
                if self.build_page:
                    self.build_page.output_row.set_subtitle(path)
                
        dialog.destroy()
        
    def _update_detected_files(self):
        """Update detected files display"""
        if not self.structure_analysis:
            self.files_page.detected_group.set_visible(False)
            return
            
        detected_files = self.structure_analysis.get('detected_files', {})
        filtered = {k: v for k, v in detected_files.items() if k != 'desktop_files'}
        
        if any(filtered.values()):
            self.files_page.detected_group.set_visible(True)
            self.files_page.detected_files.update(detected_files)
        else:
            self.files_page.detected_group.set_visible(False)
            
    def _update_additional_directories_from_analysis(self):
        """Update additional directories from analysis"""
        if not self.structure_analysis:
            return
            
        suggested = self.structure_analysis.get('suggested_additional_dirs', [])
        for dir_path in suggested:
            if os.path.exists(dir_path):
                self.files_page.directory_list.add_directory(dir_path)
                
    def _update_desktop_file_options(self):
        """Update desktop file options"""
        if not self.structure_analysis:
            self.files_page.desktop_file_group.set_visible(False)
            return
            
        detected_desktop = self.structure_analysis.get('detected_files', {}).get('desktop_files', [])
        
        if detected_desktop:
            self.files_page.desktop_file_group.set_visible(True)
            self.app_info.detected_desktop_file = detected_desktop[0]
            
            filename = os.path.basename(detected_desktop[0])
            self.files_page.found_desktop_row.set_subtitle(_("Found: {}").format(filename))
            self.files_page.use_existing_desktop_row.set_active(True)
            self.app_info.use_existing_desktop = True
        else:
            self.files_page.desktop_file_group.set_visible(False)
            self.app_info.use_existing_desktop = False
            
    def _on_use_existing_desktop_changed(self, switch_row, param):
        """Handle desktop file toggle"""
        self.app_info.use_existing_desktop = switch_row.get_active()
        
    def _on_view_desktop_file(self, button):
        """View desktop file content"""
        if self.app_info.detected_desktop_file and os.path.exists(self.app_info.detected_desktop_file):
            show_desktop_file_viewer(self.preferences_window, self.app_info.detected_desktop_file)
            
    def _on_choose_desktop_file(self, button):
        """Choose custom desktop file"""
        filters = {_("Desktop Files"): ["*.desktop"]}
        create_file_chooser(self.preferences_window, _("Choose Desktop File"), 
                           Gtk.FileChooserAction.OPEN, filters,
                           self._on_desktop_file_selected, self.settings)
        
    def _on_desktop_file_selected(self, dialog, response):
        """Handle desktop file selection"""
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.custom_desktop_file = path
                
                filename = os.path.basename(path)
                self.files_page.manual_desktop_row.set_subtitle(_("Selected: {}").format(filename))
                self.files_page.use_existing_desktop_row.set_active(False)
                
        dialog.destroy()
        
    def _update_structure_preview(self):
        """Update structure preview"""
        if not self.app_info.executable:
            self.files_page.preview_group.set_visible(False)
            return
            
        self.files_page.preview_group.set_visible(True)
        
        app_name = sanitize_filename(self.name_row.get_text() or "MyApp")
        preview_lines = [
            _("AppImage Overview:"),
            _("   App: {}").format(app_name),
            _("   Type: {}").format(self._get_current_app_type()),
        ]
        
        dirs = self.files_page.directory_list.get_directories()
        if dirs:
            preview_lines.append(_("   Additional Dirs: {}").format(len(dirs)))
            
        if self.structure_analysis:
            detected = self.structure_analysis.get('detected_files', {})
            total = sum(len(files) for files in detected.values())
            if total > 0:
                preview_lines.append(_("   Auto-detected: {} files").format(total))
        
        preview_lines.append("")
        preview_lines.append(_("Click 'View Full Structure' for details"))
        
        buffer = self.files_page.preview_text.get_buffer()
        buffer.set_text("\n".join(preview_lines))
        
    def _get_current_app_type(self):
        """Get current app type as string"""
        types = ['binary', 'python', 'python_wrapper', 'shell', 'java', 'qt', 'gtk', 'electron']
        selected = self.files_page.app_type_row.get_selected()
        return types[selected] if selected < len(types) else 'unknown'
        
    def _on_view_full_structure(self, button):
        """Show full structure view"""
        if not self.app_info.executable:
            return
            
        structure_text = self._generate_detailed_structure()
        show_structure_viewer(self.preferences_window, 
                            _("AppImage Structure - Full View"), 
                            structure_text)
        
    def _generate_detailed_structure(self):
        """Generate detailed structure text"""
        lines = [_("AppImage Structure - Detailed View"), "=" * 50, ""]
        
        app_name = sanitize_filename(self.name_row.get_text() or "MyApp")
        
        lines.append(_("[AppImage Root]"))
        lines.append(_("├── AppRun (main launcher)"))
        lines.append(f"├── {app_name}.desktop")
        lines.append(f"├── {app_name}.svg")
        lines.append(_("└── usr/"))
        lines.append(_("    ├── bin/"))
        lines.append(f"    │   └── {app_name} (launcher)")
        lines.append(_("    ├── lib/"))
        lines.append(_("    └── share/"))
        lines.append(f"        ├── {app_name}/")
        
        if self.app_info.executable:
            main_file = os.path.basename(self.app_info.executable)
            lines.append(f"        │   └── {main_file}")
        
        # Additional directories
        dirs = self.files_page.directory_list.get_directories()
        if dirs:
            lines.append("        │")
            for i, directory in enumerate(dirs):
                is_last = i == len(dirs) - 1
                prefix = "        └── " if is_last else "        ├── "
                
                try:
                    structure = scan_directory_structure(directory)
                    dir_name = os.path.basename(directory)
                    file_count = len(structure.get('files', []))
                    total_size = structure.get('total_size', 0)
                    lines.append(f"{prefix}{dir_name}/ ({file_count} files, {format_size(total_size)})")
                except Exception as e:
                    dir_name = os.path.basename(directory)
                    lines.append(f"{prefix}{dir_name}/ (error: {e})")
        
        lines.append("")
        lines.append(_("Summary:"))
        lines.append("-" * 30)
        lines.append(_("Application Type: {}").format(self._get_current_app_type()))
        lines.append(_("Additional Directories: {}").format(len(dirs)))
        
        if self.structure_analysis:
            detected = self.structure_analysis.get('detected_files', {})
            total = sum(len(files) for files in detected.values())
            lines.append(_("Auto-detected Files: {}").format(total))
        
        return "\n".join(lines)
        
    def _show_next_steps_message(self):
        """Show next steps message"""
        name = self.name_row.get_text().strip()
        
        self.status_row.set_visible(True)
        
        if not name:
            self.status_row.set_title(_("Tip"))
            self.status_row.set_subtitle(_("Enter an Application Name above to continue"))
        else:
            self.status_row.set_title(_("Ready!"))
            self.status_row.set_subtitle(_("Ready to create AppImage! Click 'Create AppImage' when ready."))
            
        GLib.timeout_add_seconds(4, self._remove_status_styling)
        
    def _remove_status_styling(self):
        """Remove status row styling"""
        try:
            self._validate_inputs()
        except:
            pass
        return False
            
    def _collect_app_info(self):
        """Collect app info from UI"""
        self.app_info.name = self.name_row.get_text().strip()
        self.app_info.version = self.app_info_page.version_row.get_text().strip() or "1.0.0"
        self.app_info.description = self.app_info_page.description_row.get_text().strip()
        
        # Ensure executable_name is set from the actual selected file
        if self.app_info.executable:
            self.app_info.executable_name = os.path.basename(self.app_info.executable)
        
        # Authors and websites
        self.app_info.authors = self.app_info_page.authors_list.get_values()
        if not self.app_info.authors:
            self.app_info.authors = ["Unknown"]
            
        self.app_info.websites = self.app_info_page.websites_list.get_values()
        
        # Categories
        categories = get_available_categories()
        selected = self.app_info_page.category_row.get_selected()
        self.app_info.categories = [categories[selected]]
        
        # App type
        types = ['binary', 'python', 'python_wrapper', 'shell', 'java', 'qt', 'gtk', 'electron']
        selected = self.files_page.app_type_row.get_selected()
        self.app_info.app_type = types[selected]
        
        # Other settings
        self.app_info.terminal = self.app_info_page.terminal_row.get_active()
        self.app_info.additional_directories = self.files_page.directory_list.get_directories()
        self.app_info.structure_analysis = self.structure_analysis
        
        # Build settings
        self.app_info.include_dependencies = self.build_page.deps_row.get_active()
        self.app_info.strip_binaries = self.build_page.strip_row.get_active()
        
        # Get selected environment
        if self.build_page.environment_row:
            selected_idx = self.build_page.environment_row.get_selected()
            if selected_idx == 0:
                self.app_info.build_environment = None
            else:
                environments = self.env_manager.get_supported_environments()
                ready_envs = [env for env in environments if env['status'] == 'ready']
                if selected_idx - 1 < len(ready_envs):
                    self.app_info.build_environment = ready_envs[selected_idx - 1]['id']
        else:
            self.app_info.build_environment = None
        
    def _on_build_clicked(self, button):
        """Start build process"""
        try:
            self._collect_app_info()
            self.builder.set_app_info(self.app_info.to_dict())
            
            self.progress_dialog = BuildProgressDialog(self)
            self.progress_dialog.cancel_button.connect("clicked", self._on_cancel_build)
            self.progress_dialog.present()
            
            self.builder.build_async(self._on_build_complete)
            
        except ValidationError as e:
            show_error_dialog(self, _("Validation Error"), str(e))
        except Exception as e:
            show_error_dialog(self, _("Error"), _("Failed to start build: {}").format(e))
            
    def _on_preferences_build_clicked(self, button):
        """Build from preferences window"""
        try:
            self._sync_from_preferences()
            self.preferences_window.close()
            self._on_build_clicked(button)
        except Exception as e:
            show_error_dialog(self.preferences_window, _("Error"), str(e))
            
    def _on_build_progress(self, percentage, message):
        """Handle build progress"""
        GLib.idle_add(self._update_progress_ui, percentage, message)
        
    def _update_progress_ui(self, percentage, message):
        """Update progress UI"""
        if self.progress_dialog:
            self.progress_dialog.update_progress(percentage, message)
        return False
        
    def _on_build_log(self, message):
        """Handle build log"""
        print(f"Build: {message}")
        
    def _on_cancel_build(self, button):
        """Cancel build"""
        if self.builder:
            self.builder.cancel_build()
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
    def _on_build_complete(self, result, error):
        """Handle build completion"""
        GLib.idle_add(self._handle_build_result, result, error)
        
    def _handle_build_result(self, result, error):
        """Handle build result"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
        if error:
            show_error_dialog(self, _("Build Failed"), str(error))
        elif result:
            def on_response(dialog, response):
                if response == "open":
                    try:
                        Gio.app_info_launch_default_for_uri(f"file://{Path.cwd()}", None)
                    except:
                        pass
                        
            show_success_dialog(self, _("Build Complete"), 
                              _("AppImage created successfully:\n{}").format(result),
                              on_response)
        else:
            show_info_dialog(self, _("Build Cancelled"), _("Build was cancelled"))
            
        return False