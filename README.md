# AppImage Creator

A modern GTK4/Libadwaita application for creating AppImages from any type of Linux application. Supports Python, Qt, GTK, Java, binary applications, and complex wrapper scripts.

## Features

- **Modern Interface**: Built with GTK4 and Libadwaita for a native GNOME experience
- **Multi-Language Support**: Handles Python, Java, Shell scripts, Qt, GTK, Electron, and binary applications
- **Smart Detection**: Automatically detects application type and structure
- **Wrapper Script Analysis**: Advanced analysis of wrapper scripts (like those created by package managers)
- **Auto-Discovery**: Finds related files like locale data, icons, and desktop files
- **Template System**: Flexible launcher templates for different application types
- **Icon Processing**: Automatic icon conversion and resizing with fallback generation
- **Progress Tracking**: Real-time build progress with detailed logging
- **Structure Preview**: Preview AppImage contents before building

## Installation

### System Requirements

- Python 3.8+
- GTK 4.0+
- Libadwaita 1.0+
- PyGObject 3.42+

### Install Dependencies

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adwaita-1 \
                 python3-pip librsvg2-bin imagemagick
```

#### Fedora
```bash
sudo dnf install python3-gobject gtk4-devel libadwaita-devel \
                 python3-pip librsvg2-tools ImageMagick
```

#### Arch Linux
```bash
sudo pacman -S python-gobject gtk4 libadwaita python-pip \
               librsvg imagemagick
```

### Install Python Dependencies
```bash
pip3 install -r requirements.txt
```

### Optional Tools (for better icon processing)
- `rsvg-convert` (usually in librsvg2-bin package)
- `ImageMagick` (imagemagick package)  
- `Inkscape` (inkscape package)

## Usage

### Running the Application
```bash
python3 main.py
```

### Quick Start

1. **Enter Application Name**: Provide a name for your application
2. **Select Executable**: Choose the main executable file or script
3. **Choose Icon** (optional): Select an icon file (PNG, SVG, etc.)
4. **Advanced Settings** (optional): Configure authors, categories, and additional files
5. **Create AppImage**: Click the build button to generate your AppImage

### Advanced Configuration

#### Application Types
The application automatically detects and supports:

- **Binary**: Compiled executables
- **Python**: Python scripts and applications
- **Python Wrapper**: Complex Python apps with wrapper scripts
- **Shell Script**: Bash/shell script applications
- **Java**: JAR files and Java applications
- **Qt**: Qt-based applications (Qt5/Qt6)
- **GTK**: GTK-based applications (GTK3/GTK4)
- **Electron**: Electron-based applications

#### Additional Directories
You can include additional directories containing:
- Locale files (`/usr/share/locale`)
- Plugin directories
- Data files
- Configuration templates
- Documentation

#### Auto-Detection
The application automatically finds and includes:
- Desktop files (`.desktop`)
- Icon files in standard locations
- Locale/translation files
- Related application data

## Project Structure

```
AppImageCreator/
├── main.py                 # Application entry point
├── window.py              # Main window and UI
├── appimage_builder.py    # Core AppImage building logic
├── app_templates.py       # Application templates and launchers
├── utils.py               # Utility functions
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## How It Works

1. **Analysis Phase**: Analyzes the selected executable to determine type and structure
2. **Structure Building**: Creates standard AppDir structure with appropriate directories
3. **File Copying**: Copies application files, dependencies, and resources
4. **Template Generation**: Creates launcher scripts based on application type
5. **Icon Processing**: Processes and converts icons to required formats
6. **Desktop Integration**: Generates .desktop files for system integration
7. **AppImage Creation**: Uses appimagetool to build the final AppImage

## Template System

The application uses a template system to generate appropriate launcher scripts:

- **PythonAppTemplate**: For standalone Python applications
- **PythonWrapperAppTemplate**: For complex Python apps with wrappers
- **BinaryAppTemplate**: For compiled binary applications
- **JavaAppTemplate**: For Java JAR applications
- **ShellAppTemplate**: For shell script applications
- **QtAppTemplate**: For Qt applications with proper environment setup
- **GtkAppTemplate**: For GTK applications with schema and typelib setup
- **ElectronAppTemplate**: For Electron applications

## Troubleshooting

### Common Issues

1. **"appimagetool not found"**: The application automatically downloads appimagetool if not available
2. **Permission denied**: Ensure the selected executable has execute permissions
3. **Missing dependencies**: Install system packages listed in requirements
4. **Icon processing fails**: Install optional icon tools (rsvg-convert, ImageMagick)

### Debug Mode
Run with verbose output:
```bash
python3 main.py --debug
```

### Build Logs
Check the console output for detailed build information and error messages.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- GTK and GNOME teams for the excellent toolkit and design system
- AppImage project for the portable application format
- All contributors and testers

## Version History

- **1.0.0**: Initial release with basic AppImage creation
- **1.1.0**: Added wrapper script analysis and auto-detection
- **1.2.0**: Enhanced UI with Libadwaita and structure preview
- **Current**: Advanced template system and comprehensive application support