#!/usr/bin/env python3
"""
AutoAIAgent - Premium GTK3 AI Chat Client

A beautiful, dark-themed desktop application for chatting with locally running LM Studio.
"""
import sys
import asyncio
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk

from ui.main_window import MainWindow
import constants as C


class AutoAIApplication(Gtk.Application):
    """Main GTK Application class."""

    def __init__(self):
        """Initialize the application."""
        super().__init__(
            application_id="com.autoai.ChatClient",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.connect("activate", self._on_activate)
        self.window = None

    def _on_activate(self, app):
        """Handle application activation.
        
        Args:
            app: The Gtk.Application instance.
        """
        if self.window is None:
            self.window = MainWindow(self)
        
        self.window.present()
        
        # Schedule async initialization on GTK's main loop
        GLib.idle_add(self._initialize_async)

    def _initialize_async(self):
        """Initialize async components on GTK's main loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.window.initialize_async())
        except Exception as e:
            print(f"Async initialization error: {e}")
        finally:
            loop.close()
        return False  # Don't reschedule


def main():
    """Main entry point."""
    app = AutoAIApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
