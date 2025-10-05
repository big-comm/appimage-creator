"""
Icon processing and generation
"""

import os
import shutil
import subprocess
from pathlib import Path
from utils.i18n import _

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print(_("Warning: PIL/Pillow not available, icon processing will be limited"))


def process_icon(icon_path, output_dir, app_name):
    """Process and convert icon to required formats"""
    if not icon_path or not os.path.exists(icon_path):
        return generate_default_icon(output_dir, app_name)
    
    icon_formats = {
        'svg': f"{app_name}.svg",
        'png_256': f"{app_name}.png",
        'png_scalable': f"{app_name}.svg"
    }
    
    processed_icons = {}
    output_dir = Path(output_dir)
    
    try:
        path = Path(icon_path)
        
        if path.suffix.lower() == '.svg':
            # Copy SVG directly
            svg_path = output_dir / icon_formats['svg']
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(icon_path, svg_path)
            processed_icons['svg'] = svg_path
            processed_icons['png_scalable'] = svg_path
            
            # Convert SVG to PNG if possible
            try:
                png_path = output_dir / icon_formats['png_256']
                if convert_svg_to_png(icon_path, png_path, 256):
                    processed_icons['png_256'] = png_path
                else:
                    processed_icons['png_256'] = svg_path
            except Exception:
                processed_icons['png_256'] = svg_path
                
        else:
            # Handle raster images
            if HAS_PIL:
                try:
                    with Image.open(icon_path) as img:
                        png_path = output_dir / icon_formats['png_256']
                        png_path.parent.mkdir(parents=True, exist_ok=True)
                        img_resized = img.resize((256, 256), Image.Resampling.LANCZOS)
                        img_resized.save(png_path, 'PNG')
                        processed_icons['png_256'] = png_path
                        processed_icons['svg'] = png_path
                        processed_icons['png_scalable'] = png_path
                except Exception:
                    png_path = output_dir / icon_formats['png_256']
                    png_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(icon_path, png_path)
                    processed_icons['png_256'] = png_path
                    processed_icons['svg'] = png_path
                    processed_icons['png_scalable'] = png_path
            else:
                png_path = output_dir / icon_formats['png_256']
                png_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(icon_path, png_path)
                processed_icons['png_256'] = png_path
                processed_icons['svg'] = png_path
                processed_icons['png_scalable'] = png_path
                
    except Exception as e:
        print(_("Error processing icon: {}").format(e))
        return generate_default_icon(output_dir, app_name)
    
    return processed_icons


def convert_svg_to_png(svg_path, png_path, size):
    """Convert SVG to PNG using available tools"""
    # Try rsvg-convert
    try:
        subprocess.run([
            'rsvg-convert', '-w', str(size), '-h', str(size),
            '-o', str(png_path), str(svg_path)
        ], check=True, capture_output=True, timeout=30)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Try ImageMagick
    try:
        subprocess.run([
            'convert', '-background', 'transparent',
            '-resize', f'{size}x{size}',
            str(svg_path), str(png_path)
        ], check=True, capture_output=True, timeout=30)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Try inkscape
    try:
        subprocess.run([
            'inkscape', '--export-type=png', f'--export-width={size}', f'--export-height={size}',
            f'--export-filename={png_path}', str(svg_path)
        ], check=True, capture_output=True, timeout=30)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    return False


def generate_default_icon(output_dir, app_name):
    """Generate a default SVG icon"""
    svg_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="256" height="256" viewBox="0 0 256 256" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#3584e4"/>
      <stop offset="50%" style="stop-color:#1c71d8"/>
      <stop offset="100%" style="stop-color:#1a5fb4"/>
    </linearGradient>
  </defs>
  <rect width="256" height="256" fill="url(#bg)" rx="24"/>
  
  <rect x="64" y="64" width="128" height="128" fill="none" stroke="white" 
        stroke-width="8" rx="16" opacity="0.8"/>
  <rect x="80" y="80" width="32" height="32" fill="white" rx="4" opacity="0.9"/>
  <rect x="128" y="80" width="48" height="16" fill="white" rx="2" opacity="0.7"/>
  <rect x="128" y="104" width="48" height="16" fill="white" rx="2" opacity="0.7"/>
  <rect x="80" y="128" width="96" height="8" fill="white" rx="1" opacity="0.5"/>
  <rect x="80" y="144" width="96" height="8" fill="white" rx="1" opacity="0.5"/>
  <rect x="80" y="160" width="64" height="8" fill="white" rx="1" opacity="0.5"/>
  
  <text x="128" y="220" text-anchor="middle" fill="white" font-size="16" 
        font-family="sans-serif" font-weight="bold" opacity="0.9">
    {app_name[:12]}
  </text>
</svg>'''
    
    output_dir = Path(output_dir)
    svg_path = output_dir / f"{app_name}.svg"
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg_content)
    
    return {
        'svg': svg_path,
        'png_256': svg_path,
        'png_scalable': svg_path
    }