"""
Message bubble widget for displaying chat messages.
"""
from datetime import datetime
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio

from models import Message, MessageRole


class MessageBubble(Gtk.Box):
    """A message bubble widget displaying a single message."""

    def __init__(self, message: Message):
        """Initialize the message bubble.
        
        Args:
            message: The message to display.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.message = message
        self.set_halign(Gtk.Align.START if message.role == MessageRole.USER else Gtk.Align.START)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Main bubble container
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bubble.set_margin_start(14)
        bubble.set_margin_end(14)
        bubble.set_margin_top(10)
        bubble.set_margin_bottom(10)
        
        # Message text
        text_label = Gtk.Label(label=message.content, wrap=True)
        text_label.set_selectable(True)
        text_label.set_justify(Gtk.Justification.LEFT)
        text_label.set_line_wrap(True)
        text_label.set_markup(f"<span size='13000'>{message.content}</span>")
        bubble.pack_start(text_label, True, True, 0)
        
        # Timestamp
        timestamp_str = message.timestamp.strftime("%H:%M")
        timestamp = Gtk.Label(label=timestamp_str)
        timestamp.set_markup(f"<span size='9000' foreground='#808080'>{timestamp_str}</span>")
        bubble.pack_end(timestamp, False, False, 0)
        
        # Apply role-based styling
        style_class = "user-bubble" if message.role == MessageRole.USER else "assistant-bubble"
        bubble.get_style_context().add_class(style_class)
        
        self.add(bubble)
        
        # Show all children
        self.show_all()
        
        # Add animation class
        # Animation handled by GTK3 rendering


class TypingIndicator(Gtk.Box):
    """Animated typing indicator widget."""

    def __init__(self):
        """Initialize the typing indicator."""
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # Create three dots
        for _ in range(3):
            dot = Gtk.Box()
            dot.set_size_request(8, 8)
            self.add(dot)
