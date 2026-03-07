"""
Wizard pages for AppImage Creator.

Each page is an Adw.NavigationPage shown inside the main
Adw.NavigationView.  The flow is:

    Welcome → Application → Configuration → Build
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw
from pathlib import Path
from typing import TYPE_CHECKING
from templates.app_templates import get_available_categories
from ui.widgets import DirectoryListWidget, DetectedFilesWidget
from utils.i18n import _

if TYPE_CHECKING:
    from core.environment_manager import EnvironmentManager


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _scrollable_content(spacing: int = 24) -> tuple[Gtk.ScrolledWindow, Gtk.Box]:
    """Return (scrolled_window, content_box) ready to be set as ToolbarView content."""
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_vexpand(True)

    clamp = Adw.Clamp()
    clamp.set_maximum_size(700)
    clamp.set_tightening_threshold(600)
    scrolled.set_child(clamp)

    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    content_box.set_margin_start(24)
    content_box.set_margin_end(24)
    content_box.set_margin_top(24)
    content_box.set_margin_bottom(24)
    clamp.set_child(content_box)

    return scrolled, content_box


def _make_nav_page(
    title: str, tag: str
) -> tuple[Adw.NavigationPage, Adw.ToolbarView, Adw.HeaderBar]:
    """Create a NavigationPage with a ToolbarView and HeaderBar."""
    nav_page = Adw.NavigationPage(title=title, tag=tag)
    toolbar_view = Adw.ToolbarView()
    header = Adw.HeaderBar()
    toolbar_view.add_top_bar(header)
    nav_page.set_child(toolbar_view)
    return nav_page, toolbar_view, header


# ---------------------------------------------------------------------------
#  Page 1 – Welcome
# ---------------------------------------------------------------------------


class WelcomePage:
    """Welcome page with app branding and system requirements check."""

    def __init__(self):
        self.nav_page, toolbar_view, self.header = _make_nav_page(
            _("Welcome"), "welcome"
        )

        scrolled, content_box = _scrollable_content()
        toolbar_view.set_content(scrolled)

        # ---- Branding area ----
        brand_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        brand_box.set_halign(Gtk.Align.CENTER)
        brand_box.set_margin_top(16)
        brand_box.set_margin_bottom(8)

        icon = Gtk.Image.new_from_icon_name("appimage-creator")
        icon.set_pixel_size(96)
        brand_box.append(icon)

        title_label = Gtk.Label(label="AppImage Creator")
        title_label.add_css_class("title-1")
        brand_box.append(title_label)

        desc_label = Gtk.Label(
            label=_("Create distributable AppImages from any Linux application")
        )
        desc_label.add_css_class("dim-label")
        desc_label.set_wrap(True)
        desc_label.set_justify(Gtk.Justification.CENTER)
        brand_box.append(desc_label)

        content_box.append(brand_box)

        # ---- System Requirements ----
        self.req_group = Adw.PreferencesGroup()
        self.req_group.set_title(_("System Requirements"))

        self.distrobox_row = Adw.ActionRow()
        self.distrobox_row.set_title("Distrobox")
        self.distrobox_row.set_subtitle(_("Checking…"))
        self.req_group.add(self.distrobox_row)

        self.runtime_row = Adw.ActionRow()
        self.runtime_row.set_title(_("Container Runtime"))
        self.runtime_row.set_subtitle(_("Checking…"))
        self.req_group.add(self.runtime_row)

        content_box.append(self.req_group)

        # ---- Build Environments (collapsible) ----
        self.env_group = Adw.PreferencesGroup()
        self.env_group.set_title(_("Build Environments"))
        self.env_group.set_description(
            _("Manage containers for cross-distribution builds")
        )

        self.env_expander = Adw.ExpanderRow()
        self.env_expander.set_title(_("Available Containers"))
        self.env_expander.set_subtitle(_("Click to manage build containers"))
        self.env_expander.set_show_enable_switch(False)
        self.env_group.add(self.env_expander)

        content_box.append(self.env_group)

        # Callbacks set by window.py
        self.on_setup_clicked_callback = None
        self.on_remove_clicked_callback = None

        # Track env rows for proper cleanup
        self._env_rows: list[Adw.ActionRow] = []

        # ---- Continue ----
        continue_group = Adw.PreferencesGroup()
        continue_group.set_margin_top(8)

        continue_row = Adw.ActionRow()
        continue_row.set_title(_("Continue"))
        continue_row.set_subtitle(_("Configure your AppImage"))

        self.continue_button = Gtk.Button(label=_("Continue"))
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_valign(Gtk.Align.CENTER)
        continue_row.add_suffix(self.continue_button)
        continue_row.set_activatable_widget(self.continue_button)
        continue_group.add(continue_row)

        content_box.append(continue_group)

        # Install button placeholder (created on demand)
        self._install_row: Adw.ActionRow | None = None
        self.install_button: Gtk.Button | None = None

    # -- public API --

    def update_system_status(self, env_manager: EnvironmentManager) -> None:
        """Refresh requirement rows from an EnvironmentManager instance."""
        host = env_manager.get_host_status()
        missing = host.get("missing_components", {})

        # Distrobox
        if missing.get("distrobox"):
            self.distrobox_row.set_subtitle(_("Not installed"))
            self._set_row_icon(self.distrobox_row, False)
        else:
            self.distrobox_row.set_subtitle(_("Ready"))
            self._set_row_icon(self.distrobox_row, True)

        # Container runtime
        if missing.get("runtime"):
            name = missing.get("runtime_name", "podman / docker")
            self.runtime_row.set_subtitle(_("Not installed ({})").format(name))
            self._set_row_icon(self.runtime_row, False)
        else:
            self.runtime_row.set_subtitle(_("Ready"))
            self._set_row_icon(self.runtime_row, True)

        # Show / hide install button
        if not host["is_ready"]:
            if self._install_row is None:
                self.install_button = Gtk.Button(label=_("Install Required Packages"))
                self.install_button.add_css_class("suggested-action")
                self.install_button.set_valign(Gtk.Align.CENTER)
                self._install_row = Adw.ActionRow()
                self._install_row.set_title(_("Missing Components"))
                self._install_row.set_subtitle(
                    _("Install required packages to enable container builds")
                )
                self._install_row.add_suffix(self.install_button)
                self.req_group.add(self._install_row)
        else:
            if self._install_row is not None:
                self.req_group.remove(self._install_row)
                self._install_row = None
                self.install_button = None

    @staticmethod
    def _set_row_icon(row: Adw.ActionRow, ok: bool):
        """Set a status icon as prefix on the row (replaces any existing)."""
        old_icon = getattr(row, "_status_icon", None)
        if old_icon is not None:
            row.remove(old_icon)

        icon_name = "emblem-ok-symbolic" if ok else "dialog-warning-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        row.add_prefix(icon)
        row._status_icon = icon  # type: ignore[attr-defined]

    def update_environments(self, env_manager: EnvironmentManager) -> None:
        """Populate the Build Environments expander with available containers."""
        # Clear previously tracked rows
        for old_row in self._env_rows:
            self.env_expander.remove(old_row)
        self._env_rows = []

        ready_count = 0
        for env in env_manager.get_supported_environments():
            row = Adw.ActionRow()
            row.set_title(env["name"])
            desc = env["description"]

            # Show "★ Recommended" badge on recommended environments
            is_recommended = _("Recommended") in desc
            if is_recommended:
                # Strip "Recommended - " prefix from subtitle
                desc = desc.replace(_("Recommended") + " - ", "")
                badge = Gtk.Label(label=_("★ Recommended"))
                badge.add_css_class("accent")
                badge.set_valign(Gtk.Align.CENTER)
                row.add_suffix(badge)

            row.set_subtitle(desc)

            if env["status"] == "ready":
                ready_count += 1
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                row.add_prefix(icon)

                remove_btn = Gtk.Button(label=_("Remove"))
                remove_btn.set_valign(Gtk.Align.CENTER)
                remove_btn.add_css_class("destructive-action")
                remove_btn.connect(
                    "clicked",
                    lambda _b, eid=env["id"]: (
                        self.on_remove_clicked_callback(eid)
                        if self.on_remove_clicked_callback
                        else None
                    ),
                )
                row.add_suffix(remove_btn)
            else:
                icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
                row.add_prefix(icon)

                setup_btn = Gtk.Button(label=_("Setup"))
                setup_btn.set_valign(Gtk.Align.CENTER)
                setup_btn.add_css_class("suggested-action")
                setup_btn.connect(
                    "clicked",
                    lambda _b, eid=env["id"]: (
                        self.on_setup_clicked_callback(eid)
                        if self.on_setup_clicked_callback
                        else None
                    ),
                )
                row.add_suffix(setup_btn)

            self.env_expander.add_row(row)
            self._env_rows.append(row)

        # Update subtitle with count
        total = len(env_manager.get_supported_environments())
        self.env_expander.set_subtitle(
            _("{} of {} containers ready").format(ready_count, total)
        )


# ---------------------------------------------------------------------------
#  Page 2 – Application
# ---------------------------------------------------------------------------


class ApplicationPage:
    """Essential application info: executable, name, icon, type."""

    def __init__(self):
        self.nav_page, toolbar_view, self.header = _make_nav_page(
            _("Application"), "application"
        )

        scrolled, content_box = _scrollable_content()
        toolbar_view.set_content(scrolled)

        # ---- Application Setup ----
        setup_group = Adw.PreferencesGroup()
        setup_group.set_title(_("Application Setup"))
        setup_group.set_description(
            _("Define the essential information for your AppImage")
        )

        # Executable
        self.executable_row = Adw.ActionRow()
        self.executable_row.set_title(_("Main Executable"))
        self.executable_row.set_subtitle(_("Select the main application file"))
        self.executable_row.set_icon_name("application-x-executable-symbolic")

        self.executable_button = Gtk.Button(label=_("Choose File"))
        self.executable_button.set_valign(Gtk.Align.CENTER)
        self.executable_row.add_suffix(self.executable_button)
        setup_group.add(self.executable_row)

        # App name
        self.name_row = Adw.EntryRow()
        self.name_row.set_title(_("Application Name"))
        setup_group.add(self.name_row)

        # Icon
        self.icon_row = Adw.ActionRow()
        self.icon_row.set_title(_("Application Icon"))
        self.icon_row.set_subtitle(
            _("Recommended – needed for menu and taskbar integration")
        )
        self.icon_row.set_icon_name("image-x-generic-symbolic")

        self.icon_button = Gtk.Button(label=_("Choose Icon"))
        self.icon_button.set_valign(Gtk.Align.CENTER)
        self.icon_row.add_suffix(self.icon_button)
        setup_group.add(self.icon_row)

        # Desktop file
        self.desktop_row = Adw.ActionRow()
        self.desktop_row.set_title(_("Desktop File"))
        self.desktop_row.set_subtitle(
            _("Optional – a default will be generated if not provided")
        )
        self.desktop_row.set_icon_name("application-x-desktop-symbolic")

        self.desktop_button = Gtk.Button(label=_("Choose File"))
        self.desktop_button.set_valign(Gtk.Align.CENTER)
        self.desktop_row.add_suffix(self.desktop_button)
        setup_group.add(self.desktop_row)

        # App type (auto-detected)
        self.app_type_row = Adw.ComboRow()
        self.app_type_row.set_title(_("Application Type"))
        self.app_type_row.set_subtitle(_("Auto-detected from executable"))

        type_model = Gtk.StringList()
        for label in [
            _("Binary"),
            _("Python"),
            _("Python Wrapper"),
            _("Shell Script"),
            _("Java"),
            _("Qt"),
            _("GTK"),
            _("Electron"),
        ]:
            type_model.append(label)
        self.app_type_row.set_model(type_model)
        self.app_type_row.set_selected(0)
        setup_group.add(self.app_type_row)

        content_box.append(setup_group)

        # ---- Status ----
        self.status_group = Adw.PreferencesGroup()

        self.status_row = Adw.ActionRow()
        self.status_row.set_title(_("Getting Started"))
        self.status_row.set_subtitle(_("Enter name and select executable"))

        self._status_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        self.status_row.add_prefix(self._status_icon)
        self.status_group.add(self.status_row)
        self.status_group.set_visible(False)

        content_box.append(self.status_group)

        # ---- Continue ----
        continue_group = Adw.PreferencesGroup()
        continue_group.set_margin_top(8)

        continue_row = Adw.ActionRow()
        continue_row.set_title(_("Continue"))
        continue_row.set_subtitle(_("Configure files and details"))

        self.continue_button = Gtk.Button(label=_("Continue"))
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_valign(Gtk.Align.CENTER)
        self.continue_button.set_sensitive(False)
        continue_row.add_suffix(self.continue_button)
        continue_row.set_activatable_widget(self.continue_button)
        continue_group.add(continue_row)

        content_box.append(continue_group)


# ---------------------------------------------------------------------------
#  Page 3 – Configuration
# ---------------------------------------------------------------------------


class ConfigurationPage:
    """Optional configuration: details, files, directories, auto-update."""

    def __init__(self):
        self.nav_page, toolbar_view, self.header = _make_nav_page(
            _("Configuration"), "configuration"
        )

        scrolled, content_box = _scrollable_content()
        toolbar_view.set_content(scrolled)

        # ---- App Details ----
        details_group = Adw.PreferencesGroup()
        details_group.set_title(_("Application Details"))

        self.version_row = Adw.EntryRow()
        self.version_row.set_title(_("Version"))
        self.version_row.set_text("1.0.0")
        details_group.add(self.version_row)

        self.description_row = Adw.EntryRow()
        self.description_row.set_title(_("Description"))
        details_group.add(self.description_row)

        self.category_row = Adw.ComboRow()
        self.category_row.set_title(_("Primary Category"))
        cat_model = Gtk.StringList()
        for cat in get_available_categories():
            cat_model.append(cat)
        self.category_row.set_model(cat_model)
        self.category_row.set_selected(12)  # Utility
        details_group.add(self.category_row)

        self.terminal_row = Adw.SwitchRow()
        self.terminal_row.set_title(_("Requires Terminal"))
        self.terminal_row.set_subtitle(
            _("Check if your application needs to run in a terminal")
        )
        details_group.add(self.terminal_row)

        content_box.append(details_group)

        # ---- Files & Resources ----
        files_group = Adw.PreferencesGroup()
        files_group.set_title(_("Additional Directories"))
        files_group.set_description(
            _("Include extra directories like locale files, plugins, or data")
        )

        add_dir_row = Adw.ActionRow()
        add_dir_row.set_title(_("Add Directory"))
        add_dir_row.set_subtitle(_("Include additional files and directories"))

        self.add_dir_button = Gtk.Button(label=_("Add Directory"))
        self.add_dir_button.set_valign(Gtk.Align.CENTER)
        add_dir_row.add_suffix(self.add_dir_button)
        files_group.add(add_dir_row)

        self.additional_dirs_listbox = Gtk.ListBox()
        self.additional_dirs_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.additional_dirs_listbox.add_css_class("boxed-list")
        files_group.add(self.additional_dirs_listbox)

        self.directory_list = DirectoryListWidget(self.additional_dirs_listbox)

        content_box.append(files_group)

        # ---- Auto-detected Files ----
        self.detected_group = Adw.PreferencesGroup()
        self.detected_group.set_title(_("Auto-detected Files"))
        self.detected_group.set_description(
            _("Files automatically found for your application")
        )
        self.detected_group.set_visible(False)

        self.detected_listbox = Gtk.ListBox()
        self.detected_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.detected_listbox.add_css_class("boxed-list")
        self.detected_group.add(self.detected_listbox)

        self.detected_files = DetectedFilesWidget(self.detected_listbox)

        content_box.append(self.detected_group)

        # ---- Desktop File ----
        self.desktop_file_group = Adw.PreferencesGroup()
        self.desktop_file_group.set_title(_("Desktop File"))
        self.desktop_file_group.set_visible(False)

        self.use_existing_desktop_row = Adw.SwitchRow()
        self.use_existing_desktop_row.set_title(_("Use Existing Desktop File"))
        self.use_existing_desktop_row.set_subtitle(
            _("Found desktop file in application")
        )
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

        content_box.append(self.desktop_file_group)

        # ---- Structure Preview ----
        self.preview_group = Adw.PreferencesGroup()
        self.preview_group.set_title(_("Structure Preview"))
        self.preview_group.set_description(
            _("View the complete structure that will be included in the AppImage")
        )
        self.preview_group.set_visible(False)

        preview_row = Adw.ActionRow()
        preview_row.set_title(_("AppImage Structure"))
        preview_row.set_subtitle(
            _("View all files and directories that will be packaged")
        )

        self.full_structure_button = Gtk.Button(label=_("View Full Structure"))
        self.full_structure_button.set_valign(Gtk.Align.CENTER)
        self.full_structure_button.add_css_class("suggested-action")
        preview_row.add_suffix(self.full_structure_button)
        self.preview_group.add(preview_row)

        self.preview_text = None  # kept for compatibility

        content_box.append(self.preview_group)

        # ---- Auto-Update (Optional) ----
        update_group = Adw.PreferencesGroup()
        update_group.set_title(_("Auto-Update (Optional)"))
        update_group.set_description(
            _("Enable automatic update checking for this AppImage")
        )

        # Help expander
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
            _(
                "<b>GitHub Releases (recommended):</b>\n"
                "Click the button next to Update URL to fill with template,"
                " then edit OWNER/REPO\n\n"
                "<b>Example:</b>\n"
                "https://api.github.com/repos/biglinux/"
                "big-video-converter/releases/latest\n\n"
                "<b>Filename Pattern:</b>\n"
                "Used to identify which file to download from the release.\n"
                "The asterisk (*) matches any text.\n\n"
                "<b>Pattern Examples:</b>\n"
                "• myapp-*-x86_64.AppImage  → matches: "
                "myapp-v1.2.3-x86_64.AppImage\n"
                "• *-gui-*.AppImage  → matches: converter-gui-1.0.AppImage\n"
                "• calculator-*.AppImage  → matches: "
                "calculator-2.5-linux.AppImage"
            )
        )
        help_text.set_wrap(True)
        help_text.set_xalign(0)
        help_box.append(help_text)

        help_expander.add_row(help_box)
        update_group.add(help_expander)

        # Update URL
        self.update_url_row = Adw.EntryRow()
        self.update_url_row.set_title(_("Update URL"))
        self.update_url_row.set_text("")

        template_btn = Gtk.Button()
        template_btn.set_icon_name("edit-paste-symbolic")
        template_btn.set_valign(Gtk.Align.CENTER)
        template_btn.set_tooltip_text(_("Paste GitHub API template"))
        template_btn.add_css_class("flat")
        template_btn.connect("clicked", self._on_use_github_template)
        self.update_url_row.add_suffix(template_btn)
        update_group.add(self.update_url_row)

        # Filename pattern
        self.update_pattern_row = Adw.EntryRow()
        self.update_pattern_row.set_title(_("Filename Pattern"))
        self.update_pattern_row.set_text("*-x86_64.AppImage")
        update_group.add(self.update_pattern_row)

        # Interval
        self.update_interval_row = Adw.ComboRow()
        self.update_interval_row.set_title(_("Check Interval"))
        self.update_interval_row.set_subtitle(_("How often to check for updates"))

        interval_model = Gtk.StringList()
        for lbl in [
            _("Every hour"),
            _("Every 12 hours"),
            _("Every 24 hours (recommended)"),
            _("Custom"),
        ]:
            interval_model.append(lbl)
        self.update_interval_row.set_model(interval_model)
        self.update_interval_row.set_selected(2)
        self.update_interval_row.connect("notify::selected", self._on_interval_changed)
        update_group.add(self.update_interval_row)

        self.custom_interval_row = Adw.SpinRow.new_with_range(1, 1440, 1)
        self.custom_interval_row.set_title(_("Custom Interval (minutes)"))
        self.custom_interval_row.set_subtitle(
            _("Minimum: 1 minute, Maximum: 1440 minutes (24h)")
        )
        self.custom_interval_row.set_value(60)
        self.custom_interval_row.set_visible(False)
        update_group.add(self.custom_interval_row)

        content_box.append(update_group)

        # ---- Continue ----
        continue_group = Adw.PreferencesGroup()
        continue_group.set_margin_top(8)

        continue_row = Adw.ActionRow()
        continue_row.set_title(_("Continue"))
        continue_row.set_subtitle(_("Review build settings"))

        self.continue_button = Gtk.Button(label=_("Continue"))
        self.continue_button.add_css_class("suggested-action")
        self.continue_button.set_valign(Gtk.Align.CENTER)
        continue_row.add_suffix(self.continue_button)
        continue_row.set_activatable_widget(self.continue_button)
        continue_group.add(continue_row)

        content_box.append(continue_group)

    # -- helpers --

    def update_pattern_from_name(self, app_name: str) -> None:
        """Auto-fill filename pattern from app name."""
        if not app_name or not self.update_pattern_row:
            return
        import re

        safe = re.sub(r"[^a-z0-9\-_]", "", app_name.lower().replace(" ", "-"))
        if safe:
            new_pat = f"{safe}-*-x86_64.AppImage"
            cur = self.update_pattern_row.get_text().strip()
            if not cur or cur == "*-x86_64.AppImage":
                self.update_pattern_row.set_text(new_pat)

    def _on_interval_changed(self, combo_row, _param):
        self.custom_interval_row.set_visible(combo_row.get_selected() == 3)

    def _on_use_github_template(self, _button):
        template = "https://api.github.com/repos/OWNER/REPO/releases/latest"
        self.update_url_row.set_text(template)
        self.update_url_row.grab_focus()


# ---------------------------------------------------------------------------
#  Page 4 – Build
# ---------------------------------------------------------------------------


class BuildPage:
    """Build settings and the final 'Create AppImage' action."""

    def __init__(self):
        self.nav_page, toolbar_view, self.header = _make_nav_page(_("Build"), "build")

        scrolled, content_box = _scrollable_content()
        toolbar_view.set_content(scrolled)

        # ---- Output ----
        output_group = Adw.PreferencesGroup()
        output_group.set_title(_("Output Settings"))

        self.output_row = Adw.ActionRow()
        self.output_row.set_title(_("Output Directory"))
        self.output_row.set_subtitle(str(Path.cwd()))

        self.output_button = Gtk.Button(label=_("Choose Folder"))
        self.output_button.set_valign(Gtk.Align.CENTER)
        self.output_row.add_suffix(self.output_button)
        output_group.add(self.output_row)

        content_box.append(output_group)

        # ---- Build Environment ----
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

        # Manage environments expander
        self.env_expander = Adw.ExpanderRow()
        self.env_expander.set_title(_("Manage Build Environments"))
        self.env_expander.set_subtitle(_("Setup or remove build containers"))
        self.env_expander.set_show_enable_switch(False)
        env_group.add(self.env_expander)

        self.environments_listbox = Gtk.ListBox()
        self.environments_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.environments_listbox.add_css_class("boxed-list")
        self.env_expander.add_row(self.environments_listbox)

        # Callbacks for environment management (set by window)
        self.on_setup_clicked_callback = None
        self.on_remove_clicked_callback = None

        content_box.append(env_group)

        # ---- Dependencies ----
        deps_group = Adw.PreferencesGroup()
        deps_group.set_title(_("Dependencies"))

        self.deps_row = Adw.SwitchRow()
        self.deps_row.set_title(_("Include Dependencies"))
        self.deps_row.set_subtitle(_("Automatically include system dependencies"))
        self.deps_row.set_active(True)
        deps_group.add(self.deps_row)

        self.deps_expander_row = Adw.ExpanderRow()
        self.deps_expander_row.set_title(_("System Dependencies"))
        self.deps_expander_row.set_subtitle(
            _("Select which system libraries to bundle")
        )
        self.deps_expander_row.set_show_enable_switch(False)
        deps_group.add(self.deps_expander_row)

        self.deps_list_box = Gtk.ListBox()
        self.deps_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.deps_list_box.add_css_class("boxed-list")
        self.deps_expander_row.add_row(self.deps_list_box)

        content_box.append(deps_group)

        # ---- Icon Theme ----
        theme_group = Adw.PreferencesGroup()
        theme_group.set_title(_("Icon Theme"))

        self.icon_theme_row = Adw.SwitchRow()
        self.icon_theme_row.set_title(_("Include Icon Theme"))
        self.icon_theme_row.set_subtitle(
            _("Bundle icons for consistent UI across systems")
        )
        self.icon_theme_row.set_active(True)
        theme_group.add(self.icon_theme_row)

        self.icon_theme_expander_row = Adw.ExpanderRow()
        self.icon_theme_expander_row.set_title(_("Icon Theme Selection"))
        self.icon_theme_expander_row.set_subtitle(
            _("Choose which icon theme to bundle")
        )
        self.icon_theme_expander_row.set_show_enable_switch(False)
        theme_group.add(self.icon_theme_expander_row)

        papirus_row = Adw.ActionRow()
        papirus_row.set_title(_("Papirus"))
        papirus_row.set_subtitle(
            _("Modern, colorful icons (~6.4MB) - Default for GTK apps")
        )
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

        content_box.append(theme_group)

        # ---- Advanced ----
        advanced_group = Adw.PreferencesGroup()
        advanced_group.set_title(_("Advanced Options"))

        self.strip_row = Adw.SwitchRow()
        self.strip_row.set_title(_("Strip Debug Symbols"))
        self.strip_row.set_subtitle(_("Reduce file size by removing debug information"))
        self.strip_row.set_active(False)
        advanced_group.add(self.strip_row)

        content_box.append(advanced_group)

        # ---- Additional Libraries ----
        self._extra_libs_group = Adw.PreferencesGroup()
        self._extra_libs_group.set_title(_("Additional Libraries"))
        self._extra_libs_group.set_description(
            _(
                "Specify extra .so library files to bundle. "
                "Use file name patterns (e.g. 'libcurl.so*', 'libssl.so.3'). "
                "Do NOT use package names like 'libcurl-dev' — only .so file names."
            )
        )

        self.extra_lib_entry = Adw.EntryRow()
        self.extra_lib_entry.set_title(_("e.g. libexample.so*"))
        self.extra_lib_entry.set_show_apply_button(True)
        self.extra_lib_entry.connect("apply", self._on_add_extra_lib)

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text(_("Add library"))
        add_btn.add_css_class("flat")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_extra_lib)
        self.extra_lib_entry.add_suffix(add_btn)

        self._extra_libs_group.add(self.extra_lib_entry)

        self._extra_libs: list[str] = []
        self._extra_lib_rows: dict[str, Adw.ActionRow] = {}

        content_box.append(self._extra_libs_group)

        # ---- Build Action ----
        build_group = Adw.PreferencesGroup()
        build_group.set_margin_top(8)

        build_row = Adw.ActionRow()
        build_row.set_title(_("Create AppImage"))
        build_row.set_subtitle(_("Generate your distributable AppImage file"))

        self.build_button = Gtk.Button(label=_("Create AppImage"))
        self.build_button.add_css_class("suggested-action")
        self.build_button.set_valign(Gtk.Align.CENTER)
        self.build_button.set_sensitive(False)
        build_row.add_suffix(self.build_button)
        build_row.set_activatable_widget(self.build_button)
        build_group.add(build_row)

        content_box.append(build_group)

    # -- Extra libs API --

    def _on_add_extra_lib(self, _widget):
        text = self.extra_lib_entry.get_text().strip()
        if not text or text in self._extra_libs:
            return
        self._extra_libs.append(text)
        self._add_lib_row(text)
        self.extra_lib_entry.set_text("")

    def _add_lib_row(self, lib_name: str):
        row = Adw.ActionRow()
        row.set_title(lib_name)
        row.set_icon_name("application-x-sharedlib-symbolic")

        remove_btn = Gtk.Button()
        remove_btn.set_icon_name("edit-delete-symbolic")
        remove_btn.set_tooltip_text(_("Remove"))
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", self._remove_extra_lib, lib_name, row)
        row.add_suffix(remove_btn)

        self._extra_libs_group.add(row)
        self._extra_lib_rows[lib_name] = row

    def _remove_extra_lib(self, _button, lib_name: str, row: Adw.ActionRow):
        if lib_name in self._extra_libs:
            self._extra_libs.remove(lib_name)
            self._extra_libs_group.remove(row)
            self._extra_lib_rows.pop(lib_name, None)

    def get_extra_libs(self) -> list[str]:
        return list(self._extra_libs)

    def set_extra_libs(self, libs: list[str]) -> None:
        for row in self._extra_lib_rows.values():
            self._extra_libs_group.remove(row)
        self._extra_libs.clear()
        self._extra_lib_rows.clear()
        for lib in libs:
            self._extra_libs.append(lib)
            self._add_lib_row(lib)

    # -- Environment management helpers --

    def update_environments(self, env_manager: EnvironmentManager) -> None:
        """Populate the environment expander with available containers."""
        child = self.environments_listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.environments_listbox.remove(child)
            child = nxt

        for env in env_manager.get_supported_environments():
            row = Adw.ActionRow()
            row.set_title(env["name"])
            desc = env["description"]

            # Show "★ Recommended" badge
            is_recommended = _("Recommended") in desc
            if is_recommended:
                desc = desc.replace(_("Recommended") + " - ", "")
                badge = Gtk.Label(label=_("★ Recommended"))
                badge.add_css_class("accent")
                badge.set_valign(Gtk.Align.CENTER)
                row.add_suffix(badge)

            row.set_subtitle(desc)

            if env["status"] == "ready":
                icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
                row.add_suffix(icon)

                remove_button = Gtk.Button(label=_("Remove"))
                remove_button.set_valign(Gtk.Align.CENTER)
                remove_button.add_css_class("destructive-action")
                remove_button.connect(
                    "clicked",
                    lambda btn, eid=env["id"]: (
                        self.on_remove_clicked_callback(eid)
                        if self.on_remove_clicked_callback
                        else None
                    ),
                )
                row.add_suffix(remove_button)
            else:
                setup_button = Gtk.Button(label=_("Setup"))
                setup_button.set_valign(Gtk.Align.CENTER)
                setup_button.connect(
                    "clicked",
                    lambda btn, eid=env["id"]: (
                        self.on_setup_clicked_callback(eid)
                        if self.on_setup_clicked_callback
                        else None
                    ),
                )
                row.add_suffix(setup_button)

            self.environments_listbox.append(row)

    def update_env_model(self, env_manager: EnvironmentManager) -> None:
        """Update the environment ComboRow model with ready containers."""
        self.env_model.splice(0, self.env_model.get_n_items())
        self.env_model.append(_("Local System (Current Python)"))

        for env in env_manager.get_supported_environments():
            if env["status"] == "ready":
                self.env_model.append(f"{env['name']} (Container)")

        self.environment_row.set_selected(0)
