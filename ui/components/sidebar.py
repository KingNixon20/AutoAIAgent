"""
Sidebar widget for conversation list and navigation.
"""
import gi
from typing import Callable, Optional

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Pango

from models import Conversation
import constants as C


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
        try:
            self.set_size_request(int(C.SIDEBAR_WIDTH), -1)
        except Exception:
            self.set_size_request(240, -1)
        self.get_style_context().add_class("sidebar")
        
        # Tab switcher (Conversations / AI Tasks)
        tabs_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tabs_row.set_margin_start(10)
        tabs_row.set_margin_end(10)
        tabs_row.set_margin_top(10)
        tabs_row.set_margin_bottom(6)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        tabs_row.pack_start(switcher, False, False, 0)
        self.add(tabs_row)
        self.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Conversations page
        conversations_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # Header with logo/app name (conversation tab)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.set_size_request(-1, 50)
        header.set_margin_start(14)
        header.set_margin_end(14)
        header.set_margin_top(10)
        header.set_margin_bottom(10)

        icon = Gtk.Label(label="🤖")
        icon.set_markup('<span font="24">🤖</span>')
        header.add(icon)

        app_name = Gtk.Label(label="AutoAI")
        app_name.set_markup('<span font="bold" size="14500">AutoAI</span>')
        app_name.set_halign(Gtk.Align.START)
        header.pack_start(app_name, True, True, 0)
        conversations_page.pack_start(header, False, False, 0)
        conversations_page.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Search bar (conversation tab)
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
        conversations_page.pack_start(search_box, False, False, 0)
        conversations_page.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        conv_scrolled = Gtk.ScrolledWindow()
        conv_scrolled.set_vexpand(True)
        conv_scrolled.set_hexpand(True)
        conv_scrolled.set_margin_top(2)
        conv_scrolled.set_margin_bottom(4)

        self.conversations_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.conversations_box.set_margin_start(0)
        self.conversations_box.set_margin_end(0)
        conv_scrolled.add_with_viewport(self.conversations_box)
        conversations_page.pack_start(conv_scrolled, True, True, 0)

        self.new_chat_button = Gtk.Button(label="+ New Chat")
        self.new_chat_button.set_margin_start(12)
        self.new_chat_button.set_margin_end(12)
        self.new_chat_button.set_margin_top(8)
        self.new_chat_button.set_margin_bottom(8)
        self.new_chat_button.set_size_request(-1, 36)
        self.new_chat_button.get_style_context().add_class("primary")
        conversations_page.pack_end(self.new_chat_button, False, False, 0)

        # AI Tasks page
        tasks_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        tasks_page.set_margin_start(10)
        tasks_page.set_margin_end(10)
        tasks_page.set_margin_top(6)
        tasks_page.set_margin_bottom(8)

        self.tasks_hint_label = Gtk.Label()
        self.tasks_hint_label.set_halign(Gtk.Align.START)
        self.tasks_hint_label.set_xalign(0.0)
        self.tasks_hint_label.set_line_wrap(True)
        self.tasks_hint_label.set_markup(
            "<span size='9000' foreground='#888'>Track plan items for this chat. "
            "Checked items remain saved with the conversation.</span>"
        )
        tasks_page.pack_start(self.tasks_hint_label, False, False, 0)

        task_input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.task_entry = Gtk.Entry()
        self.task_entry.set_placeholder_text("Add task item...")
        self.task_entry.connect("activate", self._on_add_task_clicked)
        task_input_row.pack_start(self.task_entry, True, True, 0)
        self.add_task_button = Gtk.Button(label="Add")
        self.add_task_button.connect("clicked", self._on_add_task_clicked)
        task_input_row.pack_end(self.add_task_button, False, False, 0)
        tasks_page.pack_start(task_input_row, False, False, 0)

        tasks_scrolled = Gtk.ScrolledWindow()
        tasks_scrolled.set_vexpand(True)
        tasks_scrolled.set_hexpand(True)
        tasks_scrolled.set_margin_top(2)
        tasks_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.tasks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tasks_scrolled.add_with_viewport(self.tasks_box)
        tasks_page.pack_start(tasks_scrolled, True, True, 0)

        self.stack.add_titled(conversations_page, "conversations", "Conversations")
        self.stack.add_titled(tasks_page, "ai_tasks", "AI Tasks")
        self.add(self.stack)
        
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
        self._current_conversation_id = None
        self.on_conversation_selected = None
        self.on_conversation_delete = None
        self.on_tasks_changed = None
        self._refresh_tasks_view()

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
        self._refresh_tasks_controls()

    def remove_conversation(self, conversation_id: str) -> None:
        """Remove a conversation from the list.
        
        Args:
            conversation_id: ID of the conversation to remove.
        """
        if conversation_id in self._conversations:
            item, _ = self._conversations[conversation_id]
            self.conversations_box.remove(item)
            del self._conversations[conversation_id]
            if self._current_conversation_id == conversation_id:
                self._current_conversation_id = None
                self._refresh_tasks_view()
            self._refresh_tasks_controls()

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
            self._current_conversation_id = conversation_id
            if not isinstance(conversation.ai_tasks, list):
                conversation.ai_tasks = []
            self._refresh_tasks_view()

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

    def set_ai_tasks(self, conversation_id: str, tasks: list[dict]) -> None:
        """Set AI tasks for one conversation and refresh current tasks if needed."""
        if conversation_id not in self._conversations:
            return
        _, conversation = self._conversations[conversation_id]
        conversation.ai_tasks = self._sanitize_tasks(tasks)
        if self._current_conversation_id == conversation_id:
            self._refresh_tasks_view()

    def _current_tasks(self) -> list[dict]:
        """Get tasks for active conversation."""
        if not self._current_conversation_id:
            return []
        data = self._conversations.get(self._current_conversation_id)
        if not data:
            return []
        _, conversation = data
        if not isinstance(conversation.ai_tasks, list):
            conversation.ai_tasks = []
        return conversation.ai_tasks

    def _sanitize_tasks(self, tasks: list[dict]) -> list[dict]:
        """Normalize task list structure."""
        cleaned = []
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            text = str(task.get("text", "")).strip()
            if not text:
                continue
            status = str(task.get("status", "")).strip().lower()
            if status not in ("uncompleted", "in_progress", "completed"):
                status = "completed" if bool(task.get("done", False)) else "uncompleted"
            cleaned.append(
                {
                    "text": text,
                    "done": (status == "completed"),
                    "status": status,
                }
            )
        return cleaned

    def _refresh_tasks_controls(self) -> None:
        """Enable/disable task controls based on selected conversation."""
        has_conversations = bool(self._conversations)
        self.task_entry.set_sensitive(has_conversations)
        self.add_task_button.set_sensitive(has_conversations)
        if not has_conversations:
            self.task_entry.set_text("")

    def _refresh_tasks_view(self) -> None:
        """Render task rows for current conversation."""
        for child in list(self.tasks_box.get_children()):
            self.tasks_box.remove(child)

        tasks = self._current_tasks()
        self._refresh_tasks_controls()
        if not self._current_conversation_id:
            empty = Gtk.Label()
            empty.set_halign(Gtk.Align.START)
            empty.set_xalign(0.0)
            empty.set_markup("<span foreground='#888'>Select a conversation to manage tasks.</span>")
            self.tasks_box.pack_start(empty, False, False, 0)
            self.tasks_box.show_all()
            return
        if not tasks:
            empty = Gtk.Label()
            empty.set_halign(Gtk.Align.START)
            empty.set_xalign(0.0)
            empty.set_markup("<span foreground='#888'>No tasks yet.</span>")
            self.tasks_box.pack_start(empty, False, False, 0)
            self.tasks_box.show_all()
            return

        for idx, task in enumerate(tasks):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.set_margin_top(2)
            row.set_margin_bottom(2)

            task_left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            task_left.set_hexpand(True)

            status = self._task_status(task)
            status_btn = Gtk.Button()
            status_btn.set_relief(Gtk.ReliefStyle.NONE)
            status_btn.set_tooltip_text("Task status")
            status_btn.set_valign(Gtk.Align.START)
            status_btn.set_size_request(18, 18)
            status_btn.set_sensitive(False)
            status_lbl = Gtk.Label()
            symbol, color = self._status_symbol_and_color(status)
            status_lbl.set_markup(f"<span foreground='{color}' size='12000'>{symbol}</span>")
            status_btn.add(status_lbl)
            task_left.pack_start(status_btn, False, False, 0)

            check = Gtk.CheckButton()
            check.set_active(status == "completed")
            check.set_sensitive(False)
            check.set_tooltip_text("Status is managed by AI")
            task_left.pack_start(check, False, False, 0)

            task_label = Gtk.Label()
            task_label.set_halign(Gtk.Align.START)
            task_label.set_xalign(0.0)
            task_label.set_hexpand(True)
            task_label.set_line_wrap(True)
            task_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            task_label.set_max_width_chars(28)
            task_label.set_text(str(task.get("text", "")))
            task_left.pack_start(task_label, True, True, 0)

            row.pack_start(task_left, True, True, 0)

            del_btn = Gtk.Button()
            del_btn.set_relief(Gtk.ReliefStyle.NONE)
            del_btn.set_tooltip_text("Delete task")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.set_size_request(22, 22)
            del_img = Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.MENU)
            del_btn.set_image(del_img)
            del_btn.connect("clicked", self._on_task_delete_clicked, idx)
            row.pack_end(del_btn, False, False, 0)

            self.tasks_box.pack_start(row, False, False, 0)

        self.tasks_box.show_all()

    def _on_add_task_clicked(self, _widget) -> None:
        """Create a task from entry text."""
        text = self.task_entry.get_text().strip()
        if not text:
            return
        tasks = self._current_tasks()
        tasks.append({"text": text, "done": False, "status": "uncompleted"})
        self.task_entry.set_text("")
        self._refresh_tasks_view()
        self._emit_tasks_changed(tasks)

    def _on_task_toggled(self, check: Gtk.CheckButton, index: int) -> None:
        """Update task completion state."""
        tasks = self._current_tasks()
        if index < 0 or index >= len(tasks):
            return
        is_done = bool(check.get_active())
        tasks[index]["done"] = is_done
        tasks[index]["status"] = "completed" if is_done else "uncompleted"
        self._refresh_tasks_view()
        self._emit_tasks_changed(tasks)

    def _on_task_status_clicked(self, _button: Gtk.Button, index: int) -> None:
        """Cycle task status and keep done flag consistent."""
        tasks = self._current_tasks()
        if index < 0 or index >= len(tasks):
            return
        current = self._task_status(tasks[index])
        order = ["uncompleted", "in_progress", "completed"]
        next_idx = (order.index(current) + 1) % len(order)
        nxt = order[next_idx]
        tasks[index]["status"] = nxt
        tasks[index]["done"] = (nxt == "completed")
        self._refresh_tasks_view()
        self._emit_tasks_changed(tasks)

    def _on_task_delete_clicked(self, _button: Gtk.Button, index: int) -> None:
        """Delete one task row."""
        tasks = self._current_tasks()
        if index < 0 or index >= len(tasks):
            return
        del tasks[index]
        self._refresh_tasks_view()
        self._emit_tasks_changed(tasks)

    def _emit_tasks_changed(self, tasks: list[dict]) -> None:
        """Notify listeners that active conversation tasks changed."""
        if not self._current_conversation_id:
            return
        if self.on_tasks_changed:
            self.on_tasks_changed(self._current_conversation_id, self._sanitize_tasks(tasks))

    def _task_status(self, task: dict) -> str:
        """Return normalized status for a task dict."""
        status = str(task.get("status", "")).strip().lower()
        if status in ("uncompleted", "in_progress", "completed"):
            return status
        return "completed" if bool(task.get("done", False)) else "uncompleted"

    def _status_symbol_and_color(self, status: str) -> tuple[str, str]:
        """Return UI symbol + color for task status."""
        if status == "completed":
            return ("●", "#32D27A")
        if status == "in_progress":
            return ("●", "#F6C544")
        return ("●", "#8E98A8")
