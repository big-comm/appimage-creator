# PLANNING.md — AppImage Creator Audit & Roadmap

> **Audit date:** 2025-07-14
> **Auditor profile:** Senior Python/GTK4 Engineer & UX Specialist
> **Scope:** All 32 Python files (10,488 lines) — full manual read + automated analysis
> **Constraint:** Audit only — NO code changes

---

## Table of Contents

1. [File Inventory](#1-file-inventory)
2. [Automated Analysis Summary](#2-automated-analysis-summary)
3. [Critical Findings](#3-critical-findings)
4. [High Priority Findings](#4-high-priority-findings)
5. [Medium Priority Findings](#5-medium-priority-findings)
6. [Low Priority Findings](#6-low-priority-findings)
7. [Orca/Accessibility Audit](#7-orcaaccessibility-audit)
8. [UX/Psychology Audit](#8-uxpsychology-audit)
9. [Architecture Analysis](#9-architecture-analysis)
10. [Security Audit](#10-security-audit)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Dynamic Dependency Resolution System](#12-dynamic-dependency-resolution-system)

---

## 1. File Inventory

### 1.1 Summary

| Metric | Value |
|--------|-------|
| Total Python files | 32 |
| Total lines of code | 10,488 |
| Files > 500 lines | 7 |
| Largest file | `core/builder.py` (2,985 lines) |
| Empty `__init__.py` files | 7 |

### 1.2 File Details

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | 29 | Entry point |
| **ui/** | | |
| `ui/app.py` | 74 | Adw.Application + CSS |
| `ui/window.py` | 1,166 | Main window – wizard NavigationView orchestration |
| `ui/pages.py` | 950 | Wizard pages (Welcome, Application, Configuration, Build) |
| `ui/dialogs.py` | 816 | Build progress, success, log, install, validation dialogs |
| `ui/widgets.py` | 162 | DynamicEntryList, DirectoryListWidget, DetectedFilesWidget |
| **core/** | | |
| `core/builder.py` | 2,985 | Build orchestration (god object) |
| `core/environment_manager.py` | 571 | Distrobox container management |
| `core/app_info.py` | 100 | AppInfo dataclass |
| `core/settings.py` | 51 | JSON settings persistence |
| `core/structure_analyzer.py` | 230 | App type detection & wrapper analysis |
| **templates/** | | |
| `templates/app_templates.py` | 328 | Per-type templates (Python, Java, Qt, GTK, etc.) |
| `templates/base.py` | 24 | Abstract AppTemplate base |
| **generators/** | | |
| `generators/files.py` | 275 | Desktop file, AppRun, launcher generation |
| `generators/icons.py` | 162 | Icon processing, SVG conversion, fallback |
| **validators/** | | |
| `validators/validators.py` | 102 | Input validation functions |
| **utils/** | | |
| `utils/i18n.py` | 29 | gettext configuration |
| `utils/system.py` | 107 | System info, distro detection, sanitization |
| `utils/file_ops.py` | 155 | File copy, download, directory scan |
| **updater/** | | |
| `updater/update_window.py` | 846 | GTK4 update notification UI |
| `updater/checker.py` | 267 | GitHub Releases API checker |
| `updater/downloader.py` | 245 | AppImage download + install |
| `updater/check_updates.py` | 150 | Periodic update checking |
| `updater/__init__.py` | 8 | Module init + __version__ |
| **standalone scripts** | | |
| `integration_helper.py` | 545 | Desktop integration, systemd watcher |
| `appimage-cleanup.py` | 290 | Orphaned integration cleanup |
| **`__init__.py` (empty)** | 0 × 7 | core, generators, templates, ui, utils, validators, updater locale |

---

## 2. Automated Analysis Summary

### 2.1 Ruff Linter — 77 issues

| Rule | Count | Description |
|------|-------|-------------|
| F401 | 23 | Unused imports |
| E402 | 22 | Module-level import not at top of file |
| F541 | 14 | f-string without any placeholders |
| E722 | 12 | Bare `except:` clause |
| F841 | 4 | Unused local variables |
| F811 | 1 | Redefinition of unused name |
| E741 | 1 | Ambiguous variable name |

### 2.2 Ruff Formatter

- **25 of 32 files** need reformatting

### 2.3 Mypy — 27 errors in 6 files

| File | Errors | Key issues |
|------|--------|------------|
| `core/environment_manager.py` | 8 | `union-attr` errors on subprocess result |
| `updater/checker.py` | 5 | `no-redef`, type narrowing |
| `updater/downloader.py` | 4 | `no-redef`, optional access |
| `updater/update_window.py` | 4 | `no-redef`, missing attribute |
| `updater/check_updates.py` | 3 | Assignment type conflicts |
| `integration_helper.py` | 3 | Type narrowing issues |

### 2.4 Vulture (Dead Code) — 28 items

- Unused signal handler params: `btn`, `param`, `args`, `widget` (expected for GTK signals)
- Unused imports: `Gdk`, `GLib`, `Gio` in several files
- Unused variables in callbacks
- Unused method `_on_environment_removed` in `window.py`

### 2.5 Radon (Cyclomatic Complexity) — 27 functions ≥ C grade

| Function | Grade | Score | File |
|----------|-------|-------|------|
| `_setup_python_environment` | **F** | 55 | `core/builder.py` |
| `_create_icon_symlinks` | **F** | 50 | `core/builder.py` |
| `_generate_detailed_structure` | **F** | 46 | `ui/window.py` |
| `_bundle_external_binaries` | **E** | 31 | `core/builder.py` |
| `build` | **D** | 26 | `core/builder.py` |
| `analyze_wrapper_script` | **D** | 26 | `core/structure_analyzer.py` |
| `setup_systemd_watcher` | **D** | 25 | `integration_helper.py` |
| `main` | **D** | 24 | `integration_helper.py` |
| `_copy_papirus_symbolic_icons` | **D** | 22 | `core/builder.py` |
| `_ensure_native_dependencies` | **D** | 20 | `core/builder.py` |
| `_copy_symbolic_icons` | **C** | 18 | `core/builder.py` |
| `_copy_typelibs` | **C** | 15 | `core/builder.py` |
| `copy_dependencies` | **C** | 14 | `core/builder.py` |
| +14 more at C grade | **C** | 11-14 | various |

### 2.6 Tech Debt Markers

- **Zero** TODO, FIXME, HACK, or XXX markers found in the codebase

---

## 3. Critical Findings

### 3.1 CRIT-01: Zero Orca/Screen Reader Accessibility

**Impact:** Blind or low-vision users CANNOT use this application at all.
**Scope:** ALL interactive widgets across ALL UI files.

No calls to:
- `widget.set_accessible_name()`
- `widget.set_accessible_description()`
- `widget.update_property()` with `Gtk.AccessibleProperty`
- `widget.update_relation()` with `Gtk.AccessibleRelation`
- `widget.update_state()` with `Gtk.AccessibleState`

**Affected widgets (exhaustive list):**

| File | Widget | Orca impact |
|------|--------|-------------|
| `window.py` | `Adw.EntryRow` (Quick Setup name) | No label announced |
| `window.py` | `Gtk.Button` (browse executable) | "Button" only |
| `window.py` | `Gtk.Button` (browse icon) | "Button" only |
| `window.py` | `Gtk.Button` (Quick Build) | No purpose announced |
| `window.py` | `Gtk.MenuButton` (hamburger) | No label |
| `window.py` | `Adw.PreferencesWindow` (all rows) | Missing descriptions |
| `pages.py` | `Adw.EntryRow` × 5 (name, version, desc, exec, desktop) | No accessible labels |
| `pages.py` | `Adw.ComboRow` × 2 (category, app type) | Items not described |
| `pages.py` | `Adw.SwitchRow` × 4 (terminal, auto-update, strip, icon) | State not announced semantically |
| `pages.py` | `Gtk.Button` × 4 (browse buttons) | "Button" only |
| `dialogs.py` | `Vte.Terminal` (build progress) | No accessible name/description |
| `dialogs.py` | `Gtk.ProgressBar` | Progress value not announced |
| `dialogs.py` | `Adw.StatusPage` × 3 (success, error, info) | Description may not be read |
| `widgets.py` | `DynamicEntryList` entries | No context announced |
| `widgets.py` | `DirectoryListWidget` rows | Listed items not described |
| `update_window.py` | All buttons (Update, Skip, Later) | Minimal context |
| `update_window.py` | Progress bars | Not announced |
| `update_window.py` | `Adw.ActionRow` (app update rows) | Missing accessible relations |

### 3.2 CRIT-02: No Test Suite

- **Zero** test files exist in the entire project
- No unit tests for validators, generators, templates, or utils
- No integration tests for the build pipeline
- No UI tests (not even smoke tests)
- No CI/CD testing pipeline

### 3.3 CRIT-03: Debug `input()` Call Left in Production Code

**File:** `core/builder.py`, method `build_appimage()` (around line 2815)

```python
input("⏸️  Press ENTER to continue and cleanup temp files...")
```

This **halts execution** waiting for stdin when a build fails. In a GUI application, this blocks the builder thread indefinitely with no way for the user to respond, effectively **freezing the application**.

---

## 4. High Priority Findings

### 4.1 HIGH-01: 12 Bare `except:` Clauses

Bare `except:` catches `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`, making debugging extremely difficult and potentially hiding critical failures.

**Locations:** Distributed across `builder.py`, `dialogs.py`, `window.py`, `pages.py`, `file_ops.py`.

**Fix:** Replace each with `except Exception:` at minimum, or specific exception types where identifiable.

### 4.2 HIGH-02: God Object — `builder.py` (2,985 lines)

`AppImageBuilder` class contains ~30 methods covering:
- Python environment setup (venv, pip, stdlib)
- System library copying (ldd, readelf)
- Typelib management
- GStreamer plugin handling
- Icon symlink creation
- Binary dependency detection
- External tool download (appimagetool, linuxdeploy)
- Build orchestration

This violates Single Responsibility Principle massively. Methods have inter-dependencies via `self.app_info`, `self.build_dir`, `self.container_name`.

### 4.3 HIGH-03: Two F-Grade Complexity Functions

`_setup_python_environment` (F=55) and `_create_icon_symlinks` (F=50) are nearly untestable in their current form. Both need decomposition into smaller, testable units.

### 4.4 HIGH-04: `window.py` Mixed Concerns (1,455 lines)

Business logic embedded in UI code:
- `_generate_detailed_structure()` (complexity F=46) — belongs in core/
- `_start_quick_build()` — build orchestration in UI class
- `_do_build()` — build parameter assembly in UI class
- Preferences window construction with business logic defaults

### 4.5 HIGH-05: Missing Type Annotations

Most public methods lack type hints. Critical for a 10K+ LOC project:
- `builder.py`: Most methods accept/return untyped `dict`
- `app_info` passed as a generic `dict` throughout — should be typed
- Signal handlers missing proper GTK type annotations
- Return types absent on most methods

---

## 5. Medium Priority Findings

### 5.1 MED-01: Shell Script Generation via String Interpolation

Multiple methods in `builder.py` generate bash scripts using f-strings with paths:
- `_use_system_pygobject()` — builds multi-line bash with f-string paths
- `_execute_library_copy()` — generates shell with `pattern` variable in f-string
- `_copy_typelibs()` — generates shell with search paths
- `_copy_gstreamer_plugins()` — generates shell for plugin copying
- `_copy_symbolic_icons()` — generates shell for icon copying
- `_copy_papirus_symbolic_icons()` — generates shell for icon theme copying
- `_copy_mpv_config()` — uses `bash -c` with inline script

While paths are controlled (not user input), this pattern is fragile and could break with paths containing special characters.

### 5.2 MED-02: No Download Integrity Verification

`download_appimagetool()` and `download_linuxdeploy()` download executables from GitHub without:
- Checksum (SHA256) verification
- GPG signature verification
- Certificate pinning

Downloads are executed with full permissions via `make_executable()`.

### 5.3 MED-03: Inconsistent Error Handling Strategy

| Pattern | Location | Behavior |
|---------|----------|----------|
| Return `bool` | `_use_system_pygobject()`, `download_linuxdeploy()` | Caller must check |
| Raise `RuntimeError` | `build()`, `_ensure_native_dependencies()` | Propagates up |
| Silent `pass` | Various bare except blocks | Error lost |
| `self.log()` + continue | `_copy_binary_libs()`, `_detect_binary_dependencies()` | Warning only |

No unified error strategy — some failures are silent, others crash the build.

### 5.4 MED-04: i18n Inconsistencies

- Debug/log messages mix translated `_("...")` and untranslated `f"..."` strings
- `self.log(f"[DEBUG] ...")` never translated (correct)
- `self.log(f"[linuxdeploy] {line}")` not translated (acceptable)
- Some user-facing `self.log()` messages not wrapped in `_()`
- `f-string` inside `_()` vs `_().format()` usage inconsistent

### 5.5 MED-05: `app_info` is a Raw `dict`

`app_info` is defined as a proper dataclass in `core/app_info.py` but is used as a raw dict (`self.app_info.get('key')`) throughout `builder.py`. The dataclass is essentially unused for the builder — defeating its purpose.

### 5.6 MED-06: Updater Module Isolation

The `updater/` module has:
- Its own i18n domain (`appimage-updater`)
- Its own `Adw.Application` class
- No shared infrastructure with the main app
- Duplicated patterns (window setup, CSS loading)

This could share more infrastructure with the main application.

---

## 6. Low Priority Findings

### 6.1 LOW-01: 23 Unused Imports

Identified by ruff (F401). These add noise and slow import time marginally.

### 6.2 LOW-02: 14 f-strings Without Placeholders

`f"literal string"` should be plain `"literal string"`.

### 6.3 LOW-03: 22 Module-Level Import Ordering Issues

Imports after non-import code (E402). Mostly in files that set up paths before importing.

### 6.4 LOW-04: Emoji in Log Messages

`self.log("⚠️ WARNING: ...")`, `self.log("✓ Python: ...")`, `self.log("✗ Build failed: ...")`

While visually useful in terminal, emojis may cause issues with:
- Log file parsing
- Some terminal emulators
- Orca screen reader announcement

### 6.5 LOW-05: Missing `__all__` in Modules

No module defines `__all__`, making public API unclear.

### 6.6 LOW-06: `SYSTEM_DEPENDENCIES` and `SYSTEM_BINARIES` Dicts in builder.py

These large configuration dictionaries (100+ lines each) belong in a separate config module, not mixed with business logic.

---

## 7. Orca/Accessibility Audit

### 7.1 Current State: **FAIL — Zero accessibility support**

GTK4 uses the `Gtk.Accessible` interface, which maps to AT-SPI2 (used by Orca). Every interactive widget should have:

1. **Accessible name** — What Orca announces when the widget receives focus
2. **Accessible description** — Additional context (optional but recommended)
3. **Accessible role** — Usually set automatically by GTK4 widget type
4. **Accessible state** — For toggle/switch widgets, current state
5. **Accessible relations** — For related widgets (label-for, described-by)

### 7.2 Required Fixes per File

#### `ui/window.py`
- [ ] All `Adw.EntryRow` in Quick Setup: `set_accessible_description()`
- [ ] Browse buttons: `update_property(Gtk.AccessibleProperty.LABEL, "Browse for executable")`
- [ ] Quick Build button: accessible name describing action
- [ ] Hamburger `Gtk.MenuButton`: `set_accessible_name(_("Main menu"))`
- [ ] All preferences rows: accessible descriptions
- [ ] Navigation view pages: accessible labels for page transitions

#### `ui/pages.py`
- [ ] `AppInfoPage`: All `Adw.EntryRow` need `set_accessible_description()`
- [ ] `FilesPage`: File chooser buttons need accessible labels
- [ ] `FilesPage`: `Adw.ComboRow` items need descriptive text
- [ ] `BuildPage`: Build button needs accessible description of action
- [ ] `BuildPage`: `Adw.SwitchRow` states need custom announcements
- [ ] `EnvironmentPage`: Container status rows need accessible state

#### `ui/dialogs.py`
- [ ] `Vte.Terminal`: `set_accessible_name(_("Build output terminal"))`
- [ ] `Gtk.ProgressBar`: Needs periodic accessible value updates
- [ ] `BuildSuccessDialog`: Actions need accessible descriptions
- [ ] Modal dialogs: Focus trap and Escape key handling verification
- [ ] File chooser dialogs: Accessible labels for each dialog

#### `ui/widgets.py`
- [ ] `DynamicEntryList`: Each entry needs contextual accessible name (e.g., "Package 1 of 3")
- [ ] `DirectoryListWidget`: Row descriptions for screen reader
- [ ] Add/Remove buttons: Accessible labels describing what is added/removed

#### `updater/update_window.py`
- [ ] `UpdateWindow`: Accessible name for the window
- [ ] Update/Skip/Later buttons: Accessible descriptions
- [ ] App rows: Accessible state (update available, downloading, complete)
- [ ] Progress bars: Live region announcements

### 7.3 Keyboard Navigation

Not explicitly verified but GTK4 provides baseline keyboard nav. Areas needing verification:
- [ ] Tab order through Quick Setup card
- [ ] Tab order through preferences pages
- [ ] Focus management after dialog open/close
- [ ] Escape key dismisses all dialogs
- [ ] Enter key activates focused buttons
- [ ] Arrow keys navigate combo box items

---

## 8. UX/Psychology Audit

### 8.1 Cognitive Load Analysis

#### Quick Setup Card (window.py)
- **Issue:** Three fields (name, executable, icon) + Quick Build button presented simultaneously
- **Hick's Law violation:** No progressive disclosure
- **Fix:** Step 1: Name → Step 2: Executable (auto-detect type) → Step 3: Icon (optional) → Build

#### Preferences Window (window.py)
- **Issue:** 4 tabs with many settings. User must understand all before building.
- **Miller's Law tension:** Too many options visible simultaneously on some tabs
- **Fix:** Group into essential vs. advanced, collapse advanced by default with `Adw.ExpanderRow`

#### Build Page (pages.py)
- **Issue:** Output directory, environment, dependencies, icon theme, strip option, build button all visible
- **Progressive disclosure missing:** New users see expert options immediately
- **Fix:** Show only output dir + build button. Reveal advanced options via expander.

#### Files Page (pages.py)
- **Issue:** Executable, app type, additional dirs, desktop file, icon, structure preview — 6+ distinct concepts
- **Fix:** Auto-detect as much as possible, show summary with "Edit" option

### 8.2 Feedback & Status

- **Build progress dialog:** Uses VTE terminal — effective but overwhelming for non-technical users
- **No in-line validation feedback:** Fields don't show errors until build attempt
- **Success dialog:** Well-designed with clear actions (Open folder, Open file, Build another)
- **Error dialog:** Shows raw error text — could be friendlier for common errors

### 8.3 Visual Hierarchy

- Custom CSS classes defined (`.error`, `.success`, `.accent`, `.card`) — good
- `AdwClamp` used for content width — good for readability
- `AdwStatusPage` used for empty states — follows HIG
- Icon usage in buttons is minimal — could improve scannability

---

## 9. Architecture Analysis

### 9.1 Current Architecture

```
main.py
  └── ui/app.py (Adw.Application)
        └── ui/window.py (Main Window + business logic mixed)
              ├── ui/pages.py (Page widgets)
              ├── ui/dialogs.py (Progress/Success/Error dialogs)
              ├── ui/widgets.py (Custom widget managers)
              └── core/builder.py (GOD OBJECT — 2985 lines)
                    ├── core/environment_manager.py
                    ├── core/structure_analyzer.py
                    ├── core/app_info.py
                    ├── templates/app_templates.py
                    ├── generators/files.py
                    ├── generators/icons.py
                    ├── utils/ (system, file_ops, i18n)
                    └── validators/validators.py

updater/ (semi-independent module)
  ├── update_window.py (own Adw.Application)
  ├── checker.py
  ├── downloader.py
  └── check_updates.py

Standalone scripts:
  ├── integration_helper.py
  └── appimage-cleanup.py
```

### 9.2 Recommended Architecture Decomposition

`core/builder.py` should be split into:

| New Module | Methods to Extract | Lines (est.) |
|------------|-------------------|--------------|
| `core/python_env.py` | `_setup_python_environment`, `_use_system_pygobject` | ~350 |
| `core/library_bundler.py` | `_copy_system_libraries`, `_execute_library_copy`, `_copy_binary_libs`, `_copy_typelibs` | ~300 |
| `core/plugin_bundler.py` | `_copy_gstreamer_plugins`, `_copy_mpv_config` | ~200 |
| `core/icon_manager.py` | `_create_icon_symlinks`, `_copy_symbolic_icons`, `_copy_papirus_symbolic_icons` | ~400 |
| `core/binary_bundler.py` | `_bundle_external_binaries`, `_detect_binary_dependencies`, `_copy_external_dependencies`, `_fix_wrapper_scripts` | ~300 |
| `core/dependency_detector.py` | `_detect_gui_dependencies`, `_detect_gi_usage`, `_ensure_native_dependencies` | ~250 |
| `core/tool_downloader.py` | `download_appimagetool`, `download_linuxdeploy` | ~100 |
| `core/build_config.py` | `SYSTEM_DEPENDENCIES`, `SYSTEM_BINARIES` dicts | ~200 |
| `core/builder.py` (remaining) | `build()`, `build_async()`, `cleanup()`, orchestration methods | ~500 |

`ui/window.py` should extract:
| Target | Methods/Logic | Lines (est.) |
|--------|---------------|--------------|
| `core/structure_formatter.py` | `_generate_detailed_structure()` | ~200 |
| `ui/preferences.py` | Preferences window construction | ~300 |
| `ui/quick_setup.py` | Quick Setup card logic | ~150 |

### 9.3 Dependency Flow Issues

- `app_info` is created as `AppInfo` dataclass but consumed as raw `dict` in builder
- `builder.py` imports `re` inside method bodies (should be module-level)
- Circular potential: `window.py` references `builder.py` and vice versa through callbacks

---

## 10. Security Audit

### 10.1 Findings

| ID | Severity | Description | File |
|----|----------|-------------|------|
| SEC-01 | **HIGH** | Debug `input()` blocks GUI thread on build failure | `core/builder.py` |
| SEC-02 | MEDIUM | Downloaded executables (appimagetool, linuxdeploy) not verified | `core/builder.py` |
| SEC-03 | MEDIUM | Shell scripts generated with f-string path interpolation | `core/builder.py` |
| SEC-04 | LOW | No HTTPS certificate pinning for GitHub downloads | `utils/file_ops.py` |
| SEC-05 | LOW | `subprocess.Popen` in `_bundle_external_binaries` without timeout on `wait()` | `core/builder.py` |
| SEC-06 | INFO | `subprocess.run` used throughout with command lists (good — no shell injection) | Multiple |
| SEC-07 | INFO | No use of `shell=True` in subprocess calls (good) | Multiple |

### 10.2 Positive Security Practices

- All `subprocess.run()` calls use list arguments (no shell injection)
- No `shell=True` usage
- No secrets or credentials in code
- File paths sanitized via `sanitize_filename()` in utils
- Build happens in isolated Distrobox containers

---

## 11. Implementation Roadmap

### Phase 1: Critical Safety (Week 1-2)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| ✅ Remove debug `input()` call | CRIT | 5 min | `core/builder.py` |
| ✅ Replace 12 bare `except:` with `except Exception:` | HIGH | 30 min | Multiple |
| ✅ Fix all 77 ruff lint issues | HIGH | 2 hrs | Multiple |
| ✅ Run `ruff format` on all 25 files | HIGH | 5 min | Multiple |
| ✅ Fix 27 mypy errors | HIGH | 2 hrs | 6 files |

### Phase 2: Accessibility — Orca Support (Week 2-3)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| Add accessible names to ALL buttons | CRIT | 2 hrs | `window.py`, `pages.py`, `dialogs.py`, `widgets.py` |
| Add accessible descriptions to all `EntryRow`/`ComboRow`/`SwitchRow` | CRIT | 2 hrs | `window.py`, `pages.py` |
| Add accessible name to VTE terminal | CRIT | 15 min | `dialogs.py` |
| Add accessible labels to progress bars | CRIT | 30 min | `dialogs.py`, `update_window.py` |
| Verify keyboard tab order on all pages | CRIT | 1 hr | All UI files |
| Add accessible names to updater widgets | CRIT | 1 hr | `update_window.py` |
| Test with Orca screen reader end-to-end | CRIT | 2 hrs | — |

### Phase 3: Architecture Refactor + Dynamic Dependencies (Week 3-5)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| ✅ **Fix imediato:** Trocar `libgirepository-1.0.so*` por `libgirepository-*.so*` | CRIT | 5 min | `core/builder.py` |
| ✅ Implementar auto-ldd recursivo em `copy_dependencies()` | HIGH | 3-4 hrs | `core/dependency_resolver.py` (novo) |
| ✅ Validação pré-packaging (ldd check + Python import test) | HIGH | 2-3 hrs | `core/dependency_resolver.py` |
| ✅ Extract `SYSTEM_DEPENDENCIES`/`SYSTEM_BINARIES` to `core/build_config.py` | HIGH | 30 min | `core/builder.py` |
| ✅ Extract `_setup_python_environment` + `_use_system_pygobject` to `core/python_env.py` | HIGH | 2 hrs | `core/builder.py` |
| ✅ Extract library/typelib copy methods to `core/library_bundler.py` | HIGH | 2 hrs | `core/builder.py` |
| ✅ Extract icon theme methods to `core/library_bundler.py` (merged) | HIGH | 2 hrs | `core/builder.py` |
| ✅ Extract binary bundling to `core/binary_bundler.py` | HIGH | 2 hrs | `core/builder.py` |
| ✅ Bugfix: Restaurar `download_linuxdeploy` + wrappers de delegação + `create_icon_symlinks` em `library_bundler.py` | CRIT | 1 hr | `core/builder.py`, `core/library_bundler.py` |
| ✅ Extract `_generate_detailed_structure` from `window.py` to `core/structure_formatter.py` | HIGH | 1 hr | `ui/window.py`, `core/structure_formatter.py` |
| ✅ Use `AppInfo` dataclass properly instead of raw dict | MED | 3 hrs | `core/app_info.py`, `core/builder.py`, `generators/files.py`, `templates/app_templates.py`, `core/python_env.py`, `core/library_bundler.py`, `core/binary_bundler.py`, `ui/window.py` |
| ✅ Add type annotations to all public methods | MED | 4 hrs | All files |

### Phase 4: Test Suite (Week 5-7)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| Set up pytest + pytest-cov | CRIT | 30 min | `pyproject.toml` |
| Unit tests for `validators/validators.py` | HIGH | 1 hr | New test file |
| Unit tests for `utils/system.py` | HIGH | 1 hr | New test file |
| Unit tests for `utils/file_ops.py` | HIGH | 1 hr | New test file |
| Unit tests for `core/app_info.py` | MED | 30 min | New test file |
| Unit tests for `core/structure_analyzer.py` | MED | 2 hrs | New test file |
| Unit tests for `generators/files.py` | MED | 2 hrs | New test file |
| Unit tests for `generators/icons.py` | MED | 2 hrs | New test file |
| Unit tests for `templates/app_templates.py` | MED | 2 hrs | New test file |
| Integration test for build pipeline (mock subprocess) | MED | 4 hrs | New test file |
| CI/CD with GitHub Actions for test running | MED | 1 hr | `.github/workflows/` |

### Phase 5: UX Improvements (Week 7-8)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| ✅ **Wizard UI refactor**: Migrou de Quick Setup + PreferencesWindow para wizard com `Adw.NavigationView` (Welcome → Application → Configuration → Build) | HIGH | 8 hrs | `ui/pages.py`, `ui/window.py` |
| ✅ Cada página com `Adw.HeaderBar` + botão voltar automático do NavigationView | HIGH | — | `ui/pages.py` |
| ✅ Gerenciamento de containers na WelcomePage (ExpanderRow colapsável) | HIGH | 1 hr | `ui/pages.py`, `ui/window.py` |
| ✅ Retorno automático à Welcome após build (sucesso/erro/cancelamento) | MED | 30 min | `ui/window.py` |
| ✅ Barra de título removida do BuildProgressDialog e BuildSuccessDialog | MED | 15 min | `ui/dialogs.py` |
| ✅ Menu hambúrguer (About) no header da WelcomePage | LOW | 15 min | `ui/window.py` |
| ✅ Removidos containers Debian 10 (Buster), Fedora 40 e Linux Mint 22 (redundante com Ubuntu 24.04) | LOW | 5 min | `core/environment_manager.py` |
| ✅ Tag "★ Recommended" no Ubuntu 24.04 LTS | LOW | 15 min | `core/environment_manager.py`, `ui/pages.py` |
| Add inline validation feedback to entry fields | MED | 2 hrs | `ui/pages.py`, `ui/window.py` |
| ✅ Validação inline com `validate_app_name`/`validate_version`, CSS error classes, bloqueio Config→Build | MED | — | `ui/window.py` |
| Friendlier error messages for common build failures | LOW | 2 hrs | `ui/dialogs.py` |
| ✅ `_friendly_error_message()` mapeia 12 padrões de erro para mensagens amigáveis com sugestões | LOW | — | `ui/window.py` |
| Add tooltips to all settings | LOW | 1 hr | `ui/pages.py`, `ui/window.py` |
| ✅ Tooltips adicionados em 15 widgets (EntryRow, SwitchRow, ComboRow, ActionRow) | LOW | — | `ui/pages.py` |
| ✅ Fix: Checkmarks duplicados (✓✓) nos System Requirements — `_set_row_icon` agora rastreia ícone via referência direta (`_status_icon`) | HIGH | — | `ui/pages.py` |
| ✅ Fix: Lista de containers não atualizava após remoção — `update_environments` agora rastreia rows em `_env_rows` para limpeza confiável | HIGH | — | `ui/pages.py` |
| ✅ Fix: Cancelamento real no setup de container — subprocess.terminate() ao clicar Cancel, verificação em 3 pontos (criação, init, deps) | HIGH | — | `core/environment_manager.py`, `ui/window.py` |
| ✅ Barra de título do WM removida no diálogo de setup/remoção de container (LogProgressDialog) — `set_decoration_layout("")` + botões Cancel/Close no HeaderBar | MED | — | `ui/dialogs.py` |

### Phase 6: Security Hardening (Week 8-9)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| ✅ Add SHA256 checksum verification for downloaded tools | MED | 2 hrs | `utils/file_ops.py`, `core/builder.py` |
| ✅ Add timeout to `subprocess.Popen.wait()` in `_bundle_external_binaries` | MED | 15 min | `core/binary_bundler.py`, `core/environment_manager.py` |
| ✅ Replace shell script generation with Python-native operations where possible | LOW | 4 hrs | `core/library_bundler.py` |
| ✅ Quote paths properly in generated shell scripts | LOW | 2 hrs | `core/builder.py`, `core/library_bundler.py`, `core/python_env.py` |

### Phase 7: Dynamic Dependencies — Extensibilidade (Week 9-10)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| ✅ Perfis de dependência JSON externos (substituir dict hardcoded) | MED | 4 hrs | `core/settings.py` (LibraryProfileManager) |
| ✅ UI "Additional Libraries" na página Build | MED | 2 hrs | `ui/pages.py` |
| UI "Detected Dependencies" com checkboxes | MED | 3 hrs | `ui/pages.py` |
| ✅ Diálogo de validação pré-packaging com warnings | MED | 2 hrs | `ui/dialogs.py` (ValidationWarningDialog) |
| Community profiles via GitHub (loader + docs) | LOW | 2 hrs | `core/build_config.py`, docs |

---

## 12. Dynamic Dependency Resolution System

### 12.1 Problema Atual

O `SYSTEM_DEPENDENCIES` em `builder.py` é um dicionário **estático e hardcoded** com padrões de bibliotecas fixos. Isso causa falhas em cenários reais:

- `libgirepository-1.0.so*` está no dict, mas sistemas mais novos usam `libgirepository-2.0.so.0` — AppImage falha com `ImportError: libgirepository-2.0.so.0: cannot open shared object file`
- Qualquer aplicação que use uma lib não catalogada no dict vai falhar silenciosamente
- Não há validação pós-build para detectar dependências faltantes
- Usuários não conseguem adicionar libs customizadas pela UI

**Caso real reportado:** Steam Pass (app PyGObject) falha ao rodar AppImage gerado com `ImportError: libgirepository-2.0.so.0` porque o builder só copia `libgirepository-1.0.so*`.

### 12.2 Solução Proposta: Resolução em 4 Camadas

#### Camada 1: Auto-ldd Recursivo (Core — Resolução Automática)

Após copiar todos os arquivos para o AppDir, executar varredura recursiva de dependências:

```
Algoritmo:
1. Listar todos os .so e executáveis no AppDir
2. Rodar `ldd` em cada um
3. Identificar libs "not found" ou apontando para paths do sistema
4. Copiar libs faltantes do container/host para usr/lib/
5. Repetir passos 2-4 até:
   - Nenhuma lib nova faltante encontrada, OU
   - Máximo de 3 iterações (evitar loop infinito)
6. Excluir libc/libpthread/libdl/ld-linux (devem vir do host)
```

**Nova classe proposta:** `core/dependency_resolver.py`

```python
class DependencyResolver:
    """Recursive ldd-based shared library resolver."""

    # Libraries that MUST come from the host system (never bundle)
    HOST_ONLY_LIBS = {
        'linux-vdso.so', 'ld-linux-x86-64.so', 'libc.so',
        'libpthread.so', 'libdl.so', 'librt.so', 'libm.so',
        'libresolv.so', 'libnss_', 'libthread_db.so',
    }

    def resolve(self, appdir: Path, max_iterations: int = 3) -> list[str]:
        """Resolve all missing shared libraries recursively."""
        ...

    def _scan_missing_libs(self, appdir: Path) -> set[str]:
        """Find all shared libs referenced but not present."""
        ...

    def _copy_lib_from_system(self, lib_name: str, dest: Path) -> bool:
        """Copy a specific library from system to AppDir."""
        ...
```

#### Camada 2: Perfis de Dependência Extensíveis (JSON/YAML)

Mover `SYSTEM_DEPENDENCIES` de dict hardcoded para arquivos de perfil externos:

```
~/.config/appimage-creator/profiles/
├── default.json          # Perfil padrão (shipped com a app)
├── pygi-gtk4.json        # Perfil para apps PyGObject/GTK4
├── qt5.json              # Perfil para apps Qt5
├── electron.json         # Perfil para apps Electron
└── custom/               # Perfis customizados do usuário
    └── steam-pass.json   # Exemplo: perfil específico para um app
```

**Formato proposto:**

```json
{
    "name": "PyGObject GTK4",
    "version": "1.0",
    "description": "Profile for Python/GTK4/Libadwaita applications",
    "dependencies": {
        "girepository": {
            "libs": ["libgirepository-*.so*"],
            "typelibs": ["GIRepository-*.typelib"],
            "required": true
        },
        "gtk4": {
            "libs": ["libgtk-4.so*", "libgraphene-1.0.so*"],
            "typelibs": ["Gtk-4.0.typelib", "Gdk-4.0.typelib", "Gsk-4.0.typelib"],
            "required": true
        }
    },
    "auto_detect_patterns": [
        "gi.require_version\\(['\"]Gtk['\"],\\s*['\"]4\\.0['\"]"
    ]
}
```

**Vantagem:** Padrões com wildcards (`libgirepository-*.so*`) cobrem tanto `1.0` quanto `2.0+`.

#### Camada 3: UI para Dependências Customizadas

Adicionar na página Build:

1. **"Additional Libraries" field** — Campo de texto onde o usuário pode adicionar padrões de biblioteca
   - Exemplo: `libgirepository-2.0.so* libcustom.so*`
   - Salvável como perfil para reutilização

2. **"Detected Dependencies" view** — Lista de dependências detectadas automaticamente com checkboxes
   - Mostra quais libs foram encontradas e quais estão faltando
   - Toggle para incluir/excluir cada lib

3. **"Validate" button** — Executa teste pré-packaging:
   - Roda `ldd` recursivo e mostra resultado
   - Tenta executar o main script do app para capturar ImportError
   - Mostra relatório de libs faltantes com sugestões

#### Camada 4: Validação Pré-Packaging

Antes de executar `appimagetool`, rodar validação automática:

```
Algoritmo:
1. Montar LD_LIBRARY_PATH apontando para AppDir/usr/lib/
2. Rodar ldd recursivo — listar todas as libs "not found"
3. Se app é Python: executar `python3 -c "import <main_module>"` 
   com PYTHONPATH do AppDir
4. Capturar ImportError/OSError para libs faltantes
5. Reportar ao usuário com indicação de qual lib adicionar
6. Permitir retry após correção
```

### 12.3 Fluxo Revisado de Build

```
┌──────────────────────────────────────────────┐
│ 1. Copy application files                     │
│ 2. Setup Python venv (if Python app)          │
│ 3. Copy known dependencies (profiles)         │
│ 4. Bundle external binaries (linuxdeploy)     │
│ 5. ★ AUTO-LDD RECURSIVE RESOLUTION ★         │ ← NOVO
│    → Scan all .so in AppDir                    │
│    → Copy missing libs from container          │
│    → Repeat until resolved                     │
│ 6. ★ PRE-PACKAGING VALIDATION ★              │ ← NOVO
│    → Verify all libs present                   │
│    → Test Python imports if applicable         │
│    → Report failures with suggestions          │
│ 7. Create AppImage (appimagetool)             │
└──────────────────────────────────────────────┘
```

### 12.4 Implementação Incremental

| Fase | O que | Esforço | Impacto |
|------|-------|---------|---------|
| **Fase A** | Auto-ldd recursivo no `copy_dependencies()` | 3-4 hrs | Resolve 80% dos casos (como o Steam Pass) |
| **Fase B** | Wildcard patterns em `SYSTEM_DEPENDENCIES` (ex: `libgirepository-*.so*`) | 1 hr | Fix imediato para libgirepository-2.0 |
| **Fase C** | Validação pré-packaging (ldd check + Python import test) | 2-3 hrs | Feedback antes de gerar AppImage quebrado |
| **Fase D** | Perfis JSON externos + UI para libs customizadas | 6-8 hrs | Extensibilidade completa |
| **Fase E** | Community profiles via GitHub | 2-3 hrs | Escalabilidade para novos apps |

### 12.5 Fix Imediato para o Caso Steam Pass

Enquanto o sistema dinâmico não está implementado, o fix mínimo é:

1. Trocar `'libgirepository-1.0.so*'` por `'libgirepository-*.so*'` no `SYSTEM_DEPENDENCIES['glib']`
2. Isso cobre `libgirepository-1.0.so.1` e `libgirepository-2.0.so.0`

---

## Appendix A: Tools Used

| Tool | Version | Purpose |
|------|---------|---------|
| ruff | latest | Linting + formatting |
| mypy | latest | Static type checking |
| vulture | latest | Dead code detection |
| radon | latest | Cyclomatic complexity analysis |
| grep | — | Tech debt marker search |
| Manual review | — | Full read of all 32 files |

## Appendix B: Files NOT Modified

As specified in the audit constraint, **zero files were modified**. This document is the sole deliverable.
