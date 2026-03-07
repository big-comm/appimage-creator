"""
Popover-based tooltip helper for GTK4/libadwaita.

On Wayland: custom styled popover with fade animation.
On X11: falls back to native GTK tooltips (avoids compositor segfaults).
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Gdk, GLib

from utils.i18n import _


def _is_x11_backend() -> bool:
    """Check if running on X11 backend."""
    try:
        display = Gdk.Display.get_default()
        if display is None:
            return False
        return "X11" in type(display).__name__
    except Exception:
        return False


def get_tooltips() -> dict[str, str]:
    """Return translated tooltips dictionary for all UI elements."""
    return {
        # Application Setup page
        "executable": _(
            "Select the main binary or script that starts your application.\n\n"
            "This is the entry point — the file that will be executed when "
            "the user launches the AppImage."
        ),
        "app_name": _(
            "The application name used for the AppImage filename and menu entry.\n\n"
            "Only letters, numbers, spaces, hyphens, underscores and dots are allowed."
        ),
        "app_icon": _(
            "The application icon is used in the system menu, taskbar, and file manager.\n\n"
            "A 256×256 or larger PNG/SVG icon is recommended.\n\n"
            "Without an icon, the AppImage will display a generic icon in menus and taskbar."
        ),
        "desktop_file": _(
            "The .desktop file controls how the application appears in the system menu, "
            "including its name, icon, categories, and launch options.\n\n"
            "If you don't provide one, a basic .desktop file will be generated "
            "automatically using the information configured here.\n\n"
            "For full integration, provide your own file with proper categories and metadata."
        ),
        "app_type": _(
            "Determines how the launcher (AppRun) script is generated.\n\n"
            "This is auto-detected from the executable, but you can override it:\n"
            "• Binary — compiled native executable\n"
            "• Python — Python script using system interpreter\n"
            "• Electron — Electron-based application\n"
            "• GTK/Qt — GUI applications with toolkit-specific environment variables"
        ),
        # Configuration page
        "version": _(
            "Semantic version of your application (e.g. 1.2.3).\n\n"
            "This is embedded in the AppImage metadata and used for update detection."
        ),
        "description": _(
            "A short one-line description shown in application menus and package managers.\n\n"
            "Keep it concise — typically under 80 characters."
        ),
        "terminal": _(
            "Enable this for CLI tools that need a terminal to run.\n\n"
            "When enabled, the desktop environment will open a terminal emulator "
            "before launching the application."
        ),
        "update_url": _(
            "GitHub Releases API URL for automatic updates.\n\n"
            "Must start with https:// — typically:\n"
            "https://api.github.com/repos/OWNER/REPO/releases/latest\n\n"
            "Click the paste button to insert a template."
        ),
        "update_pattern": _(
            "Glob pattern to identify which file to download from the release.\n\n"
            "The asterisk (*) matches any text. Examples:\n"
            "• myapp-*-x86_64.AppImage\n"
            "• *-gui-*.AppImage"
        ),
        # Build page
        "output_dir": _(
            "The directory where the final .AppImage file will be saved.\n\n"
            "Defaults to the current working directory."
        ),
        "build_environment": _(
            "Choose where to build the AppImage.\n\n"
            "Using a Distrobox container provides maximum compatibility with "
            "older Linux distributions, as it builds against an older glibc."
        ),
        "include_deps": _(
            "Bundle shared libraries (.so files) into the AppImage.\n\n"
            "This ensures the application works on other systems that may "
            "not have the required libraries installed."
        ),
        "icon_theme": _(
            "Bundle an icon theme inside the AppImage.\n\n"
            "Without a bundled theme, some icons may be missing on desktops "
            "that use a different icon theme than the one your app was designed for."
        ),
        "strip_symbols": _(
            "Remove debug symbols from binaries to reduce the AppImage size.\n\n"
            "This makes the file smaller but harder to debug if issues occur."
        ),
    }


class TooltipHelper:
    """Manages a single reusable popover for displaying rich tooltips.

    Uses a singleton popover to prevent state conflicts. CSS classes
    handle fade-in/out animation.
    """

    def __init__(self) -> None:
        self.tooltips = get_tooltips()
        self.active_widget: Gtk.Widget | None = None
        self.show_timer_id: int | None = None
        self._color_css_provider: Gtk.CssProvider | None = None
        self._use_native_tooltips = _is_x11_backend()

        if self._use_native_tooltips:
            self.popover = None
            self.label = None
            self.css_provider = None
            return

        self.popover = Gtk.Popover()
        self.popover.set_autohide(False)
        self.popover.set_has_arrow(False)
        self.popover.set_position(Gtk.PositionType.TOP)
        self.popover.set_offset(0, -12)

        self.label = Gtk.Label(
            wrap=True,
            max_width_chars=50,
            margin_start=12,
            margin_end=12,
            margin_top=8,
            margin_bottom=8,
            halign=Gtk.Align.START,
        )
        self.popover.set_child(self.label)

        self.css_provider = Gtk.CssProvider()
        css = b"""
        .tooltip-popover {
            opacity: 0;
            transition: opacity 250ms ease-in-out;
        }
        .tooltip-popover.visible {
            opacity: 1;
        }
        """
        self.css_provider.load_from_data(css)
        self.popover.add_css_class("tooltip-popover")

        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        self.popover.connect("map", self._on_popover_map)
        GLib.idle_add(self._update_colors)

    # ── Public API ──────────────────────────────────────────────

    def add_tooltip(self, widget: Gtk.Widget, tooltip_key: str) -> None:
        """Connect a widget to the tooltip system."""
        tooltip_text = self.tooltips.get(tooltip_key, "")

        if self._use_native_tooltips:
            if tooltip_text:
                widget.set_tooltip_text(tooltip_text)
            return

        widget.tooltip_key = tooltip_key  # type: ignore[attr-defined]

        controller = Gtk.EventControllerMotion.new()
        controller.connect("enter", self._on_enter, widget)
        controller.connect("leave", self._on_leave)
        widget.add_controller(controller)

    def cleanup(self) -> None:
        """Call on application shutdown."""
        self._clear_timer()
        if self.popover:
            try:
                if self.popover.get_parent():
                    self.popover.unparent()
            except Exception:
                pass

    # ── Internal ────────────────────────────────────────────────

    def _on_popover_map(self, _popover: Gtk.Popover) -> None:
        if self.popover:
            self.popover.add_css_class("visible")

    def _clear_timer(self) -> None:
        if self.show_timer_id:
            GLib.source_remove(self.show_timer_id)
            self.show_timer_id = None

    def _on_enter(
        self,
        _controller: Gtk.EventControllerMotion,
        _x: float,
        _y: float,
        widget: Gtk.Widget,
    ) -> None:
        if self.active_widget == widget:
            return
        self._clear_timer()
        self._hide_tooltip()
        self.active_widget = widget
        self.show_timer_id = GLib.timeout_add(250, self._show_tooltip)

    def _on_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self._clear_timer()
        if self.active_widget:
            self._hide_tooltip(animate=True)
            self.active_widget = None

    def _show_tooltip(self) -> int:
        if not self.active_widget or not self.popover:
            return GLib.SOURCE_REMOVE

        try:
            if (
                not self.active_widget.get_mapped()
                or not self.active_widget.get_visible()
            ):
                self.active_widget = None
                return GLib.SOURCE_REMOVE
            if self.active_widget.get_parent() is None:
                self.active_widget = None
                return GLib.SOURCE_REMOVE
            if self.active_widget.get_native() is None:
                self.active_widget = None
                return GLib.SOURCE_REMOVE
        except Exception:
            self.active_widget = None
            return GLib.SOURCE_REMOVE

        tooltip_key = getattr(self.active_widget, "tooltip_key", None)
        if not tooltip_key:
            return GLib.SOURCE_REMOVE

        tooltip_text = self.tooltips.get(tooltip_key)
        if not tooltip_text:
            return GLib.SOURCE_REMOVE

        try:
            self.label.set_text(tooltip_text)
            if self.popover.get_parent() is not None:
                self.popover.unparent()
            self.popover.remove_css_class("visible")
            self.popover.set_parent(self.active_widget)
            self.popover.popup()
        except Exception:
            self.active_widget = None

        self.show_timer_id = None
        return GLib.SOURCE_REMOVE

    def _hide_tooltip(self, animate: bool = False) -> None:
        if not self.popover:
            return
        try:
            if not self.popover.is_visible():
                return

            def do_cleanup() -> int:
                try:
                    if self.popover:
                        self.popover.popdown()
                        if self.popover.get_parent():
                            self.popover.unparent()
                except Exception:
                    pass
                return GLib.SOURCE_REMOVE

            self.popover.remove_css_class("visible")
            if animate:
                GLib.timeout_add(200, do_cleanup)
            else:
                do_cleanup()
        except Exception:
            pass

    def _update_colors(self) -> int:
        """Update tooltip colors based on current theme."""
        if self._use_native_tooltips:
            return GLib.SOURCE_REMOVE

        try:
            style_manager = Adw.StyleManager.get_default()
            is_dark = style_manager.get_dark()
            if is_dark:
                bg_color = "#2a2a2a"
                fg_color = "#ffffff"
            else:
                bg_color = "#fafafa"
                fg_color = "#2e2e2e"
        except Exception:
            bg_color = "#2a2a2a"
            fg_color = "#ffffff"

        tooltip_bg = self._adjust_background(bg_color)

        try:
            hex_val = bg_color.lstrip("#")
            r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            is_dark_theme = luminance < 0.5
        except (ValueError, IndexError):
            is_dark_theme = True

        border_color = "#707070" if is_dark_theme else "#a0a0a0"

        css = (
            f"popover.tooltip-popover > contents {{\n"
            f"    background-color: {tooltip_bg};\n"
            f"    background-image: none;\n"
            f"    color: {fg_color};\n"
            f"    border: 1px solid {border_color};\n"
            f"    border-radius: 8px;\n"
            f"}}\n"
            f"popover.tooltip-popover label {{ color: {fg_color}; }}\n"
        )

        display = Gdk.Display.get_default()
        if not display:
            return GLib.SOURCE_REMOVE

        if self._color_css_provider:
            try:
                Gtk.StyleContext.remove_provider_for_display(
                    display, self._color_css_provider
                )
            except Exception:
                pass
            self._color_css_provider = None

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        try:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 100,
            )
            self._color_css_provider = provider
        except Exception:
            pass

        return GLib.SOURCE_REMOVE

    @staticmethod
    def _adjust_background(bg_color: str) -> str:
        """Adjust tooltip background for better contrast."""
        try:
            hex_val = bg_color.lstrip("#")
            r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            if luminance < 0.5:
                adj = 50
                r, g, b = min(255, r + adj), min(255, g + adj), min(255, b + adj)
            else:
                adj = 30
                r, g, b = max(0, r - adj), max(0, g - adj), max(0, b - adj)
            return f"#{r:02x}{g:02x}{b:02x}"
        except (ValueError, IndexError):
            return bg_color
