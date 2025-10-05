#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Translation utilities using gettext
"""

import gettext

# Configure the translation domain
gettext.textdomain("appimage-creator")

# Export translation function
_ = gettext.gettext