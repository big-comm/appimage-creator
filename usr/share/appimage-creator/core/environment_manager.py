"""
Manages build environments using Distrobox
"""

import subprocess
import shutil
from typing import List, Dict, Any, Optional, Callable

from utils.system import get_distro_info, check_host_dependencies
from utils.i18n import _


# Define the supported build environments
# We can easily add more here in the future
SUPPORTED_ENVIRONMENTS = [
    # Ubuntu versions (latest first, then LTS versions)
    {
        'id': 'linuxmint-22',
        'name': 'Linux Mint 22 (Wilma)',
        'image': 'ubuntu:24.04',
        'description': _('Optimized for Linux Mint users - based on Ubuntu 24.04 LTS.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'python3-gi', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 'gir1.2-glib-2.0',
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    {
        'id': 'ubuntu-24.04',
        'name': 'Ubuntu 24.04 LTS',
        'image': 'ubuntu:24.04',
        'description': _('Latest Ubuntu LTS with newest packages.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'python3-gi', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 'gir1.2-glib-2.0',
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    {
        'id': 'ubuntu-22.04',
        'name': 'Ubuntu 22.04 LTS',
        'image': 'ubuntu:22.04',
        'description': _('Good balance of compatibility and modern packages.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'python3-gi', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 'gir1.2-glib-2.0',
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    {
        'id': 'ubuntu-20.04',
        'name': 'Ubuntu 20.04 LTS',
        'image': 'ubuntu:20.04',
        'description': _('Excellent compatibility for older systems.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    
    # Debian versions
    {
        'id': 'debian-12',
        'name': 'Debian 12 (Bookworm)',
        'image': 'debian:12',
        'description': _('Latest Debian stable - very reliable.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    {
        'id': 'debian-11',
        'name': 'Debian 11 (Bullseye)',
        'image': 'debian:11',
        'description': _('Previous Debian stable - proven stability.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    {
        'id': 'debian-10',
        'name': 'Debian 10 (Buster)',
        'image': 'debian:10',
        'description': _('Older Debian for maximum compatibility.'),
        'build_deps': ['python3', 'python3-venv', 'python3-dev', 'build-essential', 
                    'pkg-config', 'libcairo2-dev', 'libgirepository1.0-dev', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'vainfo', 'gstreamer1.0-gtk3'],
        'package_manager': 'apt',
    },
    
    # Red Hat based distributions (latest first)
    {
        'id': 'fedora-41',
        'name': 'Fedora 41',
        'image': 'fedora:41',
        'description': _('Latest Fedora with cutting-edge packages and GTK4/VTE support.'),
        'build_deps': ['python3', 'python3-devel', 'gcc', 'gcc-c++', 'make', 
                    'pkg-config', 'cairo-devel', 'gobject-introspection-devel', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'libva-utils', 'gstreamer1.0-plugins-good-gtk'],
        'package_manager': 'dnf',
    },
    {
        'id': 'fedora-40',
        'name': 'Fedora 40',
        'image': 'fedora:40',
        'description': _('Stable Fedora release.'),
        'build_deps': ['python3', 'python3-devel', 'gcc', 'gcc-c++', 'make', 
                    'pkg-config', 'cairo-devel', 'gobject-introspection-devel', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'libva-utils', 'gstreamer1.0-plugins-good-gtk'],
        'package_manager': 'dnf',
    },
    {
        'id': 'almalinux-9',
        'name': 'AlmaLinux 9',
        'image': 'almalinux:9',
        'description': _('RHEL 9 compatible - enterprise-grade stability.'),
        'build_deps': ['epel-release', 'python3', 'python3-devel', 'gcc', 'gcc-c++', 'make', 
                    'pkg-config', 'cairo-devel', 'gobject-introspection-devel', 
                    'git', 'binutils', 'file', 'papirus-icon-theme', 'libva-utils', 'gstreamer1.0-plugins-good-gtk'],
        'package_manager': 'dnf',
    },
    # Example of an older, highly compatible environment (might need different deps)
    # {
    #     'id': 'centos-7',
    #     'name': 'CentOS 7',
    #     'image': 'centos:7',
    #     'description': _('Maximum compatibility (very old glibc).'),
    #     'build_deps': ['python3', 'git', 'binutils'],
    #     'package_manager': 'yum',
    # },
]


class EnvironmentManager:
    """Handles detection, creation, and interaction with build environments."""

    def __init__(self):
        self.host_distro = get_distro_info()
        self.host_deps = check_host_dependencies(['podman', 'docker', 'distrobox'])
        self._distrobox_containers = self._list_distrobox_containers()
        
    def check_container_runtime(self) -> Optional[str]:
        """Check which container runtime is installed (docker or podman)."""
        if shutil.which('docker'):
            # Verify docker is actually working
            try:
                subprocess.run(['docker', 'ps'], 
                             capture_output=True, 
                             timeout=5)
                return 'docker'
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                pass
        
        if shutil.which('podman'):
            return 'podman'
        
        return None

    def get_missing_components(self) -> Dict[str, Any]:
        """Get information about missing components and what needs to be installed."""
        has_distrobox = self.host_deps.get('distrobox', False)
        runtime = self.check_container_runtime()
        
        missing = {
            'distrobox': not has_distrobox,
            'runtime': runtime is None,
            'runtime_name': 'podman' if runtime is None else runtime,
            'needs_installation': not has_distrobox or runtime is None
        }
        
        return missing

    def get_install_command(self) -> Optional[Dict[str, Any]]:
        """Get the installation command for the current distribution."""
        missing = self.get_missing_components()
        
        if not missing['needs_installation']:
            return None
        
        distro_base = self.host_distro.get('base')
        distro_id = self.host_distro.get('id')
        
        packages = []
        if missing['distrobox']:
            packages.append('distrobox')
        if missing['runtime']:
            packages.append('podman')
        
        # Arch-based distributions
        if distro_base == 'arch' or distro_id in ['arch', 'manjaro', 'endeavouros']:
            return {
                'method': 'pacman',
                'command': ['pkexec', 'pacman', '-S', '--noconfirm'] + packages,
                'display': f"pkexec pacman -S --noconfirm {' '.join(packages)}",
                'packages': packages
            }
        
        # Debian/Ubuntu-based distributions
        elif distro_base == 'debian' or distro_id in ['debian', 'ubuntu', 'linuxmint', 'pop']:
            return {
                'method': 'apt',
                'command': ['pkexec', 'apt-get', 'install', '-y'] + packages,
                'display': f"pkexec apt-get install -y {' '.join(packages)}",
                'packages': packages,
                'pre_command': ['pkexec', 'apt-get', 'update']
            }
        
        # Fedora/RHEL-based distributions
        elif distro_base == 'rpm' or distro_id in ['fedora', 'centos', 'rhel', 'nobara']:
            return {
                'method': 'dnf',
                'command': ['pkexec', 'dnf', 'install', '-y'] + packages,
                'display': f"pkexec dnf install -y {' '.join(packages)}",
                'packages': packages
            }
        
        return None

    def is_host_ready(self) -> bool:
        """Check if the host has the necessary tools (distrobox and a container runtime)."""
        has_runtime = self.host_deps.get('podman', False) or self.host_deps.get('docker', False)
        return self.host_deps.get('distrobox', False) and has_runtime

    def get_host_status(self) -> Dict[str, Any]:
        """Get a detailed status of the host environment."""
        runtime = self.check_container_runtime()
        missing = self.get_missing_components()
        
        return {
            'distro_id': self.host_distro.get('id', 'Unknown'),
            'distro_base': self.host_distro.get('base', 'unknown'),
            'has_podman': self.host_deps.get('podman', False),
            'has_docker': self.host_deps.get('docker', False),
            'has_distrobox': self.host_deps.get('distrobox', False),
            'container_runtime': runtime,
            'missing_components': missing,
            'is_ready': self.is_host_ready(),
        }

    def get_supported_environments(self) -> List[Dict[str, Any]]:
        """Return the list of supported environments with their current status."""
        environments_with_status = []
        for env_spec in SUPPORTED_ENVIRONMENTS:
            env_info = env_spec.copy()
            container_name = self._get_container_name(env_spec['id'])
            
            if container_name in self._distrobox_containers:
                # For now, we just check for existence. Later, we can check if deps are installed.
                env_info['status'] = 'ready'
            else:
                env_info['status'] = 'not_installed'
            
            env_info['container_name'] = container_name
            environments_with_status.append(env_info)
            
        return environments_with_status
    
    def create_environment(self, env_id: str, log_callback: Optional[Callable[[str], None]] = None):
        """Creates a new distrobox container for the given environment ID."""
        if not self.is_host_ready():
            raise RuntimeError(_("Host is not set up for Distrobox (missing dependencies)."))

        env_spec = next((env for env in SUPPORTED_ENVIRONMENTS if env['id'] == env_id), None)
        if not env_spec:
            raise ValueError(f"Environment ID '{env_id}' not found.")

        container_name = self._get_container_name(env_id)
        
        # Refresh list to get current state
        self._distrobox_containers = self._list_distrobox_containers()
        
        if container_name in self._distrobox_containers:
            if log_callback:
                log_callback(_("Environment '{}' already exists.").format(env_spec['name']))
            return

        cmd = [
            'distrobox-create',
            '--name', container_name,
            '--image', env_spec['image'],
            '--yes' # Automatically answer yes to prompts
        ]

        try:
            if log_callback:
                log_callback(_("Creating environment '{}'... This may take a while.").format(env_spec['name']))
                log_callback(f"$ {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output to the log callback
            if log_callback:
                for line in iter(process.stdout.readline, ''):
                    log_callback(line.strip())
            
            process.stdout.close()
            return_code = process.wait()

            if return_code != 0:
                raise RuntimeError(_("Failed to create environment. Distrobox exited with code {}.").format(return_code))
            
            # Refresh the list of containers
            self._distrobox_containers = self._list_distrobox_containers()
            
            # Initialize the container by entering it for the first time
            # This creates the user, sets up sudo, groups, etc.
            if log_callback:
                log_callback("")
                log_callback(_("Initializing container (creating user and environment)..."))
                log_callback(_("First-time setup may take 5-10 minutes on slow connections..."))
                log_callback(_("Please be patient - this is a one-time process."))
            
            init_cmd = [
                'distrobox-enter',
                container_name,
                '--',
                '/bin/bash', '-c', 'echo "Container initialized: $(whoami)@$(hostname)"'
            ]
            
            try:
                init_process = subprocess.Popen(
                    init_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                # Stream initialization output
                if log_callback:
                    for line in iter(init_process.stdout.readline, ''):
                        line = line.strip()
                        if line:
                            log_callback(line)
                
                init_process.stdout.close()
                init_return_code = init_process.wait()
                
                if init_return_code != 0:
                    if log_callback:
                        log_callback(_("Warning: Container initialization completed with issues"))
                else:
                    if log_callback:
                        log_callback("")
                        log_callback(_("Container initialization complete!"))
                        
            except Exception:
                if log_callback:
                    log_callback(_("Warning: Failed to initialize container automatically"))
                    log_callback(_("You may need to run: distrobox-enter {}").format(container_name))
            
            if log_callback:
                log_callback(_("Environment created successfully!"))

        except FileNotFoundError:
            raise RuntimeError(_("distrobox-create command not found."))
        except Exception as e:
            # Re-raise with more context
            raise RuntimeError(_("An error occurred while creating the environment: {}").format(e))

    def setup_environment_dependencies(self, env_id: str, log_callback: Optional[Callable[[str], None]] = None):
        """Installs the necessary build dependencies inside a distrobox container."""
        if not self.is_host_ready():
            raise RuntimeError(_("Host is not set up for Distrobox."))

        env_spec = next((env for env in SUPPORTED_ENVIRONMENTS if env['id'] == env_id), None)
        if not env_spec:
            raise ValueError(f"Environment ID '{env_id}' not found.")

        container_name = self._get_container_name(env_id)
        
        # Refresh container list to ensure we have latest state
        self._distrobox_containers = self._list_distrobox_containers()
        
        if container_name not in self._distrobox_containers:
            if log_callback:
                log_callback(_("Waiting for container to be fully ready..."))
            # Wait a bit and try again
            import time
            time.sleep(2)
            self._distrobox_containers = self._list_distrobox_containers()
            
            if container_name not in self._distrobox_containers:
                raise RuntimeError(_("Container '{}' was created but is not accessible. Try again in a moment.").format(container_name))

        # Build the installation command based on the package manager
        pm = env_spec['package_manager']
        deps_str = " ".join(env_spec['build_deps'])

        if pm == 'apt':
            install_cmd = f"sudo apt-get update && sudo apt-get install -y {deps_str}"
        elif pm == 'yum':
            install_cmd = f"sudo yum install -y {deps_str}"
        elif pm == 'dnf':
            # Check if it's AlmaLinux/RHEL - need to enable CRB repo first
            if 'almalinux' in env_id or 'rhel' in env_id:
                install_cmd = f"sudo dnf install -y epel-release && sudo crb enable && sudo dnf install -y {deps_str}"
            else:
                install_cmd = f"sudo dnf install -y {deps_str}"
        elif pm == 'pacman':
            install_cmd = f"sudo pacman -Sy --noconfirm {deps_str}"
        else:
            raise NotImplementedError(f"Package manager '{pm}' is not supported.")

        cmd = [
            'distrobox-enter',
            container_name,
            '--',
            'sh', '-c', install_cmd # Use sh -c to execute the full command string
        ]

        try:
            if log_callback:
                log_callback(_("Installing dependencies in '{}'...").format(env_spec['name']))
                log_callback(f"$ distrobox-enter {container_name} -- '{install_cmd}'")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            if log_callback:
                for line in iter(process.stdout.readline, ''):
                    log_callback(line.strip())
            
            process.stdout.close()
            return_code = process.wait()

            if return_code != 0:
                raise RuntimeError(_("Failed to install dependencies. Process exited with code {}.").format(return_code))

            if log_callback:
                log_callback(_("Dependencies installed successfully!"))
            
            # Here we could add a mechanism to mark the container as "fully ready"
            # For now, we assume success means it's ready.

        except Exception as e:
            raise RuntimeError(_("An error occurred while installing dependencies: {}").format(e))
        
    def remove_environment(self, env_id: str, log_callback: Optional[Callable[[str], None]] = None):
        """Remove a distrobox container environment and associated images."""
        if not self.is_host_ready():
            raise RuntimeError(_("Host is not set up for Distrobox."))
        
        env_spec = next((env for env in SUPPORTED_ENVIRONMENTS if env['id'] == env_id), None)
        if not env_spec:
            raise ValueError(f"Environment ID '{env_id}' not found.")
        
        container_name = self._get_container_name(env_id)
        image_name = env_spec['image']
        
        # Refresh container list
        self._distrobox_containers = self._list_distrobox_containers()
        
        if container_name not in self._distrobox_containers:
            if log_callback:
                log_callback(_("Container '{}' does not exist.").format(container_name))
            return
        
        # Step 1: Remove container
        cmd = ['distrobox-rm', container_name, '--force']
        
        try:
            if log_callback:
                log_callback(_("Removing container '{}'...").format(container_name))
                log_callback(f"$ {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            if log_callback:
                for line in iter(process.stdout.readline, ''):
                    log_callback(line.strip())
            
            process.stdout.close()
            return_code = process.wait()
            
            if return_code != 0:
                raise RuntimeError(_("Failed to remove container."))
            
            # Refresh container list
            self._distrobox_containers = self._list_distrobox_containers()
            
            if log_callback:
                log_callback(_("Container removed successfully!"))
                
            # Refresh container list
            self._distrobox_containers = self._list_distrobox_containers()
            
            # Step 2: Remove the Docker/Podman image to free disk space
            if log_callback:
                log_callback("")
                log_callback(_("Removing container image to free disk space..."))
            
            runtime = self.check_container_runtime()
            if runtime:
                rm_image_cmd = [runtime, 'rmi', image_name, '--force']
                try:
                    img_result = subprocess.run(
                        rm_image_cmd,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if img_result.returncode == 0:
                        if log_callback:
                            log_callback(_("Image removed successfully"))
                    else:
                        if log_callback:
                            log_callback(_("Note: Image may still be in use by other containers"))
                except Exception:
                    if log_callback:
                        log_callback(_("Warning: Could not remove image automatically"))
            
            if log_callback:
                log_callback(_("Container removed successfully!"))
                
        except Exception as e:
            raise RuntimeError(_("An error occurred while removing the container: {}").format(e))

    def _get_container_name(self, env_id: str) -> str:
        """Generate a consistent container name for our app."""
        return f"appimage-creator-{env_id}"

    def _list_distrobox_containers(self) -> List[str]:
        """Get a list of existing distrobox containers by name."""
        if not self.host_deps.get('distrobox'):
            return []
        
        try:
            result = subprocess.run(
                ['distrobox', 'list', '--no-color'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return []
            
            # The output is a table with columns: ID | NAME | STATUS | IMAGE
            lines = result.stdout.strip().split('\n')
            if len(lines) < 2:
                return []

            # Skip header line
            container_names = []
            for line in lines[1:]:
                # Split by pipe separator
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    # NAME is the second column (index 1)
                    name = parts[1].strip()
                    if name:
                        container_names.append(name)

            return container_names
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []