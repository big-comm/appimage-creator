#!/usr/bin/env python3
"""
Debug script for icon theme issues in AppImage
"""

import os
import sys
from pathlib import Path

print("=" * 70)
print("ICON THEME DEBUG - AppImage")
print("=" * 70)

# 1. Verificar APPDIR
print("\n[1] APPDIR Detection:")
appdir = os.environ.get('APPDIR')
if appdir:
    print(f"✓ APPDIR: {appdir}")
    appdir_path = Path(appdir)
else:
    print("✗ APPDIR not set - not running from AppImage?")
    # Try to detect from script location
    appdir_path = Path(__file__).parent.parent.parent
    print(f"  Trying: {appdir_path}")

# 2. Verificar XDG_DATA_DIRS
print("\n[2] XDG_DATA_DIRS:")
xdg_data_dirs = os.environ.get('XDG_DATA_DIRS', '')
print(f"Value: {xdg_data_dirs}")

if appdir:
    expected = f"{appdir}/usr/share"
    if expected in xdg_data_dirs:
        print(f"✓ AppImage path present: {expected}")
    else:
        print(f"✗ AppImage path MISSING: {expected}")
        print("  This is the problem! GTK won't find bundled icons.")

# 3. Verificar estrutura de ícones
print("\n[3] Icon Theme Structure:")
icons_dir = appdir_path / "usr" / "share" / "icons"

if icons_dir.exists():
    print(f"✓ Icons directory exists: {icons_dir}")
    
    for theme in ['Papirus', 'Papirus-Dark', 'Adwaita']:
        theme_dir = icons_dir / theme
        if theme_dir.exists():
            print(f"\n  [{theme}]")
            
            # Check index.theme
            index_file = theme_dir / "index.theme"
            if index_file.exists():
                print(f"    ✓ index.theme exists")
                
                # Read first lines
                with open(index_file) as f:
                    lines = f.readlines()[:5]
                    for line in lines:
                        if line.strip():
                            print(f"      {line.rstrip()}")
            else:
                print(f"    ✗ index.theme MISSING")
            
            # Check symbolic directory
            symbolic_dir = theme_dir / "symbolic"
            if symbolic_dir.exists():
                # Count icons
                icon_count = len(list(symbolic_dir.rglob("*.svg")))
                print(f"    ✓ symbolic/ directory: {icon_count} icons")
                
                # Check specific missing icons
                actions_dir = symbolic_dir / "actions"
                if actions_dir.exists():
                    missing_icons = ['view-pin-symbolic.svg', 'view-refresh-symbolic.svg', 
                                   'user-home-symbolic.svg']
                    for icon in missing_icons:
                        icon_path = actions_dir / icon
                        if icon_path.exists():
                            print(f"      ✓ {icon}")
                        else:
                            print(f"      ✗ {icon} MISSING")
            else:
                print(f"    ✗ symbolic/ directory MISSING")
        else:
            print(f"  ✗ {theme} not found")
else:
    print(f"✗ Icons directory MISSING: {icons_dir}")

# 4. Test GTK icon lookup
print("\n[4] GTK Icon Lookup Test:")
try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk, Gio
    
    print("✓ GTK4 imported successfully")
    
    # Get icon theme
    icon_theme = Gtk.IconTheme.get_for_display(
        Gtk.get_default_display() if hasattr(Gtk, 'get_default_display') else None
    )
    
    # Get search path
    search_path = icon_theme.get_search_path()
    print(f"\nIcon search path ({len(search_path)} locations):")
    for i, path in enumerate(search_path, 1):
        print(f"  {i}. {path}")
        if appdir and appdir in path:
            print(f"     ✓ AppImage path!")
    
    # Try to lookup missing icons
    print("\nTrying to lookup missing icons:")
    test_icons = ['view-pin-symbolic', 'view-refresh-symbolic', 'user-home-symbolic']
    
    for icon_name in test_icons:
        icon_paintable = icon_theme.lookup_icon(
            icon_name,
            None,  # fallbacks
            16,    # size
            1,     # scale
            Gtk.TextDirection.NONE,
            0      # flags
        )
        
        if icon_paintable:
            file = icon_paintable.get_file()
            if file:
                path = file.get_path()
                print(f"  ✓ {icon_name}: {path}")
                if appdir and appdir in path:
                    print(f"    → From AppImage!")
            else:
                print(f"  ? {icon_name}: Found but no file path")
        else:
            print(f"  ✗ {icon_name}: NOT FOUND")
    
except Exception as e:
    print(f"✗ Error testing GTK: {e}")
    import traceback
    traceback.print_exc()

# 5. Environment variables summary
print("\n[5] Relevant Environment Variables:")
env_vars = ['GTK_PATH', 'GTK_DATA_PREFIX', 'GTK_EXE_PREFIX', 
            'GSETTINGS_SCHEMA_DIR', 'GI_TYPELIB_PATH']

for var in env_vars:
    value = os.environ.get(var, '(not set)')
    print(f"  {var}: {value}")

print("\n" + "=" * 70)
print("DEBUG COMPLETE")
print("=" * 70)