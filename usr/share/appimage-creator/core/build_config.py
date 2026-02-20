"""
Build configuration dictionaries for system dependencies and binaries.

These define which libraries, typelibs, and binaries should be detected
and bundled when creating AppImages.
"""

# Master dictionary for system dependencies
SYSTEM_DEPENDENCIES = {
    "glib": {
        "name": "GLib/GObject",
        "libs": [
            "libgmodule-2.0.so*",
            "libgirepository-1.0.so*",
            "libgirepository-2.0.so*",
            "libpcre.so.3",
        ],
        "typelibs": [
            "GLib-2.0.typelib",
            "GObject-2.0.typelib",
            "Gio-2.0.typelib",
            "GModule-2.0.typelib",
            "cairo-1.0.typelib",
            "Pango-1.0.typelib",
            "PangoCairo-1.0.typelib",
            "GdkPixbuf-2.0.typelib",
        ],
        "detection_keyword": "gi",
        "essential": True,
    },
    "jpeg": {
        "name": "JPEG Library",
        "libs": ["libjpeg.so.8*"],
        "typelibs": [],
        "detection_keyword": "gtk4",
        "essential": False,
        "conflicting": True,
    },
    "gtk3": {
        "name": "GTK3",
        "libs": ["libgtk-3.so*", "libcairo.so*", "libcairo-gobject.so*"],
        "typelibs": [
            "Gtk-3.0.typelib",
            "Gdk-3.0.typelib",
            "GdkPixbuf-2.0.typelib",
            "Pango-1.0.typelib",
            "PangoCairo-1.0.typelib",
            "cairo-1.0.typelib",
            "HarfBuzz-0.0.typelib",
            "Atk-1.0.typelib",
        ],
        "detection_keyword": "gtk3",
        "essential": False,
    },
    "gtk4": {
        "name": "GTK4",
        "libs": ["libgtk-4.so*", "libgraphene-1.0.so*"],
        "typelibs": [
            "Gtk-4.0.typelib",
            "Gdk-4.0.typelib",
            "Gsk-4.0.typelib",
            "Graphene-1.0.typelib",
            "Pango-1.0.typelib",
            "PangoCairo-1.0.typelib",
            "cairo-1.0.typelib",
            "GdkPixbuf-2.0.typelib",
            "HarfBuzz-0.0.typelib",
            "freetype2-2.0.typelib",
        ],
        "detection_keyword": "gtk4",
        "essential": False,
    },
    "adwaita": {
        "name": "Libadwaita 1",
        "libs": ["libadwaita-1.so*"],
        "typelibs": ["Adw-1.typelib"],
        "detection_keyword": "adwaita",
        "essential": False,
    },
    "vte": {
        "name": "VTE (Terminal Widget)",
        "libs": [
            "libvte-2.91.so*",
            "libvte-2.91-gtk4.so*",
            "libicuuc.so*",
            "libicudata.so*",
            "libicui18n.so*",
        ],
        "typelibs": ["Vte-2.91.typelib", "Vte-3.91.typelib"],
        "detection_keyword": "vte",
        "essential": False,
    },
    "libsecret": {
        "name": "Libsecret (Keyring)",
        "libs": ["libsecret-1.so*"],
        "typelibs": ["Secret-1.typelib"],
        "detection_keyword": "libsecret",
        "essential": False,
    },
    "gstreamer-gtk": {
        "name": "GStreamer GTK Sink",
        "libs": ["libgstgtk.so*"],
        "typelibs": ["GstGtk-1.0.typelib"],
        "detection_keyword": "gstreamer-gtk",
        "essential": False,
    },
    "mpv": {
        "name": "MPV Library",
        "libs": [
            "libmpv.so*",
            "libavutil.so*",
            "libavcodec.so*",
            "libavformat.so*",
            "libswresample.so*",
            "libswscale.so*",
            "libplacebo.so*",
            "libvulkan.so*",
            "libx264.so*",
        ],
        "typelibs": [],
        "detection_keyword": "mpv",
        "essential": False,
    },
}

# Master dictionary for system binaries to be detected and bundled
SYSTEM_BINARIES = {
    "vainfo": {
        "name": "VA-API Info Tool",
        "binary_name": "vainfo",
        "detection_keyword": "vainfo",
        "essential": False,
    },
    "mpv": {
        "name": "MPV Media Player",
        "binary_name": "mpv",
        "detection_keyword": "mpv",
        "essential": False,
        "manage_libs_manually": True,
    },
}
