#!/usr/bin/env python3
"""
Test GTK4 and UI components without running the full app.
"""
import sys

try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk
    print("✓ GTK4 is properly installed")
    print(f"  GTK Version: {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}.{Gtk.MICRO_VERSION}")
except ImportError as e:
    print(f"✗ GTK4 import failed: {e}")
    sys.exit(1)

# Try importing the models
try:
    from models import Message, MessageRole, Conversation, ConversationSettings
    print("✓ Models imported successfully")
except ImportError as e:
    print(f"✗ Models import failed: {e}")
    sys.exit(1)

# Try importing UI components (without aiohttp requirement)
try:
    from ui.components import (
        MessageBubble,
        TypingIndicator,
        ChatInput,
        ChatArea,
        Sidebar,
        SettingsPanel,
    )
    print("✓ UI Components imported successfully")
except ImportError as e:
    print(f"✗ UI Components import failed: {e}")
    sys.exit(1)

print()
print("✓ All UI dependencies are satisfied!")
print()
print("To run the full application, install aiohttp:")
print("  pip install aiohttp")
print()
print("Then run:")
print("  python main.py")
