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

    if project_root and os.path.isdir(project_root):
        root = Path(project_root)

        for label, glob, limit in [
            (_("Python Files"), "*.py", 30),
            (_("Shell Scripts"), "*.sh", 10),
            (_("UI Files"), "*.ui", 10),
            (_("CSS Files"), "*.css", 10),
        ]:
            found = list(root.rglob(glob))
            if glob == "*.ui":
                found += list(root.rglob("*.glade"))
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
                    fp = "    └── " if j == min(9, fc - 1) else "    ├── "
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
        f"  {_('Project Root')}: {project_root or _('Not detected')}",
        f"  {_('Additional Directories')}: {len(directories)}",
    ]

    if project_root and os.path.isdir(project_root):
        root = Path(project_root)
        counts = {
            "Python": len(list(root.rglob("*.py"))),
            "Shell": len(list(root.rglob("*.sh"))),
            "UI": len(list(root.rglob("*.ui"))) + len(list(root.rglob("*.glade"))),
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
