"""
Custom widgets for AppImage Creator UI
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from utils.i18n import _


class DynamicEntryList:
    """Manages a list of entry rows (for authors, websites, etc)"""
    
    def __init__(self, list_box, title_format, allow_empty=False):
        self.list_box = list_box
        self.title_format = title_format
        self.allow_empty = allow_empty
        self.entries = []
        
    def add_entry(self, initial_text=""):
        """Add a new entry field"""
        row = Adw.EntryRow()
        row.set_title(self.title_format.format(len(self.entries) + 1))
        row.set_text(initial_text)
        
        # Remove button (not for first entry if not allow_empty)
        if len(self.entries) > 0 or self.allow_empty:
            remove_button = Gtk.Button.new_from_icon_name("edit-delete-symbolic")
            remove_button.set_valign(Gtk.Align.CENTER)
            remove_button.set_tooltip_text(_("Remove"))
            remove_button.add_css_class("destructive-action")
            remove_button.connect("clicked", lambda btn: self.remove_entry(row))
            row.add_suffix(remove_button)
        
        self.entries.append(row)
        self.list_box.append(row)
        return row
        
    def remove_entry(self, row):
        """Remove an entry field"""
        if row in self.entries:
            self.entries.remove(row)
            self.list_box.remove(row)
            self._update_titles()
            
    def _update_titles(self):
        """Update entry titles after removal"""
        for i, entry in enumerate(self.entries):
            entry.set_title(self.title_format.format(i + 1))
            
    def get_values(self):
        """Get all non-empty values"""
        return [entry.get_text().strip() for entry in self.entries 
                if entry.get_text().strip()]
    
    def clear(self):
        """Clear all entries"""
        for entry in list(self.entries):
            self.list_box.remove(entry)
        self.entries.clear()


class DirectoryListWidget:
    """Manages a list of directories"""
    
    def __init__(self, list_box, on_remove_callback=None):
        self.list_box = list_box
        self.directories = []
        self.on_remove_callback = on_remove_callback
        
    def add_directory(self, path):
        """Add directory to list"""
        import os
        if path not in self.directories:
            self.directories.append(path)
            self._refresh_list()
            
    def remove_directory(self, path):
        """Remove directory from list"""
        if path in self.directories:
            self.directories.remove(path)
            self._refresh_list()
            if self.on_remove_callback:
                self.on_remove_callback(path)
            
    def _refresh_list(self):
        """Refresh the list display"""
        import os
        # Clear existing rows
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child
            
        # Add current directories
        for directory in self.directories:
            row = Adw.ActionRow()
            row.set_title(os.path.basename(directory))
            row.set_subtitle(directory)
            
            remove_button = Gtk.Button(label=_("Remove"))
            remove_button.set_valign(Gtk.Align.CENTER)
            remove_button.add_css_class("destructive-action")
            remove_button.connect("clicked", lambda btn, path=directory: self.remove_directory(path))
            row.add_suffix(remove_button)
            
            self.list_box.append(row)
            
    def get_directories(self):
        """Get list of directories"""
        return self.directories.copy()
    
    def clear(self):
        """Clear all directories"""
        self.directories.clear()
        self._refresh_list()


class DetectedFilesWidget:
    """Widget to display auto-detected files"""
    
    def __init__(self, list_box):
        self.list_box = list_box
        
    def update(self, detected_files):
        """Update with detected files"""
        # Clear existing
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child
        
        # Filter out desktop files (they have their own section)
        filtered_files = {k: v for k, v in detected_files.items() if k != 'desktop_files'}
        
        # Add detected files
        import os
        for file_type, files in filtered_files.items():
            if files:
                for file_path in files:
                    row = Adw.ActionRow()
                    row.set_title(os.path.basename(file_path))
                    row.set_subtitle(_("{}: {}").format(
                        file_type.replace('_', ' ').title(), 
                        file_path
                    ))
                    
                    icon = Gtk.Image.new_from_icon_name("emblem-default-symbolic")
                    row.add_prefix(icon)
                    
                    self.list_box.append(row)
                    
    def clear(self):
        """Clear all displayed files"""
        child = self.list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child