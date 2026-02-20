"""
Message bubble widget for displaying chat messages.
"""
from datetime import datetime
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, Gdk, Pango

from models import Message, MessageRole
import constants as C
from token_counter import count_text_tokens


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
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        
        # Main bubble container - half width (225px), expand vertically
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bubble.set_margin_start(10)
        bubble.set_margin_end(10)
        bubble.set_margin_top(7)
        bubble.set_margin_bottom(7)
        bubble_width = max(320, int(C.CHAT_MAX_WIDTH * 0.42))
        bubble.set_size_request(bubble_width, -1)
        text_max_width = max(220, bubble_width - 36)
        
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
                bubble.pack_start(thinking_box, False, False, 0)
            # AI Tasks section (if present in response tags)
            if ai_tasks:
                tasks_box = self._build_ai_tasks_section(ai_tasks)
                bubble.pack_start(tasks_box, False, False, 0)
            # Response section - expand vertically, no scrolling
            text_widget = build_formatted_text_view(
                response if response else message.content,
                max_width=text_max_width,
            )
            bubble.pack_start(text_widget, True, True, 0)
            tool_events = self._extract_tool_events(message)
            if tool_events:
                tools_box = self._build_tools_section(tool_events)
                bubble.pack_start(tools_box, False, False, 0)
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
            text_label.set_line_wrap_mode(Pango.WrapMode.CHAR)
            text_label.set_max_width_chars(50)
            text_label.set_markup(f"<span size='11800'>{escaped}</span>")
            bubble.pack_start(text_label, True, True, 0)
        
        # Footer metadata (message context + timestamp)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_halign(Gtk.Align.END)

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
        bubble.pack_end(footer, False, False, 0)
        
        # Apply role-based styling
        style_class = "user-bubble" if message.role == MessageRole.USER else "assistant-bubble"
        bubble.get_style_context().add_class(style_class)
        
        self.add(bubble)
        bubble.set_hexpand(False)
        
        # Show all children
        self.show_all()
        
        # Add animation class
        # Animation handled by GTK3 rendering

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
            icon_name = (
                "pan-up-symbolic" if revealer.get_reveal_child() else "pan-down-symbolic"
            )
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
    """Animated typing indicator widget with 3 bouncing dots in a chat bubble."""

    def __init__(self):
        """Initialize the typing indicator."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        # Position like AI message (left-aligned)
        self.set_halign(Gtk.Align.START)
        self.set_hexpand(False)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Bubble container - styled like AI message bubble
        bubble = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bubble.set_margin_start(14)
        bubble.set_margin_end(14)
        bubble.set_margin_top(8)
        bubble.set_margin_bottom(8)
        bubble.set_size_request(72, -1)
        bubble.get_style_context().add_class("assistant-bubble")
        bubble.get_style_context().add_class("typing-indicator-bubble")
        
        # Three animated dots
        self.dots = []
        for i in range(3):
            dot = Gtk.Label(label="●")
            dot.set_markup("<span size='14000'>●</span>")
            dot.get_style_context().add_class("typing-dot")
            dot.set_opacity(0.35)  # Start with lower opacity
            bubble.pack_start(dot, False, False, 0)
            self.dots.append(dot)
        
        self.add(bubble)
        
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
