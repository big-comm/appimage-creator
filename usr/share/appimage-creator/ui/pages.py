"""
Preference pages for AppImage Creator
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from pathlib import Path
from templates.app_templates import get_available_categories
from ui.widgets import DynamicEntryList, DirectoryListWidget, DetectedFilesWidget
from utils.i18n import _


class AppInfoPage:
    """Application information preferences page"""
    
    def __init__(self):
        self.page = Adw.PreferencesPage()
        self.page.set_title(_("App"))
        self.page.set_icon_name("application-x-executable-symbolic")
        
        # Widgets we need to access
        self.name_row = None
        self.version_row = None
        self.description_row = None
        self.category_row = None # Re-added
        self.terminal_row = None # Re-added
        self.update_url_row = None
        self.update_pattern_row = None
        
        self._build_page()
        
    def _build_page(self):
        """Build the page UI"""
        # Basic info group
        basic_group = Adw.PreferencesGroup()
        basic_group.set_title(_("Basic Information"))
        
        self.name_row = Adw.EntryRow()
        self.name_row.set_title(_("Application Name"))
        basic_group.add(self.name_row)
        
        self.version_row = Adw.EntryRow()
        self.version_row.set_title(_("Version"))
        self.version_row.set_text("1.0.0")
        basic_group.add(self.version_row)
        
        self.description_row = Adw.EntryRow()
        self.description_row.set_title(_("Description"))
        basic_group.add(self.description_row)
        
        self.page.add(basic_group)
        
        # Categories group (RESTORED)
        cat_group = Adw.PreferencesGroup()
        cat_group.set_title(_("Categories"))
        
        self.category_row = Adw.ComboRow()
        self.category_row.set_title(_("Primary Category"))
        
        category_model = Gtk.StringList()
        for category in get_available_categories():
            category_model.append(category)
        self.category_row.set_model(category_model)
        self.category_row.set_selected(12)  # Utility (default)
        cat_group.add(self.category_row)
        
        self.terminal_row = Adw.SwitchRow()
        self.terminal_row.set_title(_("Requires Terminal"))
        self.terminal_row.set_subtitle(_("Check if your application needs to run in a terminal"))
        cat_group.add(self.terminal_row)

        self.page.add(cat_group)

        # Auto-update group
        update_group = Adw.PreferencesGroup()
        update_group.set_title(_("Auto-Update (Optional)"))
        update_group.set_description(_("Enable automatic update checking for this AppImage"))

        self.update_url_row = Adw.EntryRow()
        self.update_url_row.set_title(_("Update URL"))
        self.update_url_row.set_text("")
        # Set placeholder text showing the template
        self.update_url_row.props.text = ""
        if hasattr(self.update_url_row, 'set_placeholder_text'):
            # GTK 4.14+
            self.update_url_row.set_placeholder_text("https://api.github.com/repos/OWNER/REPO/releases/latest")

        # Add "Paste Template" button (fills with GitHub API template)
        use_template_button = Gtk.Button()
        use_template_button.set_icon_name("edit-paste-symbolic")
        use_template_button.set_valign(Gtk.Align.CENTER)
        use_template_button.set_tooltip_text(_("Paste GitHub API template"))
        use_template_button.add_css_class("flat")
        use_template_button.connect("clicked", self._on_use_github_template)
        self.update_url_row.add_suffix(use_template_button)

        update_group.add(self.update_url_row)

        # Add expander with help text
        help_expander = Adw.ExpanderRow()
        help_expander.set_title(_("How to configure auto-updates"))
        help_expander.set_subtitle(_("Click to see examples"))

        help_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        help_box.set_margin_start(12)
        help_box.set_margin_end(12)
        help_box.set_margin_top(6)
        help_box.set_margin_bottom(6)

        help_text = Gtk.Label()
        help_text.set_markup(
            _("<b>GitHub Releases (recommended):</b>\n"
              "Click the button next to Update URL to fill with template, then edit OWNER/REPO\n\n"
              "<b>Example:</b>\n"
              "https://api.github.com/repos/biglinux/big-video-converter/releases/latest\n\n"
              "<b>Filename Pattern:</b>\n"
              "Used to identify which file to download from the release.\n"
              "The asterisk (*) matches any text.\n\n"
              "<b>Pattern Examples:</b>\n"
              "• myapp-*-x86_64.AppImage  → matches: myapp-v1.2.3-x86_64.AppImage\n"
              "• *-gui-*.AppImage  → matches: converter-gui-1.0.AppImage\n"
              "• calculator-*.AppImage  → matches: calculator-2.5-linux.AppImage")
        )
        help_text.set_wrap(True)
        help_text.set_xalign(0)
        help_box.append(help_text)

        help_expander.add_row(help_box)
        update_group.add(help_expander)

        self.update_pattern_row = Adw.EntryRow()
        self.update_pattern_row.set_title(_("Filename Pattern"))
        self.update_pattern_row.set_text("*-x86_64.AppImage")
        update_group.add(self.update_pattern_row)

        self.page.add(update_group)

    def _on_use_github_template(self, button):
        """Fill the Update URL field with GitHub API template"""
        template = "https://api.github.com/repos/OWNER/REPO/releases/latest"

        # Set the text in the entry
        self.update_url_row.set_text(template)

        # Focus the field and select "OWNER/REPO" for easy editing
        # Position cursor at the start of OWNER
        self.update_url_row.grab_focus()

        # Try to select just the OWNER/REPO part
        # Calculate positions: "https://api.github.com/repos/" = 30 chars
        # "OWNER/REPO" starts at position 30
        start_pos = 30
        end_pos = start_pos + len("OWNER/REPO")

        # Select the text for easy replacement
        # Note: GTK4 EntryRow might not support select_region directly
        # but the user can easily see and edit OWNER/REPO


class FilesPage:
    """Files and resources preferences page"""
    
    def __init__(self):
        self.page = Adw.PreferencesPage()
        self.page.set_title(_("Files"))
        self.page.set_icon_name("folder-symbolic")
        
        # Widgets we need to access
        self.executable_row = None
        self.app_type_row = None
        self.icon_row = None
        self.desktop_file_group = None
        self.use_existing_desktop_row = None
        self.found_desktop_row = None
        self.manual_desktop_row = None
        self.detected_group = None
        self.preview_group = None
        self.preview_text = None
        
        self._build_page()
        
    def _build_page(self):
        """Build the page UI"""
        # Main files group
        files_group = Adw.PreferencesGroup()
        files_group.set_title(_("Application Files"))
        
        self.executable_row = Adw.ActionRow()
        self.executable_row.set_title(_("Main Executable"))
        self.executable_row.set_subtitle(_("Select the main application file"))
        
        self.executable_button = Gtk.Button(label=_("Choose File"))
        self.executable_button.set_valign(Gtk.Align.CENTER)
        self.executable_row.add_suffix(self.executable_button)
        files_group.add(self.executable_row)
        
        self.app_type_row = Adw.ComboRow()
        self.app_type_row.set_title(_("Application Type"))
        self.app_type_row.set_subtitle(_("Auto-detected from executable"))
        
        type_model = Gtk.StringList()
        app_types = [_("Binary"), _("Python"), _("Python Wrapper"), _("Shell Script"), 
                     _("Java"), _("Qt"), _("GTK"), _("Electron")]
        for app_type in app_types:
            type_model.append(app_type)
        self.app_type_row.set_model(type_model)
        self.app_type_row.set_selected(0)
        files_group.add(self.app_type_row)
        
        self.page.add(files_group)
        
        # Additional directories
        additional_group = Adw.PreferencesGroup()
        additional_group.set_title(_("Additional Directories"))
        additional_group.set_description(_("Include extra directories like locale files, plugins, or data"))
        
        add_dir_row = Adw.ActionRow()
        add_dir_row.set_title(_("Add Directory"))
        add_dir_row.set_subtitle(_("Include additional files and directories"))
        
        self.add_dir_button = Gtk.Button(label=_("Add Directory"))
        self.add_dir_button.set_valign(Gtk.Align.CENTER)
        add_dir_row.add_suffix(self.add_dir_button)
        additional_group.add(add_dir_row)
        
        self.additional_dirs_listbox = Gtk.ListBox()
        self.additional_dirs_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.additional_dirs_listbox.add_css_class("boxed-list")
        additional_group.add(self.additional_dirs_listbox)
        
        self.directory_list = DirectoryListWidget(self.additional_dirs_listbox)
        
        self.page.add(additional_group)
        
        # Auto-detected files
        self.detected_group = Adw.PreferencesGroup()
        self.detected_group.set_title(_("Auto-detected Files"))
        self.detected_group.set_description(_("Files automatically found for your application"))
        self.detected_group.set_visible(False)
        
        self.detected_listbox = Gtk.ListBox()
        self.detected_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.detected_listbox.add_css_class("boxed-list")
        self.detected_group.add(self.detected_listbox)
        
        self.detected_files = DetectedFilesWidget(self.detected_listbox)
        
        self.page.add(self.detected_group)
        
        # Desktop file group
        self.desktop_file_group = Adw.PreferencesGroup()
        self.desktop_file_group.set_title(_("Desktop File"))
        self.desktop_file_group.set_visible(False)
        
        self.use_existing_desktop_row = Adw.SwitchRow()
        self.use_existing_desktop_row.set_title(_("Use Existing Desktop File"))
        self.use_existing_desktop_row.set_subtitle(_("Found desktop file in application"))
        self.use_existing_desktop_row.set_active(True)
        self.desktop_file_group.add(self.use_existing_desktop_row)
        
        self.found_desktop_row = Adw.ActionRow()
        self.found_desktop_row.set_title(_("Detected Desktop File"))
        self.found_desktop_row.set_subtitle(_("No desktop file detected"))
        
        self.view_desktop_button = Gtk.Button(label=_("View"))
        self.view_desktop_button.set_valign(Gtk.Align.CENTER)
        self.found_desktop_row.add_suffix(self.view_desktop_button)
        self.desktop_file_group.add(self.found_desktop_row)
        
        self.manual_desktop_row = Adw.ActionRow()
        self.manual_desktop_row.set_title(_("Custom Desktop File"))
        self.manual_desktop_row.set_subtitle(_("Or select a different .desktop file"))
        
        self.choose_desktop_button = Gtk.Button(label=_("Choose File"))
        self.choose_desktop_button.set_valign(Gtk.Align.CENTER)
        self.manual_desktop_row.add_suffix(self.choose_desktop_button)
        self.desktop_file_group.add(self.manual_desktop_row)
        
        self.page.add(self.desktop_file_group)
        
        # Resources group
        resources_group = Adw.PreferencesGroup()
        resources_group.set_title(_("Resources"))
        
        self.icon_row = Adw.ActionRow()
        self.icon_row.set_title(_("Application Icon"))
        self.icon_row.set_subtitle(_("PNG, SVG, or other image format"))
        
        self.icon_button = Gtk.Button(label=_("Choose Icon"))
        self.icon_button.set_valign(Gtk.Align.CENTER)
        self.icon_row.add_suffix(self.icon_button)
        resources_group.add(self.icon_row)
        
        self.page.add(resources_group)
        
        # Preview group
        self.preview_group = Adw.PreferencesGroup()
        self.preview_group.set_title(_("Structure Preview"))
        self.preview_group.set_description(_("Preview of what will be included in the AppImage"))
        self.preview_group.set_visible(False)
        
        preview_header = Adw.ActionRow()
        preview_header.set_title(_("Quick Preview"))
        preview_header.set_subtitle(_("See basic structure overview"))
        
        self.full_structure_button = Gtk.Button(label=_("View Full Structure"))
        self.full_structure_button.set_valign(Gtk.Align.CENTER)
        preview_header.add_suffix(self.full_structure_button)
        self.preview_group.add(preview_header)
        
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        preview_scroll.set_max_content_height(100)
        
        self.preview_text = Gtk.TextView()
        self.preview_text.set_editable(False)
        self.preview_text.set_cursor_visible(False)
        self.preview_text.add_css_class("monospace")
        preview_scroll.set_child(self.preview_text)
        
        self.preview_group.add(preview_scroll)
        self.page.add(self.preview_group)


class BuildPage:
    """Build settings preferences page"""
    
    def __init__(self):
        self.page = Adw.PreferencesPage()
        self.page.set_title(_("Build"))
        self.page.set_icon_name("builder-symbolic")
        
        # Widgets we need to access
        self.output_row = None
        self.deps_row = None
        self.strip_row = None
        self.build_button = None
        self.environment_row = None
        self.env_model = None
        
        self._build_page()
        
    def _build_page(self):
        """Build the page UI"""
        # Output group
        output_group = Adw.PreferencesGroup()
        output_group.set_title(_("Output Settings"))
        
        self.output_row = Adw.ActionRow()
        self.output_row.set_title(_("Output Directory"))
        self.output_row.set_subtitle(str(Path.cwd()))
        
        self.output_button = Gtk.Button(label=_("Choose Folder"))
        self.output_button.set_valign(Gtk.Align.CENTER)
        self.output_row.add_suffix(self.output_button)
        output_group.add(self.output_row)
        
        self.page.add(output_group)
        
        # Environment selection group
        env_group = Adw.PreferencesGroup()
        env_group.set_title(_("Build Environment"))
        env_group.set_description(_("Choose where to build the AppImage"))
        
        self.environment_row = Adw.ComboRow()
        self.environment_row.set_title(_("Build Environment"))
        self.environment_row.set_subtitle(_("Select container or use local system"))
        
        self.env_model = Gtk.StringList()
        self.env_model.append(_("Local System (Current Python)"))
        self.environment_row.set_model(self.env_model)
        self.environment_row.set_selected(0)
        env_group.add(self.environment_row)
        
        self.page.add(env_group)
        
        # Advanced group
        advanced_group = Adw.PreferencesGroup()
        advanced_group.set_title(_("Advanced Options"))
        
        self.deps_row = Adw.SwitchRow()
        self.deps_row.set_title(_("Include Dependencies"))
        self.deps_row.set_subtitle(_("Automatically include system dependencies"))
        self.deps_row.set_active(True)
        advanced_group.add(self.deps_row)

        # Expander for detailed dependency selection
        self.deps_expander_row = Adw.ExpanderRow()
        self.deps_expander_row.set_title(_("System Dependencies"))
        self.deps_expander_row.set_subtitle(_("Select which system libraries to bundle"))
        self.deps_expander_row.set_show_enable_switch(False)
        advanced_group.add(self.deps_expander_row)

        self.deps_list_box = Gtk.ListBox()
        self.deps_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.deps_list_box.add_css_class("boxed-list")
        self.deps_expander_row.add_row(self.deps_list_box)

        # Icon theme selection
        self.icon_theme_row = Adw.SwitchRow()
        self.icon_theme_row.set_title(_("Include Icon Theme"))
        self.icon_theme_row.set_subtitle(_("Bundle icons for consistent UI across systems"))
        self.icon_theme_row.set_active(True)
        advanced_group.add(self.icon_theme_row)

        # Expander for icon theme selection
        self.icon_theme_expander_row = Adw.ExpanderRow()
        self.icon_theme_expander_row.set_title(_("Icon Theme Selection"))
        self.icon_theme_expander_row.set_subtitle(_("Choose which icon theme to bundle"))
        self.icon_theme_expander_row.set_show_enable_switch(False)
        advanced_group.add(self.icon_theme_expander_row)

        # Radio buttons for icon theme choice
        papirus_row = Adw.ActionRow()
        papirus_row.set_title(_("Papirus"))
        papirus_row.set_subtitle(_("Modern, colorful icons (~6.4MB) - Default for GTK apps"))
        self.papirus_radio = Gtk.CheckButton()
        self.papirus_radio.set_active(True)
        papirus_row.add_prefix(self.papirus_radio)
        papirus_row.set_activatable_widget(self.papirus_radio)
        self.icon_theme_expander_row.add_row(papirus_row)

        adwaita_row = Adw.ActionRow()
        adwaita_row.set_title(_("Adwaita"))
        adwaita_row.set_subtitle(_("GNOME default icons (~2.6MB)"))
        self.adwaita_radio = Gtk.CheckButton()
        self.adwaita_radio.set_group(self.papirus_radio)
        adwaita_row.add_prefix(self.adwaita_radio)
        adwaita_row.set_activatable_widget(self.adwaita_radio)
        self.icon_theme_expander_row.add_row(adwaita_row)

        self.strip_row = Adw.SwitchRow()
        self.strip_row.set_title(_("Strip Debug Symbols"))
        self.strip_row.set_subtitle(_("Reduce file size by removing debug information"))
        self.strip_row.set_active(False)
        advanced_group.add(self.strip_row)
        
        self.page.add(advanced_group)
        
        # Build action group
        build_group = Adw.PreferencesGroup()
        build_group.set_title(_("Build AppImage"))
        build_group.set_description(_("Create your AppImage with current settings"))
        
        build_row = Adw.ActionRow()
        build_row.set_title(_("Generate AppImage"))
        build_row.set_subtitle(_("Create AppImage with configured settings"))
        
        self.build_button = Gtk.Button(label=_("Create AppImage"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.set_valign(Gtk.Align.CENTER)
        self.build_button.set_sensitive(False)
        build_row.add_suffix(self.build_button)
        
        build_group.add(build_row)
        self.page.add(build_group)


class EnvironmentPage:
    """Build environment preferences page"""

    def __init__(self):
        self.page = Adw.PreferencesPage()
        self.page.set_title(_("Environment"))
        self.page.set_icon_name("box-seam-symbolic")

        # Widgets we need to access
        self.host_status_group = None
        self.environments_group = None
        self.environments_listbox = None
        self.status_row = None
        self.on_setup_clicked_callback = None
        self.on_install_packages_callback = None
        self.on_remove_clicked_callback = None

        self._build_page()

    def _build_page(self):
        """Build the page UI"""
        # Host System Status group
        self.host_status_group = Adw.PreferencesGroup()
        self.host_status_group.set_title(_("Host System Status"))
        self.host_status_group.set_description(_("Required tools for creating compatible AppImages"))
        self.page.add(self.host_status_group)

        self.status_row = Adw.ActionRow()
        self.status_row.set_title(_("Checking host system..."))
        self.host_status_group.add(self.status_row)

        # Available Build Environments group
        self.environments_group = Adw.PreferencesGroup()
        self.environments_group.set_title(_("Available Build Environments"))
        self.environments_group.set_description(_("Select an environment to build your AppImage for maximum compatibility"))
        self.environments_group.set_visible(False)
        self.page.add(self.environments_group)

        self.environments_listbox = Gtk.ListBox()
        self.environments_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.environments_listbox.add_css_class("boxed-list")
        self.environments_group.add(self.environments_listbox)

    def update_status(self, env_manager):
        """Update the page with the latest status from EnvironmentManager"""
        host_status = env_manager.get_host_status()

        # Remove any suffix widgets
        try:
            last_child = self.status_row.get_last_child()
            if last_child and isinstance(last_child, Gtk.Button):
                self.status_row.remove(last_child)
        except:
            pass

        # Update host status display
        if host_status['is_ready']:
            self.status_row.set_title(_("Host is Ready"))
            self.status_row.set_subtitle(_("Distrobox and a container runtime are installed."))
            self.status_row.set_icon_name("emblem-ok-symbolic")
            self.environments_group.set_visible(True)
        else:
            self.environments_group.set_visible(False)
            self.status_row.set_icon_name("emblem-important-symbolic")
            
            missing_components = host_status.get('missing_components', {})
            missing = []
            
            if missing_components.get('distrobox'):
                missing.append("Distrobox")
            if missing_components.get('runtime'):
                runtime_name = missing_components.get('runtime_name', 'container runtime')
                missing.append(runtime_name.capitalize())
            
            self.status_row.set_title(_("Host Setup Required"))
            self.status_row.set_subtitle(_("Missing: {}").format(", ".join(missing)))
            
            # Add install button
            install_button = Gtk.Button(label=_("Install Required Packages"))
            install_button.set_valign(Gtk.Align.CENTER)
            install_button.add_css_class("suggested-action")
            install_button.connect("clicked", lambda btn: self._on_install_button_clicked(env_manager))
            self.status_row.add_suffix(install_button)

        # Clear previous environment list
        child = self.environments_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.environments_listbox.remove(child)
            child = next_child

        # Populate available environments
        if host_status['is_ready']:
            environments = env_manager.get_supported_environments()
            for env in environments:
                row = Adw.ActionRow()
                row.set_title(env['name'])
                row.set_subtitle(env['description'])
                
                if env['status'] == 'ready':
                    icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                    row.add_suffix(icon)
                    
                    remove_button = Gtk.Button(label=_("Remove"))
                    remove_button.set_valign(Gtk.Align.CENTER)
                    remove_button.add_css_class("destructive-action")
                    remove_button.connect(
                        "clicked",
                        lambda btn, env_id=env['id']: self.on_remove_clicked_callback(env_id)
                    )
                    row.add_suffix(remove_button)
                else:
                    setup_button = Gtk.Button(label=_("Setup"))
                    setup_button.set_valign(Gtk.Align.CENTER)
                    setup_button.connect(
                        "clicked", 
                        lambda btn, env_id=env['id']: self.on_setup_clicked_callback(env_id)
                    )
                    row.add_suffix(setup_button)
                
                self.environments_listbox.append(row)
                
    def _on_install_button_clicked(self, env_manager):
        """Handle install button click"""
        if self.on_install_packages_callback:
            self.on_install_packages_callback(env_manager)