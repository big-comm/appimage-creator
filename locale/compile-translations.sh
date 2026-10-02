#!/bin/bash
# Compile the gettext catalogs into the .mo files shipped by the package.
#
#   locale/<lang>.po                    -> usr/share/locale/<lang>/LC_MESSAGES/appimage-creator.mo
#   locale/appimage-updater/<lang>.po   -> usr/share/locale/<lang>/LC_MESSAGES/appimage-updater.mo
#                                          and usr/share/appimage-creator/updater/locale/<lang>/...
#                                          (the copy bundled into generated AppImages)
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

for po in locale/*.po; do
    lang=$(basename "$po" .po)
    mkdir -p "usr/share/locale/$lang/LC_MESSAGES"
    # attranslate marks entries with these comments; they are not real fuzzies
    sed '/^#: NEEDS WORK$/d;/^#, fuzzy$/d' "$po" > "$tmp"
    msgfmt --check-format -o "usr/share/locale/$lang/LC_MESSAGES/appimage-creator.mo" "$tmp"
done

for po in locale/appimage-updater/*.po; do
    lang=$(basename "$po" .po)
    for dir in usr/share/locale usr/share/appimage-creator/updater/locale; do
        mkdir -p "$dir/$lang/LC_MESSAGES"
        msgfmt --check-format -o "$dir/$lang/LC_MESSAGES/appimage-updater.mo" "$po"
    done
done

echo "Compiled $(ls locale/*.po | wc -l) appimage-creator and $(ls locale/appimage-updater/*.po | wc -l) appimage-updater catalogs."
