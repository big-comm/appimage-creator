"""
Main application class
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, Gio
from ui.window import AppImageCreatorWindow
from utils.i18n import _


class AppImageCreatorApp(Adw.Application):
    """Main application class"""
    
    def __init__(self):
        super().__init__(
            application_id='org.communitybig.appimage',
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS
        )
        
        self.set_resource_base_path('/com/github/appimage-creator')
        
    def do_activate(self):
        """Called when the application is activated"""
        window = self.props.active_window
        if not window:
            window = AppImageCreatorWindow(application=self)
        window.present()
        
    def do_startup(self):
        """Called when the application starts up"""
        Adw.Application.do_startup(self)
        self.setup_css()
        
    def setup_css(self):
        """Setup custom CSS styling"""
        css_provider = Gtk.CssProvider()
        css_data = """
        .error {
            background-color: alpha(@error_color, 0.1);
            border: 1px solid @error_color;
        }
        
        .success {
            background-color: alpha(@success_color, 0.1);
            border: 1px solid @success_color;
        }
        
        .accent {
            color: @accent_color;
        }
        
        .card {
            background-color: @card_bg_color;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        }
        """
        
        try:
            css_provider.load_from_data(css_data.encode())
            display = self.props.active_window.get_display() if self.props.active_window else None
            if display is None:
                display = Gtk.get_default_display() if hasattr(Gtk, 'get_default_display') else None
            
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception as e:
            print(_("Warning: Could not load custom CSS: {}").format(e))