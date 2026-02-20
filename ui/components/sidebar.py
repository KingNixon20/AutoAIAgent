"""
Sidebar widget for conversation list and navigation.
"""
import gi
from typing import Callable, Optional

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Pango

from models import Conversation


class ConversationItem(Gtk.EventBox):
    """A single conversation item in the sidebar - compact single row."""

    def __init__(
        self,
        conversation: Conversation,
        on_select: Callable[[Conversation], None],
        on_delete: Optional[Callable[[Conversation], None]] = None,
    ):
        """Initialize the conversation item.
        
        Args:
            conversation: The conversation to display.
            on_select: Callback when the item is selected.
            on_delete: Callback when delete is requested.
        """
        super().__init__()
        self.get_style_context().add_class("conversation-item")
        self.conversation = conversation
        
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_size_request(-1, 32)
        row.set_margin_start(4)
        row.set_margin_end(4)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        
        # Title - expands, ellipsizes when long
        title = Gtk.Label(label=conversation.title)
        title.set_halign(Gtk.Align.START)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_markup(f"<span size='10500' weight='600'>{conversation.title}</span>")
        title.set_margin_start(10)
        title.set_margin_end(4)
        title.set_margin_top(6)
        title.set_margin_bottom(6)
        row.pack_start(title, True, True, 0)
        
        # Timestamp - fixed width, no shrink
        timestamp_str = conversation.updated_at.strftime("%H:%M")
        subtitle = Gtk.Label(label=timestamp_str)
        subtitle.set_halign(Gtk.Align.END)
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle.set_markup(f"<span size='9000' foreground='#808080'>{timestamp_str}</span>")
        subtitle.set_margin_end(4)
        subtitle.set_margin_top(6)
        subtitle.set_margin_bottom(6)
        row.pack_end(subtitle, False, False, 0)
        
        # Delete button
        if on_delete:
            del_btn = Gtk.Button()
            del_btn.set_relief(Gtk.ReliefStyle.NONE)
            del_btn.set_tooltip_text("Delete conversation")
            del_img = Gtk.Image.new_from_icon_name(
                "user-trash-symbolic", Gtk.IconSize.MENU
            )
            del_btn.set_image(del_img)
            del_btn.get_style_context().add_class("conversation-delete-btn")
            del_btn.connect(
                "clicked",
                lambda b: on_delete(conversation),
            )
            row.pack_end(del_btn, False, False, 0)
        
        self.add(row)
        
        # EventBox receives button events (Box doesn't have its own GdkWindow)
        self.connect("button-press-event", lambda _, event: on_select(conversation) or False)
        self.show_all()  # Ensure all children are visible

    def set_active(self, active: bool) -> None:
        """Set the active state of the item.
        
        Args:
            active: Whether the item should be highlighted as active.
        """
        self.active = active
        ctx = self.get_style_context()
        if active:
            ctx.add_class("active")
        else:
            ctx.remove_class("active")


class Sidebar(Gtk.Box):
    """Left sidebar containing conversation list and controls."""

    def __init__(self):
        """Initialize the sidebar."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(240, -1)
        self.get_style_context().add_class("sidebar")
        
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
        scrolled.add_with_viewport(self.conversations_box)
        self.add(scrolled)
        
        # New chat button - below conversation list
        self.new_chat_button = Gtk.Button(label="+ New Chat")
        self.new_chat_button.set_margin_start(12)
        self.new_chat_button.set_margin_end(12)
        self.new_chat_button.set_margin_top(8)
        self.new_chat_button.set_margin_bottom(8)
        self.new_chat_button.set_size_request(-1, 36)
        self.new_chat_button.get_style_context().add_class("primary")
        self.add(self.new_chat_button)
        
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
        
        self.settings_btn = Gtk.Button()
        settings_icon = Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        self.settings_btn.set_image(settings_icon)
        self.settings_btn.set_tooltip_text("Settings")
        footer_controls.add(self.settings_btn)
        
        status = Gtk.Label(label="Connected")
        footer_controls.add(status)
        
        footer.add(footer_controls)
        self.add(footer)
        
        self._conversations = {}
        self._current_active = None
        self.on_conversation_selected = None
        self.on_conversation_delete = None

    def add_conversation(self, conversation: Conversation) -> None:
        """Add a conversation to the list.
        
        Args:
            conversation: The conversation to add.
        """
        item = ConversationItem(
            conversation,
            self._on_conversation_selected,
            self._on_conversation_delete,
        )
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

    def _on_conversation_delete(self, conversation: Conversation) -> None:
        """Handle conversation delete request.
        
        Args:
            conversation: The conversation to delete.
        """
        if self.on_conversation_delete:
            self.on_conversation_delete(conversation)

    def get_conversations(self) -> list[Conversation]:
        """Get all conversations in the sidebar.
        
        Returns:
            List of conversations.
        """
        return [conv for _, conv in self._conversations.values()]
