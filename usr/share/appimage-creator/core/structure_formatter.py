"""Format detailed AppImage structure for display."""

import os
from pathlib import Path

from utils.file_ops import scan_directory_structure
from utils.i18n import _
from utils.system import format_size, sanitize_filename


def generate_detailed_structure(
    app_name_raw: str,
    executable: str | None,
    structure_analysis: dict | None,
    directories: list[str],
    app_type: str,
) -> str:
    """Build a detailed text representation of the AppImage structure.

    All parameters are plain data — no UI dependencies.
    """
    app_name = sanitize_filename(app_name_raw or "MyApp")

    lines: list[str] = [_("AppImage Structure - Detailed View"), "=" * 60, ""]
    lines += [
        _("[AppImage Root]"),
        _("├── AppRun (main launcher)"),
        f"├── {app_name}.desktop",
        f"├── {app_name}.svg",
        _("└── usr/"),
        _("    ├── bin/"),
        f"    │   └── {app_name} (launcher)",
        _("    ├── lib/"),
        _("    └── share/"),
        f"        └── {app_name}/",
    ]

    if executable:
        lines.append(
            f"            ├── {os.path.basename(executable)}"
            " (main executable)"
        )

    project_root = (
        structure_analysis.get("project_root")
        if structure_analysis
        else None
    )
    # Compiled apps have no project_root (nothing is tree-copied); show the
    # resource root in the summary. The rglob sections below stay keyed on
    # project_root so a huge build tree (Rust target/) is never walked.
    display_root = project_root or (
        structure_analysis.get("resource_root") if structure_analysis else None
    )

    # Walk the project tree only once and reuse the results in both the detail
    # listing and the summary below (avoids 8 redundant rglob traversals).
    glob_cache = {}
    if project_root and os.path.isdir(project_root):
        _root = Path(project_root)
        for pattern in ("*.py", "*.sh", "*.ui", "*.glade", "*.css"):
            glob_cache[pattern] = list(_root.rglob(pattern))

    if project_root and os.path.isdir(project_root):
        root = Path(project_root)

        for label, glob, limit in [
            (_("Python Files"), "*.py", 30),
            (_("Shell Scripts"), "*.sh", 10),
            (_("UI Files"), "*.ui", 10),
            (_("CSS Files"), "*.css", 10),
        ]:
            found = list(glob_cache.get(glob, []))
            if glob == "*.ui":
                found += list(glob_cache.get("*.glade", []))
            if found:
                lines += ["", f"            [{label}]"]
                for f in found[:limit]:
                    rel = f.relative_to(root) if f.is_relative_to(root) else f.name
                    lines.append(f"            ├── {rel}")
                if len(found) > limit:
                    lines.append(
                        f"            └── ... and {len(found) - limit} more"
                    )

    if structure_analysis:
        det = structure_analysis.get("detected_files", {})
        for key, label in [
            ("icons", _("Icon Files")),
            ("locale_dirs", _("Locale Directories")),
            ("desktop_files", _("Desktop Files")),
        ]:
            items = det.get(key, [])
            if items:
                lines += ["", f"            [{label}]"]
                for f in items[:15]:
                    suffix = "/" if key == "locale_dirs" else ""
                    lines.append(f"            ├── {os.path.basename(f)}{suffix}")
                if len(items) > 15:
                    lines.append(f"            └── ... and {len(items) - 15} more")

    if directories:
        lines += ["", _("[Additional Directories]")]
        for i, directory in enumerate(directories):
            prefix = "└── " if i == len(directories) - 1 else "├── "
            try:
                structure = scan_directory_structure(directory)
                fc = len(structure.get("files", []))
                ts = structure.get("total_size", 0)
                dn = os.path.basename(directory)
                lines.append(f"{prefix}{dn}/ ({fc} files, {format_size(ts)})")
                for j, fi in enumerate(structure.get("files", [])[:10]):
                    # Only the genuine last line (no "...more" line after) gets └──
                    is_last = j == fc - 1
                    fp = "    └── " if is_last else "    ├── "
                    lines.append(f"{fp}{fi['name']}")
                if fc > 10:
                    lines.append(f"    └── ... and {fc - 10} more files")
            except Exception as e:
                lines.append(
                    f"{prefix}{os.path.basename(directory)}/ (error reading: {e})"
                )

    lines += [
        "",
        "=" * 60,
        _("SUMMARY"),
        "=" * 60,
        f"  {_('Application Name')}: {app_name}",
        f"  {_('Application Type')}: {app_type}",
        f"  {_('Project Root')}: {display_root or _('Not detected')}",
        f"  {_('Additional Directories')}: {len(directories)}",
    ]

    if project_root and os.path.isdir(project_root):
        counts = {
            "Python": len(glob_cache.get("*.py", [])),
            "Shell": len(glob_cache.get("*.sh", [])),
            "UI": len(glob_cache.get("*.ui", []))
            + len(glob_cache.get("*.glade", [])),
        }
        if any(counts.values()):
            lines += ["", _("  File Breakdown:")]
            for lbl, cnt in counts.items():
                if cnt:
                    lines.append(f"    • {lbl}: {cnt}")
        if structure_analysis:
            det = structure_analysis.get("detected_files", {})
            for key, lbl in [
                ("icons", "Icons"),
                ("locale_dirs", "Locale Dirs"),
                ("desktop_files", "Desktop"),
            ]:
                if det.get(key):
                    lines.append(f"    • {lbl}: {len(det[key])}")

    return "\n".join(lines)
