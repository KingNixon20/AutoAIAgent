"""
Message bubble widget for displaying chat messages.
"""
from datetime import datetime
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, Gdk

from models import Message, MessageRole
import constants as C


class MessageBubble(Gtk.Box):
    """A message bubble widget displaying a single message."""

    def __init__(self, message: Message):
        """Initialize the message bubble.
        
        Args:
            message: The message to display.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.message = message
        # AI left, user right; width = half of typical chat area
        is_assistant = message.role == MessageRole.ASSISTANT
        self.set_halign(Gtk.Align.START if is_assistant else Gtk.Align.END)
        self.set_hexpand(False)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Main bubble container - half width (225px), expand vertically
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bubble.set_margin_start(14)
        bubble.set_margin_end(14)
        bubble.set_margin_top(10)
        bubble.set_margin_bottom(10)
        bubble.set_size_request(C.CHAT_MAX_WIDTH // 2, -1)  # Half of chat width
        
        # Message text - use formatted view for assistant, plain label for user
        if is_assistant:
            from ui.markdown_renderer import (
                build_formatted_text_view,
                split_thinking_and_response,
            )
            thinking, response = split_thinking_and_response(message.content)
            # Thinking section (collapsible, ChatGPT/DeepSeek style)
            if thinking:
                thinking_box = self._build_thinking_section(thinking)
                bubble.pack_start(thinking_box, False, False, 0)
            # Response section - expand vertically, no scrolling
            text_widget = build_formatted_text_view(response if response else message.content)
            bubble.pack_start(text_widget, True, True, 0)
        else:
            escaped = (
                message.content.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            text_label = Gtk.Label(label=message.content, wrap=True)
            text_label.set_selectable(True)
            text_label.set_justify(Gtk.Justification.LEFT)
            text_label.set_line_wrap(True)
            text_label.set_markup(f"<span size='13000'>{escaped}</span>")
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
        bubble.set_hexpand(False)
        
        # Show all children
        self.show_all()
        
        # Add animation class
        # Animation handled by GTK3 rendering

    def _build_thinking_section(self, thinking_text: str) -> Gtk.Box:
        """Build collapsible thinking section (ChatGPT/DeepSeek style)."""
        from ui.markdown_renderer import build_formatted_text_view

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("thinking-section")

        # Header row: "Thinking" + toggle
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_bottom(6)

        expand_btn = Gtk.Button()
        expand_btn.set_relief(Gtk.ReliefStyle.NONE)
        expand_icon = Gtk.Image.new_from_icon_name(
            "pan-down-symbolic", Gtk.IconSize.BUTTON
        )
        expand_btn.set_image(expand_icon)
        expand_btn.get_style_context().add_class("thinking-toggle")

        header_label = Gtk.Label(label="Thinking")
        header_label.set_halign(Gtk.Align.START)
        header_label.set_markup(
            '<span size="10500" foreground="#808080" weight="600">Thinking</span>'
        )
        header.pack_start(expand_btn, False, False, 0)
        header.pack_start(header_label, False, False, 0)
        header.pack_start(Gtk.Box(), True, True, 0)

        outer.pack_start(header, False, False, 0)

        # Content (initially collapsed)
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_box.get_style_context().add_class("thinking-content")

        thinking_view = build_formatted_text_view(thinking_text)
        thinking_view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.7, 0.7, 0.7, 1))
        content_box.pack_start(thinking_view, True, True, 0)

        revealer = Gtk.Revealer()
        revealer.set_reveal_child(False)
        revealer.add(content_box)

        def toggle(btn):
            revealer.set_reveal_child(not revealer.get_reveal_child())
            icon_name = (
                "pan-up-symbolic" if revealer.get_reveal_child() else "pan-down-symbolic"
            )
            expand_btn.set_image(
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            )

        expand_btn.connect("clicked", toggle)

        outer.pack_start(revealer, False, False, 0)

        return outer


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
