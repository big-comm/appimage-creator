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
    "appindicator": {
        # Tauri/Electron apps with a tray icon dlopen() this at runtime, so it
        # never shows up in DT_NEEDED. Without it bundled, the app aborts on
        # any host that doesn't ship libayatana-appindicator (Fedora, for one).
        "name": "AppIndicator (System Tray)",
        "libs": [
            "libayatana-appindicator3.so*",
            "libayatana-indicator3.so*",
            "libayatana-ido3-0.4.so*",
            "libdbusmenu-glib.so*",
            "libdbusmenu-gtk3.so*",
        ],
        "typelibs": [],
        "detection_keyword": "appindicator",
        "essential": False,
    },
    "gstreamer-gtk": {
        "name": "GStreamer GTK Sink",
        "libs": ["libgstgtk.so*"],
        "typelibs": ["GstGtk-1.0.typelib"],
        "detection_keyword": "gstreamer-gtk",
        "essential": False,
    },
    "poppler": {
        "name": "Poppler (PDF Rendering)",
        # libpoppler-glib is the introspected front end and links against the
        # core libpoppler, whose SONAME carries a fast-moving version suffix,
        # so the host copy is rarely a usable substitute.  openjp2 and lcms2
        # are the image decoders poppler pulls in that a plain GTK app would
        # not, and so cannot be assumed present on the target.
        # Deliberately minimal. Every extra library here overrides the target's
        # copy for every consumer on the system, not just for us, so anything
        # the target already has is left alone. openjp2 is the exception: it
        # arrives as a dependency of poppler itself, so a target without
        # poppler installed does not have it either.
        "libs": [
            "libpoppler-glib.so*",
            "libpoppler.so*",
            "libopenjp2.so*",
            # Debian and Ubuntu build poppler against their own gnutls flavour
            # of curl. That SONAME exists nowhere else -- Fedora and Arch ship
            # only libcurl.so.4, and its symbols carry a different version tag
            # (CURL_OPENSSL_4 vs CURL_GNUTLS_3), so it cannot stand in. Poppler
            # from those containers therefore cannot load anywhere else unless
            # this travels with it.
            "libcurl-gnutls.so*",
            # Of curl's backends, bundle only the SONAMEs a target genuinely
            # lacks. librtmp lives in RPM Fusion, so Fedora has none, and
            # Debian's libsasl2.so.2 was superseded by .so.3 elsewhere -- a
            # different SONAME, so the two coexist.
            #
            # Everything else curl needs (libssh, libldap, krb5, nghttp2, psl,
            # com_err) is present on any target AND is loaded by the target's
            # own libcurl.so.4. Bundling those puts an older copy ahead of the
            # host's on LD_LIBRARY_PATH and breaks it: Fedora's libcurl wants
            # LIBSSH_4_10_0, which Ubuntu's libssh does not export, and the
            # whole GTK stack then fails to load.
            "librtmp.so*",
            "libsasl2.so.2*",
        ],
        "typelibs": ["Poppler-0.18.typelib"],
        "detection_keyword": "poppler",
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
    # NOTE: do not add pdftoppm (or any other poppler-utils binary) here.
    # Binaries are resolved with shutil.which() and handed to linuxdeploy, both
    # of which run on the host even when the build targets a container, so the
    # host's library closure gets dragged into an AppDir whose other libraries
    # came from the container.  For poppler that mixes a host libtiff needing
    # jpeg12_* against the container's older libjpeg, and GTK fails to load.
    # PDF apps fall back to the Poppler introspection bindings, which are
    # bundled correctly from the container by SYSTEM_DEPENDENCIES["poppler"].
    "mpv": {
        "name": "MPV Media Player",
        "binary_name": "mpv",
        "detection_keyword": "mpv",
        "essential": False,
        "manage_libs_manually": True,
    },
}


# Distro packages that provide each SYSTEM_DEPENDENCIES profile inside the
# build container. Values are *candidates* in order of preference, not a single
# name: package names drift between releases (Ubuntu's 64-bit time_t rename
# turned libgtk-3-0 into libgtk-3-0t64), so the first candidate the container's
# package manager actually knows about is the one used. Anything not covered
# here the user adds by hand in the build page — this map exists to make the
# common cases discoverable, not to be exhaustive.
DEPENDENCY_PACKAGES = {
    "glib": {
        "apt": ["python3-gi", "gir1.2-glib-2.0"],
        "dnf": ["python3-gobject", "gobject-introspection"],
        "pacman": ["python-gobject"],
    },
    "jpeg": {
        "apt": ["libjpeg-turbo8"],
        "dnf": ["libjpeg-turbo"],
        "pacman": ["libjpeg-turbo"],
    },
    "gtk3": {
        "apt": ["libgtk-3-0t64", "libgtk-3-0"],
        "dnf": ["gtk3"],
        "pacman": ["gtk3"],
    },
    "gtk4": {
        "apt": ["libgtk-4-1"],
        "dnf": ["gtk4"],
        "pacman": ["gtk4"],
    },
    "adwaita": {
        "apt": ["libadwaita-1-0"],
        "dnf": ["libadwaita"],
        "pacman": ["libadwaita"],
    },
    "vte": {
        "apt": ["libvte-2.91-0t64", "libvte-2.91-0"],
        "dnf": ["vte291"],
        "pacman": ["vte3"],
    },
    "libsecret": {
        "apt": ["libsecret-1-0"],
        "dnf": ["libsecret"],
        "pacman": ["libsecret"],
    },
    "appindicator": {
        "apt": ["libayatana-appindicator3-1"],
        "dnf": ["libayatana-appindicator-gtk3"],
        "pacman": ["libayatana-appindicator"],
    },
    "gstreamer-gtk": {
        "apt": ["gstreamer1.0-gtk3"],
        "dnf": ["gstreamer1-plugins-good-gtk"],
        "pacman": ["gst-plugin-gtk"],
    },
    "poppler": {
        "apt": ["gir1.2-poppler-0.18", "libpoppler-glib8t64", "libpoppler-glib8"],
        "dnf": ["poppler-glib"],
        "pacman": ["poppler-glib"],
    },
    "mpv": {
        "apt": ["libmpv2", "libmpv1"],
        "dnf": ["mpv-libs"],
        "pacman": ["mpv"],
    },
}

# A package name as the distros allow it. Names reach the container inside a
# shell command, so anything outside this set is rejected before it gets there.
PACKAGE_NAME_PATTERN = r"^[a-z0-9][a-z0-9+._-]{0,99}$"
