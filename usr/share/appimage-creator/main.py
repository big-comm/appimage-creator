#!/usr/bin/env python3
"""
AppImage Creator - Main Entry Point
A GTK4 application for creating AppImages from any type of application
"""

import sys
import os

# Add project root to path if needed
if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import GObject
from ui.app import AppImageCreatorApp


def main():
    """Main function"""
    GObject.threads_init()
    app = AppImageCreatorApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())