#This project is the product of a single overcaffinated sleep deprived dev
#!/usr/bin/env python3
"""
AutoAIAgent - Premium GTK3 AI Chat Client

A beautiful, dark-themed desktop application for chatting with locally running LM Studio.
"""
import gi
gi.require_version("Gtk", "3.0") # Request GTK 3.0 first

import logging
import sys
import asyncio
import threading # Added import

import os

# Optional backend override for debugging:
# AUTOAI_FORCE_X11=1 python3 main.py
if os.environ.get("AUTOAI_FORCE_X11") == "1":
    os.environ["GDK_BACKEND"] = "x11"

# Configure logging to terminal
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from ui.main_window import MainWindow
import constants as C

from gi.repository import Gtk, Gio, GLib, Gdk, GObject # Import Gtk, Gio, GLib, Gdk, GObject

# Initialize GObject threading early for GTK3 thread safety with background threads.
GObject.threads_init()

# No explicit asyncio.set_event_loop or loop creation here.
# Asyncio will be managed in a separate thread.


class AsyncioThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = None
        self.started = threading.Event()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        logger.info("Asyncio event loop started in separate thread.")
        self.started.set()
        self.loop.run_forever()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.join(timeout=5) # Wait for the thread to finish
            if self.loop.is_running():
                logger.warning("Asyncio thread did not stop gracefully.")
            logger.info("Asyncio event loop stopped.")

# Global instance of the asyncio thread
asyncio_thread = AsyncioThread()

class AutoAIApplication(Gtk.Application):
    """Main GTK Application class."""

    def __init__(self):
        """Initialize the application."""
        super().__init__(
            application_id="com.autoai.ChatClient",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown) # Connect shutdown signal
        self.window = None

        # Start the asyncio thread
        global asyncio_thread
        asyncio_thread.start()
        asyncio_thread.started.wait(timeout=5) # Wait for the loop to start
        logger.debug("Asyncio thread started and loop is ready.")

    def _on_shutdown(self, app):
        """Handle application shutdown."""
        logger.debug("AutoAIApplication shutdown initiated.")
        global asyncio_thread
        asyncio_thread.stop()
        logger.debug("Asyncio thread stopped.")

    def _on_activate(self, app):
        """Handle application activation.
        
        Args:
            app: The Gtk.Application instance.
        """
        if self.window is None:
            global asyncio_thread
            self.window = MainWindow(self, asyncio_thread)
        
        self.window.present()
        
        # Schedule async initialization on GTK's main loop
        GLib.idle_add(self._initialize_async)

    def _initialize_async(self):
        """Initialize async components on GTK's main loop."""
        # Submit the _async_init coroutine to the asyncio event loop in the separate thread.
        global asyncio_thread
        if asyncio_thread.loop and asyncio_thread.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.window._async_init(), asyncio_thread.loop)
        else:
            logger.error("Asyncio loop not running in separate thread.")
        return False  # Don't reschedule
    


def main():
    """Main entry point."""
    app = AutoAIApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
