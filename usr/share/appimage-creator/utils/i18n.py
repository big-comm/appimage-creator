#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# translation_utils.py - Utilities for translation support
#
import gettext
import os

# Determine locale directory (works in AppImage and system install)
locale_dir = '/usr/share/locale'  # Default for system install

# Check if we're in an AppImage
if 'APPIMAGE' in os.environ or 'APPDIR' in os.environ:
    # Running from AppImage
    # translation_utils.py is in: usr/share/appimage-creator/utils/translation_utils.py
    # We need to get to: usr/share/locale
    script_dir = os.path.dirname(os.path.abspath(__file__))  # usr/share/appimage-creator/utils
    app_dir = os.path.dirname(script_dir)                    # usr/share/appimage-creator
    share_dir = os.path.dirname(app_dir)                     # usr/share
    appimage_locale = os.path.join(share_dir, 'locale')      # usr/share/locale
    
    if os.path.isdir(appimage_locale):
        locale_dir = appimage_locale

# Configure the translation text domain for appimage-creator
gettext.bindtextdomain("appimage-creator", locale_dir)
gettext.textdomain("appimage-creator")

# Export _ directly as the translation function
_ = gettext.gettext