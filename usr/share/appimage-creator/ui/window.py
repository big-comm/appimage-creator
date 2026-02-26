"""
Main window for AppImage Creator – Wizard UI with Adw.NavigationView.

Flow: Welcome → Application → Configuration → Build
"""

import os
import threading
from gi.repository import Gtk, Adw, GLib, Gio

from core.builder import AppImageBuilder
from core.app_info import AppInfo
from core.structure_analyzer import detect_application_structure
from core.environment_manager import EnvironmentManager, SUPPORTED_ENVIRONMENTS
from core.settings import LibraryProfileManager, SettingsManager
from templates.app_templates import get_app_type_from_file, get_available_categories
from ui.pages import WelcomePage, ApplicationPage, ConfigurationPage, BuildPage
from ui.dialogs import (
    BuildProgressDialog,
    LogProgressDialog,
    InstallPackagesDialog,
    ValidationWarningDialog,
    show_error_dialog,
    show_success_dialog,
    show_info_dialog,
    create_file_chooser,
    show_structure_viewer,
    show_desktop_file_viewer,
)
from validators.validators import ValidationError, validate_app_name, validate_version
from utils.i18n import _

# Application version – single source of truth
APP_VERSION = "1.1.2"


class AppImageCreatorWindow(Adw.ApplicationWindow):
    """Main application window using a wizard (NavigationView) layout."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Data model
        self.app_info = AppInfo()
        self.builder = AppImageBuilder()
        self.env_manager = EnvironmentManager()
        self.settings = SettingsManager()
        self.lib_profiles = LibraryProfileManager()
        self.structure_analysis = None
        self.progress_dialog = None
        self.dependency_switches: dict[str, Adw.SwitchRow] = {}
        self.build_in_progress = False
        self.app_info.selected_dependencies = []

        # Wizard pages (created once, reused across navigations)
        self.welcome_page = WelcomePage()
        self.app_page = ApplicationPage()
        self.config_page = ConfigurationPage()
        self.build_page = BuildPage()

        # Window properties
        self.set_title(_("AppImage Creator"))
        w = self.settings.get("window-width") or 820
        h = self.settings.get("window-height") or 720
        self.set_default_size(w, h)
        self.set_size_request(700, 550)
        self.set_resizable(True)

        self._setup_ui()
        self._setup_actions()
        self._setup_builder_callbacks()
        self._connect_signals()
        self._populate_dependency_switches()

        # Save window size on close
        self.connect("close-request", self._on_close_request)

        # Initial system check
        self._refresh_system_status()

    # ------------------------------------------------------------------
    #  Window lifecycle
    # ------------------------------------------------------------------

    def _on_close_request(self, _window):
        """Save window dimensions before closing."""
        self.settings.set("window-width", self.get_width())
        self.settings.set("window-height", self.get_height())
        return False

    # ------------------------------------------------------------------
    #  Settings helpers
    # ------------------------------------------------------------------

    def _get_last_chooser_path(self) -> str:
        return self.settings.get("last-chooser-directory")

    def _set_last_chooser_path(self, file: Gio.File, is_folder: bool):
        path = file.get_path() if is_folder else file.get_parent().get_path()
        if path:
            self.settings.set("last-chooser-directory", path)

    # ------------------------------------------------------------------
    #  UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        """Build the NavigationView-based wizard."""
        self.nav_view = Adw.NavigationView()
        self.set_content(self.nav_view)

        # Hamburger menu on the Welcome page header
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text(_("Menu"))

        menu = Gio.Menu()
        menu.append(_("About"), "win.about")
        menu_button.set_popover(Gtk.PopoverMenu.new_from_model(menu))

        self.welcome_page.header.pack_end(menu_button)

        # Root page
        self.nav_view.add(self.welcome_page.nav_page)

    def _setup_actions(self):
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_clicked)
        self.add_action(about_action)

    def _setup_builder_callbacks(self):
        self.builder.set_progress_callback(self._on_build_progress)
        self.builder.set_log_callback(self._on_build_log)

    # ------------------------------------------------------------------
    #  Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        """Wire up all page signals."""

        # -- Navigation --
        self.welcome_page.continue_button.connect(
            "clicked", lambda _: self.nav_view.push(self.app_page.nav_page)
        )
        self.app_page.continue_button.connect(
            "clicked", lambda _: self.nav_view.push(self.config_page.nav_page)
        )
        self.config_page.continue_button.connect("clicked", self._on_continue_to_build)

        # -- Application page --
        self.app_page.executable_button.connect("clicked", self._on_choose_executable)
        self.app_page.icon_button.connect("clicked", self._on_choose_icon)
        self.app_page.desktop_button.connect(
            "clicked", self._on_choose_desktop_app_page
        )
        self.app_page.name_row.connect("changed", self._validate_inputs)
        self.app_page.name_row.connect("changed", self._on_name_changed)

        # -- Configuration page --
        self.config_page.version_row.connect("changed", self._validate_version_input)
        self.config_page.update_url_row.connect(
            "changed", self._validate_update_url_input
        )
        self.config_page.add_dir_button.connect("clicked", self._on_add_directory)
        self.config_page.full_structure_button.connect(
            "clicked", self._on_view_full_structure
        )
        self.config_page.view_desktop_button.connect(
            "clicked", self._on_view_desktop_file
        )
        self.config_page.choose_desktop_button.connect(
            "clicked", self._on_choose_desktop_file
        )
        self.config_page.use_existing_desktop_row.connect(
            "notify::active", self._on_use_existing_desktop_changed
        )

        # -- Build page --
        self.build_page.output_button.connect("clicked", self._on_choose_output_dir)
        self.build_page.build_button.connect("clicked", self._on_build_clicked)
        self.build_page.on_setup_clicked_callback = self._on_setup_environment_clicked
        self.build_page.on_remove_clicked_callback = self._on_remove_environment_clicked
        self.build_page.icon_theme_row.connect(
            "notify::active", self._on_icon_theme_toggle
        )
        self.build_page.papirus_radio.connect("toggled", self._on_icon_theme_changed)
        self.build_page.adwaita_radio.connect("toggled", self._on_icon_theme_changed)

        # -- Welcome page environment management --
        self.welcome_page.on_setup_clicked_callback = self._on_setup_environment_clicked
        self.welcome_page.on_remove_clicked_callback = (
            self._on_remove_environment_clicked
        )

    def _on_continue_to_build(self, _button):
        """Validate configuration inputs and navigate to the Build page."""
        # Validate version before proceeding
        version = self.config_page.version_row.get_text().strip()
        if version:
            try:
                validate_version(version)
            except ValidationError:
                self.config_page.version_row.add_css_class("error")
                self.config_page.version_row.grab_focus()
                return

        # Validate update URL if provided
        update_url = self.config_page.update_url_row.get_text().strip()
        if update_url and (
            not update_url.startswith("https://") or len(update_url) <= 12
        ):
            self.config_page.update_url_row.add_css_class("error")
            self.config_page.update_url_row.grab_focus()
            return

        self.build_page.update_env_model(self.env_manager)
        self.build_page.update_environments(self.env_manager)

        # Restore previously selected build environment
        if self.app_info.build_environment:
            environments = self.env_manager.get_supported_environments()
            ready_envs = [e for e in environments if e["status"] == "ready"]
            for idx, env in enumerate(ready_envs):
                if env["id"] == self.app_info.build_environment:
                    self.build_page.environment_row.set_selected(idx + 1)
                    break

        self.nav_view.push(self.build_page.nav_page)

    # ------------------------------------------------------------------
    #  About
    # ------------------------------------------------------------------

    def _on_about_clicked(self, _action, _param):
        Adw.AboutWindow(
            transient_for=self,
            application_name=_("AppImage Creator"),
            application_icon="appimage-creator",
            version=APP_VERSION,
            developer_name="BigCommunity",
            copyright="© 2026 BigCommunity",
            license_type=Gtk.License.GPL_3_0,
            comments=_(
                "Create distributable AppImages from any Linux application.\n"
                "Supports Python, Qt, GTK, Java, and binary applications."
            ),
            website="https://github.com/big-comm/appimage-creator",
            issue_url="https://github.com/big-comm/appimage-creator/issues",
            developers=["BigCommunity"],
        ).present()

    # ------------------------------------------------------------------
    #  Icon theme
    # ------------------------------------------------------------------

    def _on_icon_theme_toggle(self, switch_row, _param):
        self.app_info.include_icon_theme = switch_row.get_active()
        self.build_page.icon_theme_expander_row.set_sensitive(switch_row.get_active())

    def _on_icon_theme_changed(self, _radio):
        if self.build_page.papirus_radio.get_active():
            self.app_info.icon_theme_choice = "papirus"
        elif self.build_page.adwaita_radio.get_active():
            self.app_info.icon_theme_choice = "adwaita"

    # ------------------------------------------------------------------
    #  Validation
    # ------------------------------------------------------------------

    def _validate_inputs(self, *_args):
        name = self.app_page.name_row.get_text().strip()
        exe = self.app_info.executable

        # Validate name with proper validator
        name_valid = False
        if name:
            try:
                validate_app_name(name)
                name_valid = True
                self.app_page.name_row.remove_css_class("error")
            except ValidationError:
                self.app_page.name_row.add_css_class("error")
        else:
            self.app_page.name_row.remove_css_class("error")

        exe_valid = exe is not None and os.path.exists(exe)
        valid = name_valid and exe_valid

        self.app_page.continue_button.set_sensitive(valid)
        self.build_page.build_button.set_sensitive(valid)

        row = self.app_page.status_row
        if valid:
            row.set_title(_("Ready to Build"))
            row.set_subtitle(_("All requirements met"))
        elif exe_valid and not name:
            row.set_title(_("Almost Ready!"))
            row.set_subtitle(_("Please enter an Application Name"))
        elif exe_valid and name and not name_valid:
            row.set_title(_("Almost Ready!"))
            row.set_subtitle(_("Application name contains invalid characters"))
        elif name_valid and not exe_valid:
            row.set_title(_("Select Executable"))
            row.set_subtitle(_("Please choose the main executable file"))
        else:
            row.set_title(_("Getting Started"))
            row.set_subtitle(_("Enter name and select executable"))

    def _validate_version_input(self, entry):
        """Validate version field inline on every keystroke."""
        text = entry.get_text().strip()
        if not text:
            entry.remove_css_class("error")
            return
        try:
            validate_version(text)
            entry.remove_css_class("error")
        except ValidationError:
            entry.add_css_class("error")

    def _validate_update_url_input(self, entry):
        """Validate update URL field inline on every keystroke."""
        text = entry.get_text().strip()
        if not text:
            entry.remove_css_class("error")
            return
        if text.startswith("https://") and len(text) > 12:
            entry.remove_css_class("error")
        else:
            entry.add_css_class("error")

    def _on_name_changed(self, entry):
        self.config_page.update_pattern_from_name(entry.get_text().strip())

    # ------------------------------------------------------------------
    #  Dependency switches
    # ------------------------------------------------------------------

    def _populate_dependency_switches(self):
        from core.build_config import SYSTEM_DEPENDENCIES

        while child := self.build_page.deps_list_box.get_first_child():
            self.build_page.deps_list_box.remove(child)
        self.dependency_switches.clear()

        for key, data in SYSTEM_DEPENDENCIES.items():
            sw = Adw.SwitchRow()
            sw.set_title(data["name"])
            sw.dependency_key = key  # type: ignore[attr-defined]
            self.build_page.deps_list_box.append(sw)
            self.dependency_switches[key] = sw

        def on_deps_toggle(switch, _):
            self.build_page.deps_expander_row.set_sensitive(switch.get_active())

        self.build_page.deps_row.connect("notify::active", on_deps_toggle)
        self.build_page.deps_expander_row.set_sensitive(
            self.build_page.deps_row.get_active()
        )

    def _update_autodetected_dependencies(self):
        from core.build_config import SYSTEM_DEPENDENCIES

        for key, switch in self.dependency_switches.items():
            if not SYSTEM_DEPENDENCIES[key].get("essential", False):
                switch.set_active(False)

        gui_deps = self.builder._detect_gui_dependencies(self.app_info)
        if self.builder._detect_gi_usage(self.app_info):
            gui_deps["gi"] = True

        for dep_key, switch in self.dependency_switches.items():
            dep_info = SYSTEM_DEPENDENCIES[dep_key]
            keyword = dep_info.get("detection_keyword")
            if keyword and gui_deps.get(keyword):
                switch.set_active(True)
                if dep_info.get("essential", False):
                    switch.set_sensitive(False)
                    switch.set_subtitle(_("Essential for this application type"))
            elif dep_info.get("essential", False):
                switch.set_sensitive(True)
                switch.set_subtitle("")

        self.app_info.selected_dependencies = [
            k for k, s in self.dependency_switches.items() if s.get_active()
        ]

    # ------------------------------------------------------------------
    #  Environment management
    # ------------------------------------------------------------------

    def _refresh_system_status(self):
        """Update welcome-page system status, environments, and connect install button."""
        self.welcome_page.update_system_status(self.env_manager)
        self.welcome_page.update_environments(self.env_manager)
        btn = self.welcome_page.install_button
        if btn and not getattr(btn, "_handler_connected", False):
            btn.connect(
                "clicked",
                lambda _: self._on_install_packages_clicked(self.env_manager),
            )
            btn._handler_connected = True  # type: ignore[attr-defined]

    def _refresh_environments(self):
        """Refresh both system status and build-page environment lists."""
        self._refresh_system_status()
        self.build_page.update_env_model(self.env_manager)
        self.build_page.update_environments(self.env_manager)

    def _on_setup_environment_clicked(self, env_id: str):
        env_spec = next((e for e in SUPPORTED_ENVIRONMENTS if e["id"] == env_id), None)
        if not env_spec:
            return

        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(450, 400)
        dialog.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        main_box.append(content)

        title_label = Gtk.Label(label=_("Setup Build Environment?"))
        title_label.add_css_class("title-2")
        title_label.set_margin_bottom(8)
        content.append(title_label)

        info_label = Gtk.Label(
            label=_(
                "This will download and setup '{}'.\n\n"
                "This process may take 5-15 minutes depending on your "
                "internet connection.\n\nThe following will be installed:"
            ).format(env_spec["name"])
        )
        info_label.set_wrap(True)
        info_label.set_xalign(0)
        info_label.set_justify(Gtk.Justification.LEFT)
        content.append(info_label)

        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        details_box.add_css_class("card")
        details_box.set_margin_start(12)
        details_box.set_margin_end(12)
        details_box.set_margin_top(8)
        details_box.set_margin_bottom(8)
        content.append(details_box)

        img_lbl = Gtk.Label(label=f"• Container image: {env_spec['image']}")
        img_lbl.set_xalign(0)
        img_lbl.set_margin_start(12)
        img_lbl.set_margin_top(8)
        details_box.append(img_lbl)

        deps_lbl = Gtk.Label(
            label=f"• Build dependencies: {len(env_spec['build_deps'])} packages"
        )
        deps_lbl.set_xalign(0)
        deps_lbl.set_margin_start(12)
        deps_lbl.set_margin_bottom(8)
        details_box.append(deps_lbl)

        q_lbl = Gtk.Label(label=_("Do you want to continue?"))
        q_lbl.set_xalign(0)
        q_lbl.set_margin_top(8)
        content.append(q_lbl)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(16)
        content.append(btn_box)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.set_size_request(140, -1)
        cancel_btn.connect("clicked", lambda _: dialog.close())
        btn_box.append(cancel_btn)

        setup_btn = Gtk.Button(label=_("Setup Environment"))
        setup_btn.set_size_request(180, -1)
        setup_btn.add_css_class("suggested-action")
        btn_box.append(setup_btn)

        def on_setup(_btn):
            dialog.close()
            progress = LogProgressDialog(self, _("Setting Up Environment"))
            progress.present()
            threading.Thread(
                target=self._run_environment_setup,
                args=(env_id, progress),
                daemon=True,
            ).start()

        setup_btn.connect("clicked", on_setup)
        dialog.present()

    def _run_environment_setup(self, env_id: str, dialog: LogProgressDialog):
        def log(msg):
            GLib.idle_add(dialog.add_log, msg)

        def is_cancelled() -> bool:
            return dialog.cancelled

        try:
            GLib.idle_add(dialog.set_status, _("Creating container..."))
            self.env_manager.create_environment(
                env_id, log_callback=log, cancel_check=is_cancelled
            )

            if dialog.cancelled:
                GLib.idle_add(dialog.add_log, _("Setup cancelled by user."))
                GLib.idle_add(dialog.finish, False)
                return

            GLib.idle_add(
                dialog.set_status,
                _("Installing dependencies (this may take a while)..."),
            )
            self.env_manager.setup_environment_dependencies(
                env_id, log_callback=log, cancel_check=is_cancelled
            )

            if dialog.cancelled:
                GLib.idle_add(dialog.add_log, _("Setup cancelled by user."))
                GLib.idle_add(dialog.finish, False)
                return

            GLib.idle_add(dialog.finish, True)
        except Exception as e:
            GLib.idle_add(dialog.add_log, _("Error: {}").format(e))
            GLib.idle_add(dialog.finish, False)
        finally:
            GLib.idle_add(self._refresh_environments)

    def _on_remove_environment_clicked(self, env_id: str):
        env_spec = next((e for e in SUPPORTED_ENVIRONMENTS if e["id"] == env_id), None)
        if not env_spec:
            return

        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading(_("Remove Environment?"))
        dialog.set_body(
            _(
                "Are you sure you want to remove '{}'?\n"
                "This will delete the container and all its data."
            ).format(env_spec["name"])
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dlg, resp):
            if resp == "remove":
                progress = LogProgressDialog(self, _("Removing Environment"))
                progress.present()
                threading.Thread(
                    target=self._run_environment_removal,
                    args=(env_id, progress),
                    daemon=True,
                ).start()

        dialog.connect("response", on_response)
        dialog.present()

    def _run_environment_removal(self, env_id: str, dialog: LogProgressDialog):
        def log(msg):
            GLib.idle_add(dialog.add_log, msg)

        try:
            GLib.idle_add(dialog.set_status, _("Removing container..."))
            self.env_manager.remove_environment(env_id, log_callback=log)
            GLib.idle_add(dialog.finish, True)
        except Exception as e:
            GLib.idle_add(dialog.add_log, _("Error: {}").format(e))
            GLib.idle_add(dialog.finish, False)
        finally:
            GLib.idle_add(self._refresh_environments)

    def _on_install_packages_clicked(self, env_manager):
        install_info = env_manager.get_install_command()
        if not install_info:
            show_error_dialog(
                self,
                _("Cannot Install"),
                _("Unable to determine package manager for your distribution."),
            )
            return

        dialog = InstallPackagesDialog(self, install_info)

        def on_close(_widget):
            if getattr(dialog, "installation_success", False):
                self.env_manager = EnvironmentManager()
                GLib.idle_add(self._refresh_system_status)

                def show_restart():
                    d = Adw.MessageDialog(transient_for=self)
                    d.set_heading(_("Installation Complete"))
                    d.set_body(
                        _(
                            "Required packages were installed successfully!\n\n"
                            "Please restart the application to use the new "
                            "features."
                        )
                    )
                    d.add_response("ok", _("OK"))
                    d.set_default_response("ok")
                    d.present()

                GLib.idle_add(show_restart)

        dialog.connect("close-request", on_close)
        dialog.present()

    # ------------------------------------------------------------------
    #  File choosers
    # ------------------------------------------------------------------

    def _on_choose_executable(self, _button):
        filters = {
            _("Executable Files"): ["*.py", "*.sh", "*.jar", "*"],
            _("All Files"): ["*"],
        }
        create_file_chooser(
            self,
            _("Choose Executable"),
            Gtk.FileChooserAction.OPEN,
            filters,
            self._on_executable_selected,
            self.settings,
        )

    def _on_executable_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.executable = path
                filename = os.path.basename(path)

                self.app_page.executable_row.set_subtitle(
                    _("Selected: {}").format(filename)
                )

                # Auto-fill name immediately (lightweight)
                if not self.app_page.name_row.get_text().strip():
                    suggested = os.path.splitext(filename)[0]
                    suggested = suggested.replace("-gui", "").replace("-cli", "")
                    suggested = suggested.replace("_", " ").title()
                    if suggested and len(suggested) > 2:
                        self.app_page.name_row.set_text(suggested)

                # Show analysis in progress
                self.app_page.status_row.set_title(_("Analyzing..."))
                self.app_page.status_row.set_subtitle(
                    _("Detecting application structure")
                )
                self.app_page.continue_button.set_sensitive(False)

                # Run heavy analysis in background thread
                def _analyze():
                    structure = detect_application_structure(path)
                    app_type = get_app_type_from_file(path, structure)
                    GLib.idle_add(self._on_analysis_complete, path, structure, app_type)

                threading.Thread(target=_analyze, daemon=True).start()

        dialog.destroy()

    def _on_analysis_complete(self, path, structure, app_type):
        """Apply analysis results on the main thread."""
        self.structure_analysis = structure
        self.app_info.structure_analysis = structure
        self.app_info.app_type = app_type

        type_map = {
            "binary": 0,
            "python": 1,
            "python_wrapper": 2,
            "shell": 3,
            "java": 4,
            "qt": 5,
            "gtk": 6,
            "electron": 7,
        }
        if app_type in type_map:
            self.app_page.app_type_row.set_selected(type_map[app_type])
            saved_libs = self.lib_profiles.load(app_type)
            if saved_libs:
                self.build_page.set_extra_libs(saved_libs)

        # Auto-set detected .desktop file on Application page
        desktop_files = structure.get("detected_files", {}).get("desktop_files", [])
        if desktop_files:
            self.app_info.detected_desktop_file = desktop_files[0]
            self.app_info.custom_desktop_file = desktop_files[0]
            self.app_info.use_existing_desktop = True
            self.app_page.desktop_row.set_subtitle(
                _("Detected: {}").format(os.path.basename(desktop_files[0]))
            )

        # Auto-set detected icon
        icons = structure.get("detected_files", {}).get("icons", [])
        if icons and not self.app_info.icon:
            self.app_info.icon = icons[0]
            self.app_page.icon_row.set_subtitle(
                _("Detected: {}").format(os.path.basename(icons[0]))
            )

        # Update config-page sections
        self._update_detected_files()
        self._update_additional_directories_from_analysis()
        self._update_desktop_file_options()
        self._update_structure_preview()
        self._update_autodetected_dependencies()

        self._validate_inputs()
        return False  # Remove from idle

    def _on_choose_icon(self, _button):
        filters = {_("Image Files"): ["*.png", "*.svg", "*.jpg", "*.ico"]}
        create_file_chooser(
            self,
            _("Choose Icon"),
            Gtk.FileChooserAction.OPEN,
            filters,
            self._on_icon_selected,
            self.settings,
        )

    def _on_icon_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.icon = path
                self.app_page.icon_row.set_subtitle(
                    _("Selected: {}").format(os.path.basename(path))
                )
        dialog.destroy()

    def _on_choose_desktop_app_page(self, _button):
        filters = {_("Desktop Files"): ["*.desktop"]}
        create_file_chooser(
            self,
            _("Choose Desktop File"),
            Gtk.FileChooserAction.OPEN,
            filters,
            self._on_desktop_app_page_selected,
            self.settings,
        )

    def _on_desktop_app_page_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.custom_desktop_file = path
                self.app_info.use_existing_desktop = True
                self.app_page.desktop_row.set_subtitle(
                    _("Selected: {}").format(os.path.basename(path))
                )
                # Also update config page
                self.config_page.desktop_file_group.set_visible(True)
                self.config_page.manual_desktop_row.set_subtitle(
                    _("Selected: {}").format(os.path.basename(path))
                )
                self.config_page.use_existing_desktop_row.set_active(True)
        dialog.destroy()

    def _on_add_directory(self, _button):
        create_file_chooser(
            self,
            _("Add Directory"),
            Gtk.FileChooserAction.SELECT_FOLDER,
            None,
            self._on_directory_selected,
            self.settings,
        )

    def _on_directory_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                self.config_page.directory_list.add_directory(file.get_path())
                self._update_structure_preview()
        dialog.destroy()

    def _on_choose_output_dir(self, _button):
        create_file_chooser(
            self,
            _("Choose Output Directory"),
            Gtk.FileChooserAction.SELECT_FOLDER,
            None,
            self._on_output_dir_selected,
            self.settings,
        )

    def _on_output_dir_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.output_dir = path
                self.build_page.output_row.set_subtitle(path)
        dialog.destroy()

    # ------------------------------------------------------------------
    #  Detected-files / desktop / preview helpers
    # ------------------------------------------------------------------

    def _update_detected_files(self):
        if not self.structure_analysis:
            self.config_page.detected_group.set_visible(False)
            return
        detected = self.structure_analysis.get("detected_files", {})
        filtered = {k: v for k, v in detected.items() if k != "desktop_files"}
        if any(filtered.values()):
            self.config_page.detected_group.set_visible(True)
            self.config_page.detected_files.update(detected)
        else:
            self.config_page.detected_group.set_visible(False)

    def _update_additional_directories_from_analysis(self):
        if not self.structure_analysis:
            return
        for d in self.structure_analysis.get("suggested_additional_dirs", []):
            if os.path.exists(d):
                self.config_page.directory_list.add_directory(d)

    def _update_desktop_file_options(self):
        if not self.structure_analysis:
            self.config_page.desktop_file_group.set_visible(False)
            return
        desktop = self.structure_analysis.get("detected_files", {}).get(
            "desktop_files", []
        )
        if desktop:
            self.config_page.desktop_file_group.set_visible(True)
            self.app_info.detected_desktop_file = desktop[0]
            self.config_page.found_desktop_row.set_subtitle(
                _("Found: {}").format(os.path.basename(desktop[0]))
            )
            self.config_page.use_existing_desktop_row.set_active(True)
            self.app_info.use_existing_desktop = True
        else:
            self.config_page.desktop_file_group.set_visible(False)
            self.app_info.use_existing_desktop = False

    def _on_use_existing_desktop_changed(self, switch_row, _param):
        self.app_info.use_existing_desktop = switch_row.get_active()

    def _on_view_desktop_file(self, _button):
        df = self.app_info.detected_desktop_file
        if df and os.path.exists(df):
            show_desktop_file_viewer(self, df)

    def _on_choose_desktop_file(self, _button):
        filters = {_("Desktop Files"): ["*.desktop"]}
        create_file_chooser(
            self,
            _("Choose Desktop File"),
            Gtk.FileChooserAction.OPEN,
            filters,
            self._on_desktop_file_selected,
            self.settings,
        )

    def _on_desktop_file_selected(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            file = dialog.get_file()
            if file:
                path = file.get_path()
                self.app_info.custom_desktop_file = path
                self.config_page.manual_desktop_row.set_subtitle(
                    _("Selected: {}").format(os.path.basename(path))
                )
                self.config_page.use_existing_desktop_row.set_active(False)
        dialog.destroy()

    def _update_structure_preview(self):
        self.config_page.preview_group.set_visible(bool(self.app_info.executable))

    def _get_current_app_type(self) -> str:
        types = [
            "binary",
            "python",
            "python_wrapper",
            "shell",
            "java",
            "qt",
            "gtk",
            "electron",
        ]
        sel = self.app_page.app_type_row.get_selected()
        return types[sel] if sel < len(types) else "unknown"

    def _on_view_full_structure(self, _button):
        if not self.app_info.executable:
            return
        from core.structure_formatter import generate_detailed_structure

        content = generate_detailed_structure(
            app_name_raw=self.app_page.name_row.get_text(),
            executable=self.app_info.executable,
            structure_analysis=self.structure_analysis,
            directories=self.config_page.directory_list.get_directories(),
            app_type=self._get_current_app_type(),
        )
        show_structure_viewer(
            self,
            _("AppImage Structure - Full View"),
            content,
        )

    # ------------------------------------------------------------------
    #  Collect app info from wizard pages
    # ------------------------------------------------------------------

    def _collect_app_info(self):
        self.app_info.name = self.app_page.name_row.get_text().strip()
        self.app_info.version = (
            self.config_page.version_row.get_text().strip() or "1.0.0"
        )
        self.app_info.description = self.config_page.description_row.get_text().strip()

        if self.app_info.executable:
            self.app_info.executable_name = os.path.basename(self.app_info.executable)

        self.app_info.authors = ["Unknown"]
        self.app_info.websites = []

        categories = get_available_categories()
        sel = self.config_page.category_row.get_selected()
        self.app_info.categories = [categories[sel]]

        types = [
            "binary",
            "python",
            "python_wrapper",
            "shell",
            "java",
            "qt",
            "gtk",
            "electron",
        ]
        sel = self.app_page.app_type_row.get_selected()
        self.app_info.app_type = types[sel]

        self.app_info.terminal = self.config_page.terminal_row.get_active()
        self.app_info.additional_directories = (
            self.config_page.directory_list.get_directories()
        )
        self.app_info.structure_analysis = self.structure_analysis

        # Auto-update
        self.app_info.update_url = self.config_page.update_url_row.get_text().strip()
        self.app_info.update_pattern = (
            self.config_page.update_pattern_row.get_text().strip()
        )

        # Dependencies (read directly – widgets are always alive)
        self.app_info.selected_dependencies = [
            k for k, s in self.dependency_switches.items() if s.get_active()
        ]

        # Build settings
        self.app_info.include_dependencies = self.build_page.deps_row.get_active()
        self.app_info.strip_binaries = self.build_page.strip_row.get_active()
        self.app_info.extra_libraries = self.build_page.get_extra_libs()

        # Icon theme
        self.app_info.include_icon_theme = self.build_page.icon_theme_row.get_active()
        if self.build_page.papirus_radio.get_active():
            self.app_info.icon_theme_choice = "papirus"
        elif self.build_page.adwaita_radio.get_active():
            self.app_info.icon_theme_choice = "adwaita"

        # Build environment
        sel_idx = self.build_page.environment_row.get_selected()
        if sel_idx == 0:
            self.app_info.build_environment = None
        else:
            envs = self.env_manager.get_supported_environments()
            ready = [e for e in envs if e["status"] == "ready"]
            if sel_idx - 1 < len(ready):
                self.app_info.build_environment = ready[sel_idx - 1]["id"]

    # ------------------------------------------------------------------
    #  Build
    # ------------------------------------------------------------------

    def _on_build_clicked(self, _button):
        try:
            self.build_in_progress = True
            self._collect_app_info()
            self.builder.set_app_info(self.app_info)

            warning = self.builder.get_compatibility_warning()
            if warning:
                self.build_in_progress = False
                self._show_local_build_warning(warning)
                return

            self._start_actual_build()
        except ValidationError as e:
            self.build_in_progress = False
            show_error_dialog(self, _("Validation Error"), str(e))
        except Exception as e:
            self.build_in_progress = False
            show_error_dialog(
                self, _("Error"), _("Failed to start build: {}").format(e)
            )

    def _show_local_build_warning(self, warning):
        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(500, 450)
        dialog.set_resizable(False)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_content(main_box)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)
        title_lbl = Gtk.Label(label=warning["title"])
        title_lbl.add_css_class("title-2")
        header.set_title_widget(title_lbl)
        main_box.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        main_box.append(content)

        parts = warning["message"].split("\n\n")

        intro = Gtk.Label(label=parts[0])
        intro.set_wrap(True)
        intro.set_xalign(0)
        intro.set_justify(Gtk.Justification.LEFT)
        content.append(intro)

        if len(parts) > 1:
            pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pbox.add_css_class("card")
            pbox.set_margin_start(12)
            pbox.set_margin_end(12)
            pbox.set_margin_top(8)
            pbox.set_margin_bottom(8)
            content.append(pbox)

            ptitle = Gtk.Label(
                label=_(
                    "AppImages built on your system may NOT work on other "
                    "distributions due to:"
                )
            )
            ptitle.set_wrap(True)
            ptitle.set_xalign(0)
            ptitle.set_margin_start(12)
            ptitle.set_margin_top(8)
            pbox.append(ptitle)

            for line in parts[1].split("\n"):
                if line.strip().startswith("•"):
                    lbl = Gtk.Label(label=line.strip())
                    lbl.set_xalign(0)
                    lbl.set_margin_start(12)
                    pbox.append(lbl)
            pbox.set_margin_bottom(8)

        if len(parts) > 2:
            rec = Gtk.Label()
            split = parts[2].split(":", 1)
            rec.set_markup(f"<b>{split[0]}:</b>\n{split[1]}")
            rec.set_wrap(True)
            rec.set_xalign(0)
            rec.set_justify(Gtk.Justification.LEFT)
            content.append(rec)

        if len(parts) > 3:
            q = Gtk.Label(label=parts[3])
            q.set_xalign(0)
            q.set_margin_top(8)
            content.append(q)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(16)
        content.append(btn_box)

        cancel = Gtk.Button(label=_("Cancel"))
        cancel.set_size_request(140, -1)
        cancel.connect("clicked", lambda _: dialog.close())
        btn_box.append(cancel)

        cont = Gtk.Button(label=_("Continue Anyway"))
        cont.set_size_request(160, -1)
        cont.add_css_class("destructive-action")

        def on_continue(_b):
            dialog.close()
            self._start_actual_build()

        cont.connect("clicked", on_continue)
        btn_box.append(cont)

        dialog.present()

    def _start_actual_build(self):
        try:
            self.build_in_progress = True
            self.progress_dialog = BuildProgressDialog(self)
            self.progress_dialog.cancel_button.connect("clicked", self._on_cancel_build)
            self.progress_dialog.present()
            self.builder.build_async(self._on_build_complete)
        except Exception as e:
            self.build_in_progress = False
            show_error_dialog(
                self, _("Error"), _("Failed to start build: {}").format(e)
            )

    def _on_build_progress(self, percentage, message):
        GLib.idle_add(self._update_progress_ui, percentage, message)

    def _update_progress_ui(self, percentage, message):
        if not self.build_in_progress:
            return False
        if self.progress_dialog:
            self.progress_dialog.update_progress(percentage, message)
        return False

    def _on_build_log(self, message):
        print(f"Build: {message}")

    def _on_cancel_build(self, _button):
        self.build_in_progress = False
        if self.builder:
            self.builder.cancel_build()
        if self.progress_dialog:
            self.progress_dialog.destroy()
            self.progress_dialog = None

    def _on_build_complete(self, result, error):
        GLib.idle_add(self._handle_build_result, result, error)

    def _handle_build_result(self, result, error):
        self.build_in_progress = False
        GLib.idle_add(
            self._finish_build_cleanup,
            result,
            error,
            priority=GLib.PRIORITY_LOW,
        )
        return False

    def _finish_build_cleanup(self, result, error):
        if self.progress_dialog:
            self.progress_dialog.set_visible(False)
            self.progress_dialog.set_deletable(True)
            self.progress_dialog.destroy()
            self.progress_dialog = None

        validation = getattr(self.builder, "validation_result", None)
        has_warnings = validation and not validation.get("ok", True)

        def _back_to_welcome(*_args):
            self.nav_view.pop_to_tag("welcome")

        if error:
            show_error_dialog(
                self,
                _("Build Failed"),
                self._friendly_error_message(str(error)),
            )
            _back_to_welcome()
        elif result:
            extra_libs = self.app_info.extra_libraries
            if extra_libs:
                self.lib_profiles.save(self.app_info.app_type, extra_libs)
            if has_warnings:
                dlg = ValidationWarningDialog(self, validation, result)
                dlg.connect("close-request", _back_to_welcome)
                dlg.present()
            else:
                show_success_dialog(
                    self,
                    _("Build Complete"),
                    _("AppImage created successfully:\\n{}").format(result),
                    appimage_path=result,
                    on_response=_back_to_welcome,
                )
        else:
            show_info_dialog(self, _("Build Cancelled"), _("Build was cancelled"))
            _back_to_welcome()
        return False

    @staticmethod
    def _friendly_error_message(error_text: str) -> str:
        """Map common build errors to user-friendly messages with suggestions."""
        lower = error_text.lower()

        patterns = [
            (
                "appimagetool not available",
                _(
                    "The appimagetool utility could not be found or downloaded.\n\n"
                    "Suggestion: Check your internet connection and try again."
                ),
            ),
            (
                "failed to setup appimagetool",
                _(
                    "Could not set up appimagetool.\n\n"
                    "Suggestion: Check your internet connection and available "
                    "disk space."
                ),
            ),
            (
                "build timed out",
                _(
                    "The build process took too long and was stopped.\n\n"
                    "Suggestion: Try building again. If the problem persists, "
                    "check if the build environment is responsive."
                ),
            ),
            (
                "build cancelled",
                _("The build was cancelled by the user."),
            ),
            (
                "distrobox-create command not found",
                _(
                    "Distrobox is not installed on your system.\n\n"
                    "Suggestion: Install distrobox from your package manager."
                ),
            ),
            (
                "host is not set up for distrobox",
                _(
                    "Your system is not configured for Distrobox containers.\n\n"
                    "Suggestion: Make sure Docker or Podman is installed and "
                    "running."
                ),
            ),
            (
                "failed to create build directory",
                _(
                    "Could not create the build directory.\n\n"
                    "Suggestion: Check disk space and write permissions."
                ),
            ),
            (
                "failed to copy application files",
                _(
                    "Could not copy application files to the build directory.\n\n"
                    "Suggestion: Ensure the source files still exist and you "
                    "have read permissions."
                ),
            ),
            (
                "python setup timed out",
                _(
                    "Python environment setup took too long.\n\n"
                    "Suggestion: Check your internet connection (pip may be "
                    "downloading packages)."
                ),
            ),
            (
                "python stdlib required",
                _(
                    "Python standard library could not be found in the build "
                    "container.\n\nSuggestion: Try removing and recreating the "
                    "build environment."
                ),
            ),
            (
                "no space left",
                _(
                    "Not enough disk space to complete the build.\n\n"
                    "Suggestion: Free up disk space and try again."
                ),
            ),
            (
                "permission denied",
                _(
                    "A file permission error occurred during the build.\n\n"
                    "Suggestion: Check that you have the necessary permissions "
                    "for all files."
                ),
            ),
        ]

        for pattern, message in patterns:
            if pattern in lower:
                return message

        return error_text
