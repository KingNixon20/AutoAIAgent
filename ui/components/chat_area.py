"""
Chat message display area widget.
"""
import gi
from datetime import datetime, timedelta

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from models import Message, Conversation
from ui.components.message_bubble import MessageBubble, TypingIndicator


class ChatArea(Gtk.Box):
    """Displays chat messages in a scrollable area."""

    def __init__(self):
        """Initialize the chat area."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Chat header
        self.header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.header_box.set_size_request(-1, 70)
        self.header_box.set_margin_start(20)
        self.header_box.set_margin_end(20)
        self.header_box.set_margin_top(14)
        self.header_box.set_margin_bottom(14)
        
        title_label = Gtk.Label(label="New Conversation")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_markup("<span font='bold' size='14500'>New Conversation</span>")
        title_label.set_margin_bottom(4)
        self.header_box.add(title_label)
        
        subtitle_label = Gtk.Label(label="")
        subtitle_label.set_halign(Gtk.Align.START)
        subtitle_label.set_markup("<span size='10000' foreground='#808080'>Loading...</span>")
        self.header_box.add(subtitle_label)
        
        self._title_label = title_label
        self._subtitle_label = subtitle_label
        
        self.add(self.header_box)
        
        # Messages container with scrolling
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        
        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.messages_box.set_homogeneous(False)
        self.messages_box.set_hexpand(True)
        self.messages_box.set_size_request(400, -1)  # Min width to prevent shrinking
        
        scrolled.add(self.messages_box)
        self.add(scrolled)
        
        self.scrolled = scrolled
        self._last_date = None
        self._typing_shown = False

    def set_conversation(self, conversation: Conversation) -> None:
        """Set the active conversation and display its messages.
        
        Args:
            conversation: The conversation to display.
        """
        # Clear existing messages
        for child in list(self.messages_box.get_children()):
            self.messages_box.remove(child)
        self._typing_shown = False
        if hasattr(self, "_typing_indicator_widget"):
            del self._typing_indicator_widget
        
        # Update header
        self._title_label.set_label(conversation.title)
        self._subtitle_label.set_label(f"Model: {conversation.model}")
        
        # Add messages
        self._last_date = None
        for message in conversation.messages:
            self.add_message(message, animate=False)
        
        # Auto scroll to bottom
        self._scroll_to_bottom()

    def add_message(self, message: Message, animate: bool = True) -> None:
        """Add a message to the display.
        
        Args:
            message: The message to add.
            animate: Whether to animate the message appearance.
        """
        # Add date separator if needed
        current_date = message.timestamp.date()
        if self._last_date != current_date:
            self._add_date_separator(current_date)
            self._last_date = current_date
        
        # Create and add message bubble
        bubble = MessageBubble(message)
        self.messages_box.add(bubble)
        bubble.show_all()  # Make sure message bubble is visible
        
        # Auto scroll to bottom
        GLib.idle_add(self._scroll_to_bottom)

    def show_typing_indicator(self) -> None:
        """Show the typing indicator."""
        if not self._typing_shown:
            indicator = TypingIndicator()
            self._typing_indicator_widget = indicator
            self.messages_box.add(indicator)
            self._typing_shown = True
            GLib.idle_add(self._scroll_to_bottom)

    def hide_typing_indicator(self) -> None:
        """Hide the typing indicator."""
        if self._typing_shown and hasattr(self, "_typing_indicator_widget"):
            self.messages_box.remove(self._typing_indicator_widget)
            del self._typing_indicator_widget
        self._typing_shown = False

    def clear(self) -> None:
        """Clear all messages from the display."""
        for child in list(self.messages_box.get_children()):
            self.messages_box.remove(child)
        self._last_date = None
        self._typing_shown = False
        if hasattr(self, "_typing_indicator_widget"):
            del self._typing_indicator_widget

    def _add_date_separator(self, date) -> None:
        """Add a date separator to the display.
        
        Args:
            date: The date to display in the separator.
        """
        separator_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        separator_box.set_homogeneous(False)
        
        # Line before
        line1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        line1.set_hexpand(True)
        separator_box.add(line1)
        
        # Date text
        date_str = date.strftime("%b %d, %Y")
        date_label = Gtk.Label(label=date_str)
        separator_box.add(date_label)
        
        # Line after
        line2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        line2.set_hexpand(True)
        separator_box.add(line2)
        
        self.messages_box.add(separator_box)

    def _scroll_to_bottom(self) -> bool:
        """Scroll to the bottom of the messages.
        
        Returns:
            False to prevent further idle calls.
        """
        adj = self.scrolled.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False
