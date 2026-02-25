"""
Message bubble widget for displaying chat messages.
"""
from datetime import datetime
from typing import Optional, Callable
from gi.repository import Gtk, Gio, Gdk, Pango

from models import Message, MessageRole
import constants as C
from token_counter import count_text_tokens


class MessageBubble(Gtk.Box):
    """A message bubble widget displaying a single message."""

    def __init__(self, message: Message,
                 on_edit_message: Optional[Callable[[str], None]] = None,
                 on_repush_message: Optional[Callable[[str], None]] = None,
                 on_delete_message: Optional[Callable[[str], None]] = None,
                 on_message_edited: Optional[Callable[[str, str], None]] = None, # Added this parameter
                 max_content_width: int = -1): # Added max_content_width
        """Initialize the message bubble.
        
        Args:
            message: The message to display.
            on_edit_message: Callback for editing a message.
            on_repush_message: Callback for re-pushing a message.
            on_delete_message: Callback for deleting a message.
            on_message_edited: Callback for when the message content is edited.
            max_content_width: Maximum width for the message content.
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.message = message
        self.on_edit_message = on_edit_message
        self.on_repush_message = on_repush_message
        self.on_delete_message = on_delete_message
        self.on_message_edited = on_message_edited # Store the new callback
        self.max_content_width = max_content_width
        self.is_editing = False # Track if the message is currently being edited
        # Full width, no alignment tricks
        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Role indicator (user/assistant) - subtle prefix
        is_assistant = message.role == MessageRole.ASSISTANT
        role_prefix = "Assistant" if is_assistant else "You"
        role_color = "#7C5DFF" if is_assistant else "#00D9FF"
        
        # Header with role and timestamp
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_bottom(4)
        
        role_label = Gtk.Label()
        role_label.set_halign(Gtk.Align.START)
        role_label.set_markup(f"<span size='9500' foreground='{role_color}' weight='600'>{role_prefix}</span>")
        header.pack_start(role_label, False, False, 0)
        
        timestamp_str = message.timestamp.strftime("%H:%M")
        timestamp = Gtk.Label()
        timestamp.set_markup(f"<span size='8500' foreground='#707070'>{timestamp_str}</span>")
        header.pack_start(timestamp, False, False, 0)
        
        token_count = self._message_token_count(message)
        token_label = Gtk.Label()
        token_label.set_markup(
            f"<span size='8500' foreground='#707070'>• {token_count:,} tokens</span>"
        )
        header.pack_start(token_label, False, False, 0)
        
        self.pack_start(header, False, False, 0)
        
        # Message content container - no bubble styling
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content_box.set_margin_start(0)
        content_box.set_margin_end(0)
        
        # Message text - use formatted view for assistant, plain label for user
        if is_assistant:
            from ui.markdown_renderer import (
                build_formatted_text_view,
                extract_ai_tasks_and_response,
                split_thinking_and_response,
            )
            thinking, response = split_thinking_and_response(message.content)
            ai_tasks, response = extract_ai_tasks_and_response(response if response else message.content)
            # Thinking section (collapsible, ChatGPT/DeepSeek style)
            if thinking:
                thinking_box = self._build_thinking_section(thinking)
                content_box.pack_start(thinking_box, False, False, 0)
            # AI Tasks section (if present in response tags)
            if ai_tasks:
                tasks_box = self._build_ai_tasks_section(ai_tasks)
                content_box.pack_start(tasks_box, False, False, 0)
            # Response section - expand vertically, no scrolling
            text_widget = build_formatted_text_view(
                response if response else message.content,
                max_width=self.max_content_width if self.max_content_width > 0 else min(800, C.CHAT_MAX_WIDTH),
            )
            content_box.pack_start(text_widget, True, True, 0)
            tool_events = self._extract_tool_events(message)
            if tool_events:
                tools_box = self._build_tools_section(tool_events)
                content_box.pack_start(tools_box, False, False, 0)
        else:
            # Display mode (Gtk.Label)
            escaped = (
                message.content.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            text_label = Gtk.Label(label=message.content, wrap=True)
            text_label.set_selectable(True)
            text_label.set_justify(Gtk.Justification.LEFT)
            text_label.set_line_wrap(True)
            text_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text_label.set_xalign(0.0)
            text_label.set_halign(Gtk.Align.START)
            text_label.set_markup(f"<span size='11000'>{escaped}</span>")
            if self.max_content_width > 0:
                # Set a wrap width on the label to respect the available space
                # Using a rough estimate of 5 characters per token to convert pixels to chars
                text_label.set_max_width_chars(int(self.max_content_width / 5))
            content_box.pack_start(text_label, True, True, 0)
            self.message_display_widget = text_label

            # Edit mode (Gtk.TextView)
            edit_text_view = Gtk.TextView()
            edit_text_view.set_wrap_mode(Gtk.WrapMode.WORD)
            edit_text_view.get_buffer().set_text(message.content, -1)
            edit_text_view.set_size_request(-1, 100) # Give it some initial height
            edit_text_view.get_style_context().add_class("message-editor")
            
            edit_text_scroll = Gtk.ScrolledWindow()
            edit_text_scroll.add(edit_text_view)
            edit_text_scroll.set_hexpand(True)
            edit_text_scroll.set_vexpand(True)
            edit_text_scroll.set_size_request(-1, 100)
            
            # Action buttons for edit mode
            edit_actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            edit_actions_box.set_halign(Gtk.Align.END)
            edit_actions_box.get_style_context().add_class("message-editor-actions")

            save_btn = Gtk.Button.new_with_label("Save")
            save_btn.get_style_context().add_class("suggested-action")
            save_btn.connect("clicked", self._on_edit_submitted)
            edit_actions_box.pack_start(save_btn, False, False, 0)

            cancel_btn = Gtk.Button.new_with_label("Cancel")
            cancel_btn.connect("clicked", self._on_edit_cancelled)
            edit_actions_box.pack_start(cancel_btn, False, False, 0)
            
            self.message_edit_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.message_edit_container.pack_start(edit_text_scroll, True, True, 0)
            self.message_edit_container.pack_start(edit_actions_box, False, False, 0)
            self.message_edit_container.show_all()
            
            content_box.pack_start(self.message_edit_container, True, True, 0)
            self.message_edit_container.hide() # Initially hidden
            self.message_editor_text_view = edit_text_view
        
        # Footer metadata (message context + timestamp)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_halign(Gtk.Align.END)

        # Action buttons (re-push, edit, delete)
        action_buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        action_buttons_box.set_halign(Gtk.Align.END)
        action_buttons_box.set_valign(Gtk.Align.CENTER)
        action_buttons_box.get_style_context().add_class("message-actions")

        # Edit button
        edit_btn = Gtk.Button()
        edit_btn.set_relief(Gtk.ReliefStyle.NONE)
        edit_btn.set_tooltip_text("Edit message")
        edit_icon = Gtk.Image.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        edit_btn.set_image(edit_icon)
        edit_btn.get_style_context().add_class("message-action-button")
        edit_btn.connect("clicked", self._on_edit_clicked)
        action_buttons_box.pack_start(edit_btn, False, False, 0)
        self.edit_button = edit_btn

        # Re-push button (only for user messages)
        if message.role == MessageRole.USER:
            repush_btn = Gtk.Button()
            repush_btn.set_relief(Gtk.ReliefStyle.NONE)
            repush_btn.set_tooltip_text("Re-send message")
            repush_icon = Gtk.Image.new_from_icon_name("object-rotate-right-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
            repush_btn.set_image(repush_icon)
            repush_btn.get_style_context().add_class("message-action-button")
            repush_btn.connect("clicked", self._on_repush_clicked)
            action_buttons_box.pack_start(repush_btn, False, False, 0)
            self.repush_button = repush_btn
        else:
            self.repush_button = None

        # Delete button
        delete_btn = Gtk.Button()
        delete_btn.set_relief(Gtk.ReliefStyle.NONE)
        delete_btn.set_tooltip_text("Delete message")
        delete_icon = Gtk.Image.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        delete_btn.set_image(delete_icon)
        delete_btn.get_style_context().add_class("message-action-button")
        delete_btn.connect("clicked", self._on_delete_clicked)
        action_buttons_box.pack_start(delete_btn, False, False, 0)
        self.delete_button = delete_btn

        footer.pack_start(action_buttons_box, False, False, 0)



        token_count = self._message_token_count(message)
        token_label = Gtk.Label()
        token_label.set_markup(
            f"<span size='8200' foreground='#9a9a9a'>{token_count:,} token(s)</span>"
        )
        footer.pack_start(token_label, False, False, 0)

        timestamp_str = message.timestamp.strftime("%H:%M")
        timestamp = Gtk.Label()
        timestamp.set_markup(f"<span size='8200' foreground='#808080'>{timestamp_str}</span>")
        footer.pack_start(timestamp, False, False, 0)
        
        # The MessageBubble (self) should pack its children directly.
        # 'header' is already packed with 'self.pack_start(header, False, False, 0)' at the beginning of __init__
        self.pack_start(content_box, True, True, 0) # This one was missing
        self.pack_end(footer, False, False, 0)
        
        # Apply role-based styling to the MessageBubble (self)
        if message.role == MessageRole.USER:
            self.get_style_context().add_class("user-bubble")
        # AI messages will not have a specific bubble class, relying on parent container styling
        
        # Show all children
        self.show_all()

    def set_edit_mode(self, editing: bool) -> None:
        """Set the message bubble into or out of edit mode."""
        if self.message.role != MessageRole.USER:
            return # Only user messages can be edited
            
        self.is_editing = editing
        self.message_display_widget.set_visible(not editing)
        self.message_edit_container.set_visible(editing)
        
        if editing:
            # Populate the TextView with current content and set focus
            self.message_editor_text_view.get_buffer().set_text(self.message.content, -1)
            self.message_editor_text_view.grab_focus()
            # Hide action buttons when editing
            self.edit_button.hide()
            if self.repush_button:
                self.repush_button.hide()
            self.delete_button.hide()
        else:
            # Show action buttons when not editing
            self.edit_button.show()
            if self.repush_button:
                self.repush_button.show()
            self.delete_button.show()

    def _on_edit_submitted(self, _button) -> None:
        """Handle save button click in edit mode."""
        buffer = self.message_editor_text_view.get_buffer()
        new_content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        
        if self.on_message_edited:
            self.on_message_edited(self.message.id, new_content)
        
        # Exit edit mode regardless of whether callback was handled
        self.set_edit_mode(False)

    def _on_edit_cancelled(self, _button) -> None:
        """Handle cancel button click in edit mode."""
        self.set_edit_mode(False)

    def _message_token_count(self, message: Message) -> int:
        """Return stored token count, or a rough estimate when unavailable."""
        if message.tokens and message.tokens > 0:
            return int(message.tokens)
        return count_text_tokens(message.content)

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

        thinking_view = build_formatted_text_view(thinking_text, max_width=max(260, (C.CHAT_MAX_WIDTH // 2) - 72))
        thinking_view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.7, 0.7, 0.7, 1))
        content_box.pack_start(thinking_view, True, True, 0)

        revealer = Gtk.Revealer()
        revealer.set_reveal_child(False)
        revealer.add(content_box)

        def toggle(btn):
            revealer.set_reveal_child(not revealer.get_reveal_child())
            icon_name = "pan-up-symbolic" if revealer.get_reveal_child() else "pan-down-symbolic"
            expand_btn.set_image(
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            )

        expand_btn.connect("clicked", toggle)

        outer.pack_start(revealer, False, False, 0)

        return outer

    def _extract_tool_events(self, message: Message) -> list[dict]:
        """Return tool events attached to a message metadata block."""
        if not isinstance(message.meta, dict):
            return []
        events = message.meta.get("tool_events")
        if not isinstance(events, list):
            return []
        return [ev for ev in events if isinstance(ev, dict)]

    def _build_tools_section(self, tool_events: list[dict]) -> Gtk.Box:
        """Build collapsible tool execution section."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.get_style_context().add_class("tool-events-section")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(8)
        header.set_margin_bottom(6)

        expand_btn = Gtk.Button()
        expand_btn.set_relief(Gtk.ReliefStyle.NONE)
        expand_icon = Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON)
        expand_btn.set_image(expand_icon)
        expand_btn.get_style_context().add_class("thinking-toggle")

        header_label = Gtk.Label()
        header_label.set_halign(Gtk.Align.START)
        header_label.set_markup(
            f"<span size='9800' foreground='#9a9ab5' weight='600'>Tools Used ({len(tool_events)})</span>"
        )
        header.pack_start(expand_btn, False, False, 0)
        header.pack_start(header_label, False, False, 0)
        header.pack_start(Gtk.Box(), True, True, 0)
        outer.pack_start(header, False, False, 0)

        revealer = Gtk.Revealer()
        revealer.set_reveal_child(False)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.get_style_context().add_class("thinking-content")
        for ev in tool_events:
            name = str(ev.get("name", "tool"))
            result = ev.get("result")
            ok = True
            if isinstance(result, dict):
                ok = bool(result.get("ok", True))
            badge = "ok" if ok else "error"
            detail = self._compact_result(result)
            item = Gtk.Label()
            item.set_halign(Gtk.Align.START)
            item.set_xalign(0.0)
            item.set_selectable(True)
            item.set_line_wrap(True)
            item.set_line_wrap_mode(Pango.WrapMode.CHAR)
            item.set_max_width_chars(60)
            escaped_detail = (
                detail.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            item.set_markup(
                f"<span size='9300'><b>{name}</b> • {badge}\n{escaped_detail}</span>"
            )
            content_box.pack_start(item, False, False, 0)

        revealer.add(content_box)

        def toggle(_btn):
            next_state = not revealer.get_reveal_child()
            revealer.set_reveal_child(next_state)
            icon_name = "pan-up-symbolic" if next_state else "pan-down-symbolic"
            expand_btn.set_image(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON))

        expand_btn.connect("clicked", toggle)
        outer.pack_start(revealer, False, False, 0)
        return outer

    def _render_tool_event_detail(self, tool_event: dict) -> Optional[Gtk.Widget]:
        """Render a single structured tool event into a Gtk.Widget."""
        from ui.markdown_renderer import build_formatted_text_view
        
        name = tool_event.get("name", "unknown_tool")
        status = tool_event.get("status", "unknown")
        details = tool_event.get("details", {})
        detail_type = details.get("type", "tool_output")
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.get_style_context().add_class("tool-event-detail")
        if status == "error":
            vbox.get_style_context().add_class("tool-event-error")

        # Tool name and status header
        header_label = Gtk.Label()
        header_label.set_halign(Gtk.Align.START)
        header_label.set_xalign(0.0)
        icon = self._get_tool_event_icon(detail_type, status)
        header_label.set_markup(
            f"<span size='9500'><b>{icon} {name}</b> • <span foreground='{C.COLOR_ERROR if status == 'error' else C.COLOR_ACCENT_PRIMARY}'>{status.upper()}</span></span>"
        )
        vbox.pack_start(header_label, False, False, 0)

        # Render details based on type
        if detail_type == "file_edit":
            path = details.get("path", "N/A")
            diff_content = details.get("diff", "No diff available.")
            vbox.pack_start(Gtk.Label.new(f"File: {path}"), False, False, 0)
            if diff_content:
                diff_view = build_formatted_text_view(f"```diff\n{diff_content}\n```")
                diff_view.set_hexpand(True)
                diff_view.set_vexpand(True)
                vbox.pack_start(diff_view, False, False, 0)
        
        elif detail_type == "file_write":
            path = details.get("path", "N/A")
            bytes_written = details.get("bytes_written", 0)
            content_preview = details.get("content_preview", "")
            vbox.pack_start(Gtk.Label.new(f"File: {path} ({bytes_written} bytes written)"), False, False, 0)
            if content_preview:
                preview_view = build_formatted_text_view(f"```\n{content_preview}\n```")
                preview_view.set_hexpand(True)
                vbox.pack_start(preview_view, False, False, 0)

        elif detail_type == "file_read":
            path = details.get("path", "N/A")
            content_preview = details.get("content_preview", "")
            vbox.pack_start(Gtk.Label.new(f"File: {path}"), False, False, 0)
            if content_preview:
                preview_view = build_formatted_text_view(f"```\n{content_preview}\n```")
                preview_view.set_hexpand(True)
                vbox.pack_start(preview_view, False, False, 0)
        
        elif detail_type == "file_delete":
            path = details.get("path", "N/A")
            vbox.pack_start(Gtk.Label.new(f"File: {path} (deleted)"), False, False, 0)

        elif detail_type == "file_listing":
            path = details.get("path", ".")
            entries = details.get("entries", [])
            entry_text = "\n".join([f"- {e}" for e in entries])
            vbox.pack_start(Gtk.Label.new(f"Path: {path}"), False, False, 0)
            if entry_text:
                entries_view = build_formatted_text_view(f"```\n{entry_text}\n```")
                entries_view.set_hexpand(True)
                vbox.pack_start(entries_view, False, False, 0)

        elif detail_type == "command_execution":
            command = details.get("command", "N/A")
            stdout = details.get("stdout", "").strip()
            stderr = details.get("stderr", "").strip()
            returncode = details.get("returncode", None)
            
            cmd_label = Gtk.Label()
            cmd_label.set_halign(Gtk.Align.START)
            cmd_label.set_markup(f"Command: <b>{self._escape_markup(command)}</b> (Exit: {returncode})")
            vbox.pack_start(cmd_label, False, False, 0)

            if stdout:
                stdout_view = build_formatted_text_view(f"```bash\n{stdout}\n```")
                stdout_view.set_hexpand(True)
                vbox.pack_start(stdout_view, False, False, 0)
            if stderr:
                stderr_view = build_formatted_text_view(f"```bash\n{stderr}\n```")
                stderr_view.set_hexpand(True)
                vbox.pack_start(stderr_view, False, False, 0)

        elif detail_type == "text_search":
            pattern = details.get("pattern", "N/A")
            path = details.get("path", ".")
            matches = details.get("matches", [])
            match_text = "\n".join([f"- {m}" for m in matches])
            vbox.pack_start(Gtk.Label.new(f"Pattern: {pattern} in {path}"), False, False, 0)
            if match_text:
                matches_view = build_formatted_text_view(f"```\n{match_text}\n```")
                matches_view.set_hexpand(True)
                vbox.pack_start(matches_view, False, False, 0)

        elif detail_type == "tool_error":
            message = details.get("message", "An error occurred.")
            vbox.pack_start(Gtk.Label.new(f"Error: {message}"), False, False, 0)
            exception_info = details.get("exception", "")
            if exception_info:
                vbox.pack_start(Gtk.Label.new(f"Exception: {exception_info}"), False, False, 0)

        return vbox

    def _get_tool_event_icon(self, detail_type: str, status: str) -> str:
        if status == "error":
            return "❌"
        
        if detail_type == "file_edit":
            return "📝"
        elif detail_type == "file_write":
            return "💾"
        elif detail_type == "file_read":
            return "📖"
        elif detail_type == "file_delete":
            return "🗑️"
        elif detail_type == "file_listing":
            return "📂"
        elif detail_type == "command_execution":
            return "▶️"
        elif detail_type == "text_search":
            return "🔎"
        return "🛠️"

    def _build_ai_tasks_section(self, tasks: list[dict]) -> Gtk.Box:
        """Render parsed AI tasks in a styled list."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.get_style_context().add_class("ai-tasks-section")

        header = Gtk.Label()
        header.set_halign(Gtk.Align.START)
        header.set_xalign(0.0)
        header.set_markup(
            f"<span size='9800' weight='600' foreground='#aeb3ff'>AI Tasks ({len(tasks)})</span>"
        )
        outer.pack_start(header, False, False, 0)

        for task in tasks:
            text = str(task.get("text", "")).strip()
            if not text:
                continue
            done = bool(task.get("done", False))
            status = "Completed" if done else "Pending"
            status_color = "#5bd38e" if done else "#f5cd61"

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.get_style_context().add_class("ai-task-row")

            dot = Gtk.Label()
            dot.set_halign(Gtk.Align.START)
            dot.set_valign(Gtk.Align.START)
            dot.set_markup(f"<span foreground='{status_color}' size='11000'>●</span>")
            row.pack_start(dot, False, False, 0)

            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            body.set_hexpand(True)
            body.get_style_context().add_class("ai-task-body")

            summary, goal, expected = self._split_task_text_fields(text)
            escaped_summary = self._escape_markup(summary)
            title = Gtk.Label()
            title.set_halign(Gtk.Align.START)
            title.set_xalign(0.0)
            title.set_line_wrap(True)
            title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            title.set_markup(f"<span size='9500' foreground='#e8ebff'>{escaped_summary}</span>")
            body.pack_start(title, False, False, 0)

            if goal:
                goal_lbl = Gtk.Label()
                goal_lbl.set_halign(Gtk.Align.START)
                goal_lbl.set_xalign(0.0)
                goal_lbl.set_line_wrap(True)
                goal_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                goal_lbl.set_markup(
                    f"<span size='8900' foreground='#b7bdd8'><b>Goal:</b> {self._escape_markup(goal)}</span>"
                )
                body.pack_start(goal_lbl, False, False, 0)
            if expected:
                out_lbl = Gtk.Label()
                out_lbl.set_halign(Gtk.Align.START)
                out_lbl.set_xalign(0.0)
                out_lbl.set_line_wrap(True)
                out_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                out_lbl.set_markup(
                    f"<span size='8900' foreground='#b7bdd8'><b>Expected:</b> {self._escape_markup(expected)}</span>"
                )
                body.pack_start(out_lbl, False, False, 0)

            row.pack_start(body, True, True, 0)

            status_lbl = Gtk.Label()
            status_lbl.set_halign(Gtk.Align.END)
            status_lbl.set_valign(Gtk.Align.START)
            status_lbl.set_markup(
                f"<span size='8200' foreground='{status_color}'>{status}</span>"
            )
            row.pack_end(status_lbl, False, False, 0)

            outer.pack_start(row, False, False, 0)

        return outer

    def _split_task_text_fields(self, text: str) -> tuple[str, str, str]:
        """Split one task line into summary / goal / expected parts."""
        summary = text
        goal = ""
        expected = ""
        for part in [p.strip() for p in text.split("|") if p.strip()]:
            lowered = part.lower()
            if lowered.startswith("goal:"):
                goal = part.split(":", 1)[1].strip() if ":" in part else ""
            elif lowered.startswith("expected:"):
                expected = part.split(":", 1)[1].strip() if ":" in part else ""
            else:
                summary = part
        return (summary, goal, expected)

    def _escape_markup(self, value: str) -> str:
        """Escape text for safe GTK markup rendering."""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
    
    def _on_edit_clicked(self, _button) -> None:
        if self.on_edit_message:
            self.on_edit_message(self.message.id)
        self.set_edit_mode(True)

    def _on_repush_clicked(self, _button) -> None:
        """Handle repush button click."""
        if self.on_repush_message:
            self.on_repush_message(self.message.id)

    def _on_delete_clicked(self, _button) -> None:
        """Handle delete button click."""
        if self.on_delete_message:
            self.on_delete_message(self.message.id)

    def _compact_result(self, result: object) -> str:
        """Render tool result in compact one-line form."""
        if isinstance(result, dict):
            if "error" in result:
                return str(result.get("error"))
            if "stdout" in result and result.get("stdout"):
                return str(result.get("stdout"))[:220]
            if "content" in result and result.get("content"):
                return str(result.get("content"))[:220]
            return str(result)[:220]
        return str(result)[:220]


class TypingIndicator(Gtk.Box):
    """Animated typing indicator widget."""

    def __init__(self):
        """Initialize the typing indicator."""
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        
        # Position like AI message (left, full width)
        self.set_halign(Gtk.Align.START)
        self.set_hexpand(False)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Simple text label
        typing_label = Gtk.Label()
        typing_label.set_markup("<span size='9500' foreground='#7C5DFF' weight='600'>AI</span>")
        self.pack_start(typing_label, False, False, 0)
        
        # Three animated dots
        self.dots = []
        for i in range(3):
            dot = Gtk.Label(label="●")
            dot.set_markup("<span size='11000' foreground='#7C5DFF'>●</span>")
            dot.set_opacity(0.35)  # Start with lower opacity
            self.pack_start(dot, False, False, 0)
            self.dots.append(dot)
        
        # Animation state
        self.animation_step = 0
        self.animation_timeout = None
        
        # Start animation
        self._start_animation()
        
        self.show_all()
    
    def _start_animation(self):
        """Start the dot animation loop."""
        from gi.repository import GLib
        self.animation_timeout = GLib.timeout_add(300, self._animate_dots)
    
    def _animate_dots(self) -> bool:
        """Animate the dots by changing opacity.
        
        Returns:
            True to continue the animation, False to stop.
        """
        # Cycle through animation steps
        self.animation_step = (self.animation_step + 1) % 6
        
        for i, dot in enumerate(self.dots):
            # Each dot has offset animation
            offset_step = (self.animation_step - i * 2) % 6
            
            # Create pulsing effect: 0.2 -> 1.0 -> 0.2
            if offset_step < 3:
                opacity = 0.2 + (offset_step / 3.0) * 0.8
            else:
                opacity = 1.0 - ((offset_step - 3) / 3.0) * 0.8
            
            dot.set_opacity(opacity)
        
        return True  # Continue animation
    
    def stop_animation(self):
        """Stop the animation."""
        from gi.repository import GLib
        if self.animation_timeout:
            GLib.source_remove(self.animation_timeout)
            self.animation_timeout = None