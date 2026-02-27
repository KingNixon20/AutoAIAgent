"""
Message bubble widget for displaying chat messages.
"""
from datetime import datetime
from typing import Optional, Callable
from gi.repository import Gtk, Gdk, Pango, GLib
import re
import json

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
                 on_tool_permission_decision: Optional[Callable[[str, str, bool, str], None]] = None,
                 max_content_width: int = -1,
                 animate: bool = True):
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
        self.on_tool_permission_decision = on_tool_permission_decision
        self.max_content_width = max_content_width
        self._animate_enabled = bool(animate)
        self.is_editing = False # Track if the message is currently being edited
        self._fade_source_id = None
        self._permission_status_label: Optional[Gtk.Label] = None
        self._permission_allow_btn: Optional[Gtk.Button] = None
        self._permission_deny_btn: Optional[Gtk.Button] = None
        self._permission_deny_reason_btn: Optional[Gtk.Button] = None
        self._permission_always_toggle: Optional[Gtk.CheckButton] = None
        self._permission_card: Optional[Gtk.Box] = None
        self._permission_details_revealer: Optional[Gtk.Revealer] = None
        self._permission_expand_btn: Optional[Gtk.Button] = None
        self._permission_reason_box: Optional[Gtk.Box] = None
        self._permission_reason_entry: Optional[Gtk.Entry] = None
        # Full width, no alignment tricks
        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        
        # Role indicator (user/assistant/system) - subtle prefix
        is_permission_request = self._is_tool_permission_message(message)
        permission_pending = self._is_tool_permission_pending(message)
        is_assistant = message.role == MessageRole.ASSISTANT
        is_system = message.role == MessageRole.SYSTEM
        if is_permission_request and permission_pending:
            role_prefix = "Tool Action"
            role_color = "#f6c453"
        elif is_permission_request:
            role_prefix = "Assistant"
            role_color = "#7C5DFF"
        elif is_assistant:
            role_prefix = "Assistant"
            role_color = "#7C5DFF"
        elif is_system:
            role_prefix = "System"
            role_color = "#f6c453"
        else:
            role_prefix = "You"
            role_color = "#00D9FF"
        
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
        
        # Message text - special inline card for permission requests
        if is_permission_request:
            permission_card = self._build_tool_permission_card(message.meta or {}, animate=animate)
            content_box.pack_start(permission_card, False, False, 0)
            self.message_display_widget = permission_card
        # Message text - use formatted view for assistant, plain label for user
        elif is_assistant:
            from ui.markdown_renderer import (
                build_formatted_text_view,
                build_diff_change_badge,
                count_diff_additions_removals,
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
            response_content = response if response else message.content
            if self._looks_like_agent_activity(response_content):
                text_widget = self._build_agent_activity_section(response_content)
            else:
                text_widget = build_formatted_text_view(
                    response_content,
                    max_width=self.max_content_width if self.max_content_width > 0 else 700,
                )
            content_box.pack_start(text_widget, True, True, 0)
            self.message_display_widget = text_widget  # Store for dynamic width updates
            tool_events = self._extract_tool_events(message)
            if tool_events:
                change_items = self._build_change_items_from_tool_events(
                    tool_events,
                    count_diff_additions_removals,
                )
                if change_items:
                    plural = "s" if len(change_items) != 1 else ""
                    summary = f"{len(change_items)} file{plural} changed"
                    change_badge = build_diff_change_badge(
                        summary_text=summary,
                        items=change_items,
                        actions=["Undo", "Review"],
                        animate=animate,
                    )
                    content_box.pack_start(change_badge, False, False, 0)
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
            text_label.set_markup(f"<span size='11300' weight='500'>{escaped}</span>")
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
        
        show_footer_actions = not is_permission_request
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_halign(Gtk.Align.FILL)
        footer.set_hexpand(True)
        self.edit_button = None
        self.repush_button = None
        self.delete_button = None

        if show_footer_actions:
            # Action buttons (re-push, edit, delete) - pack at END for right alignment
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

            # Pack action buttons at END (right side) of footer
            footer.pack_end(action_buttons_box, False, False, 0)
        
        # The MessageBubble (self) should pack its children directly.
        # 'header' is already packed with 'self.pack_start(header, False, False, 0)' at the beginning of __init__
        self.pack_start(content_box, True, True, 0) # This one was missing
        self.pack_end(footer, False, False, 0)
        
        # Apply role-based styling to the MessageBubble (self)
        if is_permission_request:
            if permission_pending:
                self.get_style_context().add_class("tool-permission-bubble")
            else:
                self.get_style_context().add_class("assistant-bubble")
        elif message.role == MessageRole.USER:
            self.get_style_context().add_class("user-bubble")
        else:
            self.get_style_context().add_class("assistant-bubble")
        
        # Show all children
        self.show_all()
        
        # Ensure edit container is hidden initially (show_all() overrides the earlier hide())
        if hasattr(self, 'message_edit_container'):
            self.message_edit_container.hide()
        if animate:
            self._start_fade_in()

    def _start_fade_in(self) -> None:
        """Animate newly added bubble to feel less abrupt."""
        try:
            self.set_opacity(0.0)
        except Exception:
            return

        duration_ms = 170
        tick_ms = 16
        total_steps = max(1, duration_ms // tick_ms)
        self._fade_step = 0

        def _tick() -> bool:
            self._fade_step += 1
            opacity = min(1.0, self._fade_step / float(total_steps))
            try:
                self.set_opacity(opacity)
            except Exception:
                return False
            if self._fade_step >= total_steps:
                self._fade_source_id = None
                return False
            return True

        self._fade_source_id = GLib.timeout_add(tick_ms, _tick)

    def _animate_widget_fade_in(
        self,
        widget: Gtk.Widget,
        delay_ms: int = 0,
        duration_ms: int = 170,
    ) -> None:
        """Fade a widget in after an optional delay."""
        try:
            widget.set_opacity(0.0)
        except Exception:
            return

        tick_ms = 16
        total_steps = max(1, int(duration_ms) // tick_ms)
        state = {"step": 0}

        def _tick() -> bool:
            state["step"] += 1
            opacity = min(1.0, state["step"] / float(total_steps))
            try:
                widget.set_opacity(opacity)
            except Exception:
                return False
            return state["step"] < total_steps

        def _start() -> bool:
            GLib.timeout_add(tick_ms, _tick)
            return False

        if delay_ms > 0:
            GLib.timeout_add(int(delay_ms), _start)
        else:
            _start()

    def _is_tool_permission_message(self, message: Message) -> bool:
        """Return True when this message is a tool permission request card."""
        return bool(isinstance(message.meta, dict) and message.meta.get("type") == "tool_permission_request")

    def _is_tool_permission_pending(self, message: Message) -> bool:
        """Return True when permission decision is still pending."""
        if not self._is_tool_permission_message(message):
            return False
        meta = message.meta if isinstance(message.meta, dict) else {}
        return str(meta.get("decision_status", "pending")).strip().lower() == "pending"

    def _build_tool_permission_card(self, meta: dict, animate: bool = True) -> Gtk.Widget:
        """Render interactive inline permission request card."""
        tool_name = str(meta.get("tool_name", "unknown_tool"))
        tool_description = str(meta.get("tool_description", "")).strip()
        explanation = str(meta.get("explanation", "")).strip() or "The assistant is requesting permission to execute a tool."
        args_preview = str(meta.get("args_preview", "")).strip()
        status = str(meta.get("decision_status", "pending")).strip().lower() or "pending"
        allow_always_active = bool(meta.get("allow_always", False))
        deny_reason = str(meta.get("deny_reason", "")).strip()

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("tool-permission-card")
        self._permission_card = card

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name("system-run-symbolic", Gtk.IconSize.BUTTON)
        icon.get_style_context().add_class("tool-permission-icon")
        top.pack_start(icon, False, False, 0)

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label()
        title.set_halign(Gtk.Align.START)
        title.set_xalign(0.0)
        title.set_markup(
            f"<span size='9800' weight='700'>{self._escape_markup(tool_name)}</span>"
        )
        title_col.pack_start(title, False, False, 0)
        if tool_description:
            subtitle = Gtk.Label()
            subtitle.set_halign(Gtk.Align.START)
            subtitle.set_xalign(0.0)
            subtitle.set_line_wrap(True)
            subtitle.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            subtitle.set_markup(
                f"<span size='8800' foreground='#9aa3b2'>{self._escape_markup(tool_description)}</span>"
            )
            title_col.pack_start(subtitle, False, False, 0)
        top.pack_start(title_col, True, True, 0)

        expand_btn = Gtk.Button()
        expand_btn.set_relief(Gtk.ReliefStyle.NONE)
        expand_btn.get_style_context().add_class("thinking-toggle")
        self._permission_expand_btn = expand_btn
        top.pack_end(expand_btn, False, False, 0)
        card.pack_start(top, False, False, 0)

        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        explanation_lbl = Gtk.Label()
        explanation_lbl.set_halign(Gtk.Align.START)
        explanation_lbl.set_xalign(0.0)
        explanation_lbl.set_line_wrap(True)
        explanation_lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        explanation_lbl.set_markup(
            f"<span size='9000'>{self._escape_markup(explanation)}</span>"
        )
        details_box.pack_start(explanation_lbl, False, False, 0)

        if args_preview:
            args_label = Gtk.Label()
            args_label.set_halign(Gtk.Align.START)
            args_label.set_xalign(0.0)
            args_label.set_markup("<span size='8600' weight='600' foreground='#9aa3b2'>Parameters preview</span>")
            details_box.pack_start(args_label, False, False, 0)

            args_view = Gtk.TextView()
            args_view.set_editable(False)
            args_view.set_cursor_visible(False)
            args_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            args_view.get_buffer().set_text(args_preview, -1)
            args_view.get_style_context().add_class("tool-permission-args")

            args_scroll = Gtk.ScrolledWindow()
            args_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            args_scroll.set_hexpand(True)
            args_scroll.set_vexpand(False)
            args_scroll.set_size_request(-1, 120)
            args_scroll.add(args_view)
            details_box.pack_start(args_scroll, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.get_style_context().add_class("tool-permission-actions")

        allow_always = Gtk.CheckButton(label="Allow always")
        allow_always.set_active(allow_always_active)
        allow_always.get_style_context().add_class("tool-permission-toggle")
        self._permission_always_toggle = allow_always
        actions.pack_start(allow_always, False, False, 0)

        actions.pack_start(Gtk.Box(), True, True, 0)

        deny_btn = Gtk.Button.new_with_label("Deny")
        deny_btn.get_style_context().add_class("tool-permission-deny")
        deny_btn.connect("clicked", lambda _btn: self._on_permission_decision("denied", reason=""))
        self._permission_deny_btn = deny_btn
        actions.pack_end(deny_btn, False, False, 0)

        deny_reason_btn = Gtk.Button.new_with_label("Deny with reason")
        deny_reason_btn.get_style_context().add_class("tool-permission-deny")
        deny_reason_btn.connect("clicked", self._on_permission_deny_with_reason_clicked)
        self._permission_deny_reason_btn = deny_reason_btn
        actions.pack_end(deny_reason_btn, False, False, 0)

        allow_btn = Gtk.Button.new_with_label("Allow")
        allow_btn.get_style_context().add_class("tool-permission-allow")
        allow_btn.connect("clicked", lambda _btn: self._on_permission_decision("approved", reason=""))
        self._permission_allow_btn = allow_btn
        actions.pack_end(allow_btn, False, False, 0)

        details_box.pack_start(actions, False, False, 0)

        reason_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        reason_box.get_style_context().add_class("tool-permission-reason-row")

        reason_entry = Gtk.Entry()
        reason_entry.set_placeholder_text("Reason for denying this tool call")
        reason_entry.set_hexpand(True)
        reason_entry.connect("activate", self._on_permission_reason_submit)
        reason_box.pack_start(reason_entry, True, True, 0)
        self._permission_reason_entry = reason_entry

        reason_submit_btn = Gtk.Button.new_with_label("Submit")
        reason_submit_btn.get_style_context().add_class("tool-permission-deny")
        reason_submit_btn.connect("clicked", self._on_permission_reason_submit)
        reason_box.pack_start(reason_submit_btn, False, False, 0)

        reason_cancel_btn = Gtk.Button.new_with_label("Cancel")
        reason_cancel_btn.connect("clicked", self._on_permission_reason_cancel)
        reason_box.pack_start(reason_cancel_btn, False, False, 0)

        self._permission_reason_box = reason_box
        details_box.pack_start(reason_box, False, False, 0)
        reason_box.hide()

        status_lbl = Gtk.Label()
        status_lbl.set_halign(Gtk.Align.START)
        status_lbl.set_xalign(0.0)
        self._permission_status_label = status_lbl
        details_box.pack_start(status_lbl, False, False, 0)

        details_revealer = Gtk.Revealer()
        details_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        details_revealer.set_transition_duration(160)
        details_revealer.add(details_box)
        self._permission_details_revealer = details_revealer
        card.pack_start(details_revealer, False, False, 0)

        def _toggle(_btn):
            if not self._permission_details_revealer:
                return
            next_state = not self._permission_details_revealer.get_reveal_child()
            self._permission_details_revealer.set_reveal_child(next_state)
            icon_name = "pan-up-symbolic" if next_state else "pan-down-symbolic"
            if self._permission_expand_btn:
                self._permission_expand_btn.set_image(
                    Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
                )

        expand_btn.connect("clicked", _toggle)

        self._apply_permission_state(
            status=status,
            allow_always=allow_always_active,
            deny_reason=deny_reason,
        )

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_transition_duration(180)
        revealer.add(card)
        revealer.set_reveal_child(False)
        if animate:
            GLib.idle_add(lambda: revealer.set_reveal_child(True) or False)
        else:
            revealer.set_reveal_child(True)
        return revealer

    def _apply_permission_state(self, status: str, allow_always: bool = False, deny_reason: str = "") -> None:
        """Apply decision state to permission controls."""
        normalized = str(status or "pending").strip().lower()
        pending = normalized == "pending"
        approved = normalized == "approved"
        denied = normalized == "denied"
        if self._permission_details_revealer:
            self._permission_details_revealer.set_reveal_child(pending)
        if self._permission_expand_btn:
            icon_name = "pan-up-symbolic" if pending else "pan-down-symbolic"
            self._permission_expand_btn.set_image(
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            )

        # Switch bubble/card styling from yellow request mode to normal assistant mode once resolved.
        style_ctx = self.get_style_context()
        if pending:
            style_ctx.remove_class("assistant-bubble")
            style_ctx.add_class("tool-permission-bubble")
        else:
            style_ctx.remove_class("tool-permission-bubble")
            style_ctx.add_class("assistant-bubble")
        if self._permission_card:
            card_ctx = self._permission_card.get_style_context()
            if pending:
                card_ctx.remove_class("tool-permission-card-resolved")
            else:
                card_ctx.add_class("tool-permission-card-resolved")

        if self._permission_allow_btn:
            self._permission_allow_btn.set_sensitive(pending)
        if self._permission_deny_btn:
            self._permission_deny_btn.set_sensitive(pending)
        if self._permission_deny_reason_btn:
            self._permission_deny_reason_btn.set_sensitive(pending)
        if self._permission_always_toggle:
            self._permission_always_toggle.set_sensitive(pending)
            if allow_always:
                self._permission_always_toggle.set_active(True)
        if self._permission_reason_box and not pending:
            self._permission_reason_box.hide()
        if self._permission_status_label:
            if pending:
                self._permission_status_label.set_markup(
                    "<span size='8400' foreground='#9aa3b2'>Waiting for your decision.</span>"
                )
            elif approved:
                extra = " (always enabled)" if allow_always else ""
                self._permission_status_label.set_markup(
                    f"<span size='8400' foreground='#74d28f'>Permission granted{extra}.</span>"
                )
            elif denied:
                reason_text = f" Reason: {self._escape_markup(deny_reason)}" if deny_reason else ""
                self._permission_status_label.set_markup(
                    f"<span size='8400' foreground='#f38f8f'>Permission denied.{reason_text}</span>"
                )
            else:
                self._permission_status_label.set_markup(
                    f"<span size='8400' foreground='#9aa3b2'>Status: {self._escape_markup(normalized)}</span>"
                )

    def _on_permission_deny_with_reason_clicked(self, _button) -> None:
        """Show inline reason input for denial."""
        if self._permission_reason_box:
            self._permission_reason_box.show_all()
        if self._permission_reason_entry:
            self._permission_reason_entry.grab_focus()

    def _on_permission_reason_cancel(self, _button) -> None:
        """Hide reason input row without submitting a decision."""
        if self._permission_reason_entry:
            self._permission_reason_entry.set_text("")
        if self._permission_reason_box:
            self._permission_reason_box.hide()

    def _on_permission_reason_submit(self, _widget) -> None:
        """Submit denial decision with a provided reason."""
        reason = ""
        if self._permission_reason_entry:
            reason = self._permission_reason_entry.get_text().strip()
        if not reason:
            return
        self._on_permission_decision("denied", reason=reason)

    def _on_permission_decision(self, decision: str, reason: str = "") -> None:
        """Handle inline permission decision click."""
        allow_always = bool(self._permission_always_toggle and self._permission_always_toggle.get_active())
        if decision == "approved":
            self._apply_permission_state("approved", allow_always=allow_always)
        else:
            self._apply_permission_state("denied", allow_always=False, deny_reason=reason)
        if self.on_tool_permission_decision:
            self.on_tool_permission_decision(self.message.id, decision, allow_always, reason)

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

    def update_max_content_width(self, new_width: int) -> None:
        """Update the maximum width constraint for message content.
        
        Called when the container is resized to make messages adapt to available space.
        """
        if new_width <= 0:
            return
        
        self.max_content_width = new_width
        
        # Update the display widget if it exists (both user labels and assistant text views)
        if hasattr(self, 'message_display_widget') and self.message_display_widget:
            if isinstance(self.message_display_widget, Gtk.Label):
                # Update user message label width
                self.message_display_widget.set_max_width_chars(int(new_width / 5))
            elif hasattr(self.message_display_widget, '_max_width'):
                # Update ClampedTextView (assistant messages)
                self.message_display_widget._max_width = new_width
                self.message_display_widget.queue_resize()

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

    def _build_change_items_from_tool_events(
        self,
        tool_events: list[dict],
        diff_counter,
    ) -> list[dict]:
        """Build per-file addition/removal counters from tool events."""
        per_file: dict[str, dict[str, int]] = {}
        for ev in tool_events:
            details = ev.get("details")
            if not isinstance(details, dict):
                continue
            detail_type = str(details.get("type", ""))
            path = str(details.get("path", "")).strip()
            if not path:
                continue

            additions = 0
            removals = 0
            if detail_type == "file_edit":
                additions, removals = diff_counter(details.get("diff", ""))
            elif detail_type == "file_write":
                preview = str(details.get("content_preview", "") or "")
                additions = len([ln for ln in preview.splitlines() if ln.strip()])
            elif detail_type == "file_delete":
                removals = 1
            else:
                continue

            if additions == 0 and removals == 0:
                continue

            if path not in per_file:
                per_file[path] = {"additions": 0, "removals": 0}
            per_file[path]["additions"] += additions
            per_file[path]["removals"] += removals

        items = [
            {
                "filename": filename,
                "additions": counts["additions"],
                "removals": counts["removals"],
            }
            for filename, counts in per_file.items()
        ]
        items.sort(key=lambda it: str(it.get("filename", "")).lower())
        return items

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

    def _looks_like_agent_activity(self, text: str) -> bool:
        """Detect concatenated agent progress/update blocks."""
        stripped = str(text or "").strip()
        return bool(stripped) and stripped.startswith("[Agent")

    def _parse_agent_activity_entries(self, text: str) -> list[tuple[str, str]]:
        """Split a combined agent message into tagged entries."""
        raw = str(text or "").strip()
        if not raw:
            return []
        chunks = re.split(r"(?=\[Agent(?:\s*-\s*[^\]]+)?\])", raw)
        entries: list[tuple[str, str]] = []
        for chunk in chunks:
            item = chunk.strip()
            if not item:
                continue
            match = re.match(
                r"^\[(?P<tag>Agent(?:\s*-\s*[^\]]+)?)\]\s*(?P<body>.*)$",
                item,
                flags=re.DOTALL,
            )
            if not match:
                continue
            tag = str(match.group("tag") or "Agent").strip()
            body = str(match.group("body") or "").strip()
            if body:
                entries.append((tag, body))
        return entries

    def _format_agent_body_lines(self, body: str) -> list[str]:
        """Render JSON payloads in compact readable lines."""
        stripped = str(body or "").strip()
        if not stripped:
            return []
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict):
                    lines = []
                    for key, value in parsed.items():
                        pretty_key = str(key).replace("_", " ").strip().capitalize()
                        lines.append(f"{pretty_key}: {value}")
                    return lines
            except Exception:
                pass
        return [line.strip() for line in stripped.splitlines() if line.strip()]

    def _build_agent_activity_section(self, text: str) -> Gtk.Box:
        """Render agent updates as a professional timeline-style activity block."""
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.get_style_context().add_class("agent-activity-section")

        header = Gtk.Label()
        header.set_halign(Gtk.Align.START)
        header.set_xalign(0.0)
        header.set_markup("<span size='9700' weight='600' foreground='#b7c2d8'>Agent Activity</span>")
        outer.pack_start(header, False, False, 0)

        entries = self._parse_agent_activity_entries(text)
        animate_from = 0
        if isinstance(self.message.meta, dict):
            try:
                animate_from = max(0, int(self.message.meta.get("agent_activity_animate_from", 0) or 0))
            except Exception:
                animate_from = 0

        if self._animate_enabled:
            self._animate_widget_fade_in(outer, delay_ms=40, duration_ms=350)

        for idx, (tag, body) in enumerate(entries):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            row.get_style_context().add_class("agent-activity-entry")

            tag_markup = self._escape_markup(tag)
            tag_label = Gtk.Label()
            tag_label.set_halign(Gtk.Align.START)
            tag_label.set_xalign(0.0)
            tag_label.set_markup(
                f"<span size='8300' weight='600' foreground='#7fa3cf'>{tag_markup}</span>"
            )
            row.pack_start(tag_label, False, False, 0)

            for line in self._format_agent_body_lines(body):
                line_label = Gtk.Label()
                line_label.set_halign(Gtk.Align.START)
                line_label.set_xalign(0.0)
                line_label.set_line_wrap(True)
                line_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                line_label.set_markup(
                    f"<span size='8900' foreground='#d6deed'>{self._escape_markup(line)}</span>"
                )
                row.pack_start(line_label, False, False, 0)

            outer.pack_start(row, False, False, 0)
            if self._animate_enabled and idx >= animate_from:
                # Only animate newly appended entries; existing ones remain steady.
                delta_idx = idx - animate_from
                self._animate_widget_fade_in(
                    row,
                    delay_ms=120 + (delta_idx * 1050),
                    duration_ms=600,
                )

        return outer


class TypingIndicator(Gtk.Box):
    """Animated typing indicator widget."""

    def __init__(self):
        """Initialize the typing indicator."""
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.get_style_context().add_class("assistant-bubble")
        self.get_style_context().add_class("typing-indicator-bubble")
        
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
        if self.animation_timeout:
            GLib.source_remove(self.animation_timeout)
            self.animation_timeout = None


class StreamingMessageBubble(Gtk.Box):
    """Live assistant bubble that animates streamed text word-by-word."""

    def __init__(
        self,
        stream_id: str,
        max_content_width: int = 700,
        on_text_advanced: Optional[Callable[[], None]] = None,
        word_interval_ms: int = 30,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.stream_id = stream_id
        self.max_content_width = max_content_width
        self._on_text_advanced = on_text_advanced
        self._word_interval_ms = max(16, min(int(word_interval_ms), 40))
        self._display_text = ""
        self._pending_tokens: list[str] = []
        self._animate_source_id = None

        self.set_halign(Gtk.Align.FILL)
        self.set_hexpand(True)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(4)
        self.set_margin_bottom(4)
        self.get_style_context().add_class("assistant-bubble")
        self.get_style_context().add_class("streaming-bubble")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_bottom(4)
        role_label = Gtk.Label()
        role_label.set_halign(Gtk.Align.START)
        role_label.set_markup("<span size='9500' foreground='#8cb4ff' weight='600'>Assistant</span>")
        header.pack_start(role_label, False, False, 0)
        state_label = Gtk.Label()
        state_label.set_markup("<span size='8400' foreground='#7a86a1'>live</span>")
        header.pack_start(state_label, False, False, 0)
        self.pack_start(header, False, False, 0)

        self._label = Gtk.Label()
        self._label.set_halign(Gtk.Align.START)
        self._label.set_xalign(0.0)
        self._label.set_line_wrap(True)
        self._label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._label.set_selectable(True)
        if self.max_content_width > 0:
            self._label.set_max_width_chars(max(48, int(self.max_content_width / 7)))
        self._set_label_markup()
        self.pack_start(self._label, True, True, 0)

        self.show_all()
        self._start_fade_in()

    def _set_label_markup(self) -> None:
        escaped = (
            self._display_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        self._label.set_markup(f"<span size='10300'>{escaped}</span>")

    def append_text(self, chunk: str) -> None:
        """Queue streamed text; animation loop drains at 20-40ms cadence."""
        if not chunk:
            return
        self._pending_tokens.extend(self._tokenize_for_animation(chunk))
        if self._animate_source_id is None:
            self._animate_source_id = GLib.timeout_add(
                self._word_interval_ms,
                self._drain_one_tick,
            )

    def flush(self) -> None:
        """Immediately show any pending text."""
        if self._pending_tokens:
            self._display_text += "".join(self._pending_tokens)
            self._pending_tokens.clear()
            self._set_label_markup()
            if callable(self._on_text_advanced):
                self._on_text_advanced()

    def stop(self) -> None:
        """Stop scheduled animation timers."""
        if self._animate_source_id is not None:
            GLib.source_remove(self._animate_source_id)
            self._animate_source_id = None

    def update_max_content_width(self, new_width: int) -> None:
        if new_width <= 0:
            return
        self.max_content_width = new_width
        self._label.set_max_width_chars(max(48, int(new_width / 7)))

    def _tokenize_for_animation(self, text: str) -> list[str]:
        # Keep whitespace/newlines intact while animating by visible word chunks.
        return re.findall(r"\S+\s*|\n+|[ \t]+", text)

    def _drain_one_tick(self) -> bool:
        if not self._pending_tokens:
            self._animate_source_id = None
            return False

        # Drain more than one token if backlog grows to keep UI responsive.
        drain_count = 1
        if len(self._pending_tokens) > 120:
            drain_count = 4
        elif len(self._pending_tokens) > 50:
            drain_count = 2

        drained = []
        for _ in range(drain_count):
            if not self._pending_tokens:
                break
            drained.append(self._pending_tokens.pop(0))

        if drained:
            self._display_text += "".join(drained)
            self._set_label_markup()
            if callable(self._on_text_advanced):
                self._on_text_advanced()
        return True

    def _start_fade_in(self) -> None:
        try:
            self.set_opacity(0.0)
        except Exception:
            return

        duration_ms = 150
        tick_ms = 16
        total_steps = max(1, duration_ms // tick_ms)
        fade_step = {"value": 0}

        def _tick() -> bool:
            fade_step["value"] += 1
            opacity = min(1.0, fade_step["value"] / float(total_steps))
            try:
                self.set_opacity(opacity)
            except Exception:
                return False
            return fade_step["value"] < total_steps

        GLib.timeout_add(tick_ms, _tick)
