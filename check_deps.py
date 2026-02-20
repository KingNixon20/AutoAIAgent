#!/usr/bin/env python3
"""
Dependency checker for AutoAIAgent.
Verifies all required packages are installed.
"""
import sys
import importlib


def check_dependency(module_name: str, package_name: str = None) -> bool:
    """Check if a module is installed.
    
    Args:
        module_name: Name of the module to import
        package_name: Display name (defaults to module_name)
    
    Returns:
        True if installed, False otherwise
    """
    package_name = package_name or module_name
    try:
        importlib.import_module(module_name)
        print(f"✓ {package_name} is installed")
        return True
    except ImportError as e:
        print(f"✗ {package_name} is NOT installed")
        print(f"  Error: {e}")
        return False


def main():
    """Check all dependencies."""
    print("AutoAIAgent Dependency Checker")
    print("=" * 50)
    print()
    
    required = [
        ("models", "Models (built-in)"),
        ("ui", "UI Components (built-in)"),
        ("api", "API Client (built-in)"),
        ("constants", "Constants (built-in)"),
    ]
    
    optional = [
        ("gi", "PyGObject (GTK4 bindings)"),
        ("aiohttp", "aiohttp (async HTTP)"),
        ("requests", "requests (HTTP)"),
    ]
    
    print("REQUIRED (Built-in):")
    print("-" * 50)
    all_required_ok = True
    for module, display_name in required:
        if not check_dependency(module, display_name):
            all_required_ok = False
    print()
    
    print("OPTIONAL (External):")
    print("-" * 50)
    all_optional_ok = True
    for module, display_name in optional:
        if not check_dependency(module, display_name):
            all_optional_ok = False
    print()
    
    print("=" * 50)
    print("INSTALLATION INSTRUCTIONS")
    print("=" * 50)
    print()
    print("For Ubuntu/Debian:")
    print("  sudo apt-get install libgtk-4-dev libgobject-introspection-dev")
    print("  sudo apt-get install libcairo2-dev")
    print("  pip install -r requirements.txt")
    print()
    print("For Fedora/RHEL:")
    print("  sudo dnf install gtk4-devel gobject-introspection-devel cairo-devel")
    print("  pip install -r requirements.txt")
    print()
    print("For macOS:")
    print("  brew install gtk4 gobject-introspection cairo")
    print("  pip install -r requirements.txt")
    print()
    
    if not all_required_ok:
        print("ERROR: Required dependencies missing!")
        return 1
    
    print("All required dependencies are available!")
    print()
    
    if not all_optional_ok:
        print("WARNING: Some optional dependencies missing.")
        print("The app will not work fully without GTK4 (PyGObject)")
        print()
    
    if check_dependency("gi", "PyGObject"):
        print("✓ GTK4 is available - you can run: python main.py")
    else:
        print("✗ GTK4 (PyGObject) not installed")
        print("  Install system dependencies and try again")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
