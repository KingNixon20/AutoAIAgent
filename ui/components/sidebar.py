"""
Sidebar widget for conversation list and navigation.
"""
import gi
from typing import Callable, Optional

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from models import Conversation


class ConversationItem(Gtk.Box):
    """A single conversation item in the sidebar."""

    def __init__(self, conversation: Conversation, on_select: Callable[[Conversation], None]):
        """Initialize the conversation item.
        
        Args:
            conversation: The conversation to display.
            on_select: Callback when the item is selected.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.conversation = conversation
        self.set_size_request(-1, 56)
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(3)
        self.set_margin_bottom(3)
        
        # Title
        title = Gtk.Label(label=conversation.title)
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(True)
        title.set_markup(f"<span font='11500' weight='600'>{conversation.title}</span>")
        title.set_margin_start(10)
        title.set_margin_end(10)
        title.set_margin_top(8)
        self.add(title)
        
        # Timestamp
        timestamp_str = conversation.updated_at.strftime("%a %H:%M")
        subtitle = Gtk.Label(label=timestamp_str)
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_ellipsize(True)
        subtitle.set_markup(f"<span size='9500' foreground='#808080'>{timestamp_str}</span>")
        subtitle.set_margin_start(10)
        subtitle.set_margin_end(10)
        subtitle.set_margin_bottom(6)
        self.add(subtitle)
        
        # Make clickable
        self.connect("button-press-event", lambda _, event: on_select(conversation) or False)
        self.show_all()  # Ensure all children are visible

    def set_active(self, active: bool) -> None:
        """Set the active state of the item.
        
        Args:
            active: Whether the item should be highlighted as active.
        """
        # In GTK3, simple styling is applied via CSS
        # We'll keep the data internally but skip adding CSS classes
        self.active = active


class Sidebar(Gtk.Box):
    """Left sidebar containing conversation list and controls."""

    def __init__(self):
        """Initialize the sidebar."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(240, -1)
        
        # Header with logo/app name
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.set_size_request(-1, 50)
        header.set_margin_start(14)
        header.set_margin_end(14)
        header.set_margin_top(14)
        header.set_margin_bottom(14)
        
        icon = Gtk.Label(label="🤖")
        icon_attrs = Gtk.Label()
        icon.set_markup('<span font="24">🤖</span>')
        header.add(icon)
        
        app_name = Gtk.Label(label="AutoAI")
        app_name.set_markup('<span font="bold" size="14500">AutoAI</span>')
        app_name.set_halign(Gtk.Align.START)
        header.pack_start(app_name, True, True, 0)
        
        sep = Gtk.Separator()
        self.add(header)
        self.add(sep)
        
        # Search bar
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        search_box.set_margin_start(12)
        search_box.set_margin_end(12)
        search_box.set_margin_top(12)
        search_box.set_margin_bottom(8)
        search_box.set_size_request(-1, 36)
        
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search conversations...")
        self.search_entry.set_margin_start(0)
        self.search_entry.set_margin_end(0)
        search_box.pack_start(self.search_entry, True, True, 0)
        
        self.add(search_box)
        
        # New chat button
        self.new_chat_button = Gtk.Button(label="+ New Chat")
        self.new_chat_button.set_margin_start(12)
        self.new_chat_button.set_margin_end(12)
        self.new_chat_button.set_margin_top(4)
        self.new_chat_button.set_margin_bottom(12)
        self.new_chat_button.set_size_request(-1, 40)
        self.new_chat_button.get_style_context().add_class("primary")
        self.add(self.new_chat_button)
        
        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(sep)
        
        # Conversation list (scrollable)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_margin_top(4)
        scrolled.set_margin_bottom(4)
        
        self.conversations_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.conversations_box.set_margin_start(0)
        self.conversations_box.set_margin_end(0)
        scrolled.add(self.conversations_box)
        self.add(scrolled)
        
        # Footer with settings and status
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer.set_margin_start(12)
        footer.set_margin_end(12)
        footer.set_margin_top(12)
        footer.set_margin_bottom(12)
        footer.set_size_request(-1, 52)
        
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        footer.add(sep2)
        
        footer_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        settings_btn = Gtk.Button()
        settings_icon = Gtk.Image.new_from_icon_name("system-run-symbolic", Gtk.IconSize.BUTTON)
        settings_btn.set_image(settings_icon)
        footer_controls.add(settings_btn)
        
        status = Gtk.Label(label="Connected")
        footer_controls.add(status)
        
        footer.add(footer_controls)
        self.add(footer)
        
        self._conversations = {}
        self._current_active = None
        self.on_conversation_selected = None

    def add_conversation(self, conversation: Conversation) -> None:
        """Add a conversation to the list.
        
        Args:
            conversation: The conversation to add.
        """
        item = ConversationItem(conversation, self._on_conversation_selected)
        self.conversations_box.add(item)
        item.show_all()  # Show the conversation item after adding it
        self._conversations[conversation.id] = (item, conversation)

    def remove_conversation(self, conversation_id: str) -> None:
        """Remove a conversation from the list.
        
        Args:
            conversation_id: ID of the conversation to remove.
        """
        if conversation_id in self._conversations:
            item, _ = self._conversations[conversation_id]
            self.conversations_box.remove(item)
            del self._conversations[conversation_id]

    def set_active_conversation(self, conversation_id: str) -> None:
        """Set a conversation as active/selected.
        
        Args:
            conversation_id: ID of the conversation to activate.
        """
        if self._current_active:
            old_id, old_item = self._current_active
            old_item.set_active(False)
        
        if conversation_id in self._conversations:
            item, conversation = self._conversations[conversation_id]
            item.set_active(True)
            self._current_active = (conversation_id, item)

    def _on_conversation_selected(self, conversation: Conversation) -> None:
        """Handle conversation selection.
        
        Args:
            conversation: The selected conversation.
        """
        self.set_active_conversation(conversation.id)
        if self.on_conversation_selected:
            self.on_conversation_selected(conversation)

    def get_conversations(self) -> list[Conversation]:
        """Get all conversations in the sidebar.
        
        Returns:
            List of conversations.
        """
        return [conv for _, conv in self._conversations.values()]
