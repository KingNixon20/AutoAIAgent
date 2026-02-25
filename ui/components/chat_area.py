"""
Chat message display area widget.
"""
import os
import gi
from datetime import datetime

from typing import Callable, Optional
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from models import Message, Conversation, ConversationSettings, MessageRole
import constants as C
from ui.components.message_bubble import MessageBubble, TypingIndicator


class ChatArea(Gtk.Box):
    """Displays chat messages in a scrollable area."""

    def __init__(self,
                 on_edit_message_request: Optional[Callable[[str], None]] = None,
                 on_repush_message_request: Optional[Callable[[str], None]] = None,
                 on_delete_message_request: Optional[Callable[[str], None]] = None,
                 on_message_edited_request: Optional[Callable[[str, str], None]] = None): # New callback
        """Initialize the chat area."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._current_conversation = None
        self._context_limit = 4096  # Default context limit
        self._last_date = None
        self._typing_shown = False
        self._loading_chat_settings = False
        self.on_chat_settings_changed = None
        self._global_settings_provider = None
        self._autoscroll_enabled = True
        self._autoscroll_pulses = 0
        self._autoscroll_source_id = None
        self._last_known_container_width = 0  # Track width changes
        self._initial_layout_done = False  # Track if initial layout has been applied
        
        self.on_edit_message_request = on_edit_message_request
        self.on_repush_message_request = on_repush_message_request
        self.on_delete_message_request = on_delete_message_request
        self.on_message_edited_request = on_message_edited_request # Store the new callback
        self._on_message_edited_internal = self._handle_message_edited # Internal handler

        # Chat header
        self.header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.header_box.set_size_request(-1, 64)
        self.header_box.set_margin_start(20)
        self.header_box.set_margin_end(20)
        self.header_box.set_margin_top(8)
        self.header_box.set_margin_bottom(8)

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        title_label = Gtk.Label(label="New Conversation")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_hexpand(True)
        title_label.set_xalign(0.0)
        title_label.set_markup("<span font='bold' size='13000'>New Conversation</span>")
        header_row.pack_start(title_label, True, True, 0)

        self.open_dir_btn = Gtk.Button()
        self.open_dir_btn.set_relief(Gtk.ReliefStyle.NORMAL)
        self.open_dir_btn.set_tooltip_text("Open project directory")
        self.open_dir_btn.set_no_show_all(True)
        folder_icon = Gtk.Image.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON)
        self.open_dir_btn.set_image(folder_icon)
        self.open_dir_btn.connect("clicked", self._on_open_dir_clicked)
        header_row.pack_end(self.open_dir_btn, False, False, 0)

        self.chat_settings_btn = Gtk.Button()
        self.chat_settings_btn.set_relief(Gtk.ReliefStyle.NORMAL)
        self.chat_settings_btn.set_tooltip_text("Per-chat settings overrides")
        settings_icon = Gtk.Image.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        self.chat_settings_btn.set_image(settings_icon)
        header_row.pack_end(self.chat_settings_btn, False, False, 0)

        subtitle_label = Gtk.Label(label="")
        subtitle_label.set_halign(Gtk.Align.START)
        subtitle_label.set_xalign(0.0)
        subtitle_label.set_markup("<span size='9000' foreground='#808080'>Loading...</span>")

        self._title_label = title_label
        self._subtitle_label = subtitle_label

        self.header_box.pack_start(header_row, False, False, 0)
        self.header_box.pack_start(subtitle_label, False, False, 0)
        self.add(self.header_box)

        # Build per-chat settings popover
        self._build_chat_settings_popover()

        # Messages container with scrolling
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        # Prevent horizontal scrolling - messages should wrap, not scroll horizontally
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.messages_box.set_homogeneous(False)
        self.messages_box.set_hexpand(True)
        self.messages_box.set_halign(Gtk.Align.FILL)
        # Don't set a fixed size_request - let content expand to fill available space
        # Messages will be constrained by their max-width to prevent excessive line lengths
        self.messages_box.set_size_request(-1, -1)

        scrolled.add(self.messages_box)
        self.add(scrolled)

        self.scrolled = scrolled
        self.messages_box.connect("size-allocate", self._on_messages_size_allocate)
        # Connect to ChatArea's own size-allocate to fix initial layout on app launch
        self.connect("size-allocate", self._on_chat_area_size_allocate)

    def get_message_bubble_by_id(self, message_id: str) -> Optional[MessageBubble]:
        """Finds and returns a MessageBubble widget by its associated message ID."""
        for child in self.messages_box.get_children():
            if isinstance(child, MessageBubble) and child.message.id == message_id:
                return child
        return None

    def edit_message_bubble(self, message_id: str) -> None:
        """Puts a specific message bubble into edit mode."""
        bubble = self.get_message_bubble_by_id(message_id)
        if bubble and bubble.message.role == MessageRole.USER:
            bubble.set_edit_mode(True)
            self._autoscroll_enabled = False # Disable autoscroll while editing

    def _handle_message_edited(self, message_id: str, new_content: str) -> None:
        """Handles the event when a message bubble's content has been edited."""
        if not self._current_conversation:
            return

        edited_message_index = -1
        for i, message in enumerate(self._current_conversation.messages):
            if message.id == message_id:
                edited_message_index = i
                break

        if edited_message_index == -1:
            print(f"Error: Message with ID {message_id} not found for editing.")
            return

        # 1. Update the message content in the conversation object
        self._current_conversation.messages[edited_message_index].content = new_content
        self._current_conversation.messages[edited_message_index].timestamp = datetime.now() # Update timestamp

        # 2. Remove all subsequent messages from the conversation object
        self._current_conversation.messages = self._current_conversation.messages[:edited_message_index + 1]

        # 3. Remove all subsequent MessageBubble widgets from the display
        children_to_remove = []
        for i, child in enumerate(self.messages_box.get_children()):
            if isinstance(child, MessageBubble) and child.message.id == message_id:
                # All children after this one (and potentially including date separators)
                children_to_remove = self.messages_box.get_children()[i+1:]
                break
        
        for child in children_to_remove:
            self.messages_box.remove(child)
        
        # 4. Re-enable autoscroll
        self._autoscroll_enabled = True

        # 5. Trigger the re-iteration (callback to main window)
        if self.on_message_edited_request:
            self.on_message_edited_request(message_id, new_content)
        
        # Re-display the updated message bubble to reflect new content (and potentially new token count)
        # We need to find the bubble again as the children list might have changed
        updated_bubble = self.get_message_bubble_by_id(message_id)
        if updated_bubble:
            # For user messages, the content is rendered as a Gtk.Label inside the bubble
            # We need to update this label
            if updated_bubble.message.role == MessageRole.USER and hasattr(updated_bubble, 'message_display_widget'):
                escaped = (
                    new_content.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                updated_bubble.message_display_widget.set_markup(f"<span size='11000'>{escaped}</span>")
            # Update token count
            for child in updated_bubble.get_children():
                if isinstance(child, Gtk.Box) and child.get_style_context().has_class("message-actions"):
                    # Assuming token label is part of the footer, which is packed before action buttons
                    # This is a bit brittle, might need a more robust way to find the token label
                    footer_children = child.get_parent().get_children()
                    for f_child in footer_children:
                        if isinstance(f_child, Gtk.Label) and "token(s)" in f_child.get_text():
                            f_child.set_markup(f"<span size='8200' foreground='#9a9a9a'>{updated_bubble._message_token_count(updated_bubble.message):,} token(s)</span>")
                            break
            updated_bubble.message.content = new_content # Ensure message object is updated
            updated_bubble.show_all()
        
        self._update_subtitle() # Update context token count in subtitle
        self._request_scroll_to_bottom(8)


    def set_global_settings_provider(self, provider) -> None:
        """Set callable returning current global settings."""
        self._global_settings_provider = provider

    def set_conversation(self, conversation: Conversation, context_limit: int = 4096) -> None:
        """Set the active conversation and display its messages.

        Args:
            conversation: The conversation to display.
            context_limit: The context token limit for this conversation.
        """
        # Clear existing messages
        for child in list(self.messages_box.get_children()):
            self.messages_box.remove(child)
        self._typing_shown = False
        if hasattr(self, "_typing_indicator_widget"):
            del self._typing_indicator_widget
        
        # Reset initial layout flag so new conversation gets proper width
        self._initial_layout_done = False

        # Store conversation and context limit
        self._current_conversation = conversation
        self._context_limit = context_limit

        # Update header
        self._title_label.set_label(conversation.title)
        self._update_subtitle()

        # Sync popover controls to current conversation
        self._load_chat_settings_into_ui()

        # Show/hide open dir button based on agent_config
        self._update_open_dir_button()

        # Add messages
        self._last_date = None
        # Messages will automatically calculate their width based on available space
        # When added, each message will use the current container width or a fallback
        # As the layout resizes, all messages will adapt via _update_message_widths_for_container

        for message in conversation.messages:
            # Don't pass width - let add_message calculate it dynamically
            self.add_message(message, animate=False)

        # Auto scroll to bottom
        self._request_scroll_to_bottom(8)
        
        # Schedule width fixup after initial layout - this ensures messages get correct width
        # on app launch before they're rendered
        GLib.idle_add(self._schedule_width_fixup)

    def set_context_limit(self, context_limit: int) -> None:
        """Update context limit for subtitle rendering."""
        self._context_limit = context_limit
        self._update_subtitle()

    def add_message(self, message: Message, animate: bool = True, max_content_width: int = -1) -> None:
        """Add a message to the display.

        Args:
            message: The message to add.
            animate: Whether to animate the message appearance.
            max_content_width: Optional. The maximum width for the message content.
        """
        # Add date separator if needed
        current_date = message.timestamp.date()
        if self._last_date != current_date:
            self._add_date_separator(current_date)
            self._last_date = current_date

        calculated_width = max_content_width
        if calculated_width == -1: # If not passed, calculate it
            # Account for MessageBubble's set_margin_start(20) and set_margin_end(20)
            allocated_width = self.messages_box.get_allocated_width()
            total_horizontal_margins = 20 + 20
            
            # Use actual allocated space if available, otherwise a conservative fallback
            if allocated_width > 1:
                calculated_width = allocated_width - total_horizontal_margins
            else:
                # Fallback: use 550px (conservative) - will be corrected by _schedule_width_fixup
                calculated_width = 550
            
            # Cap to CHAT_MAX_WIDTH to prevent excessively long lines
            calculated_width = min(calculated_width, C.CHAT_MAX_WIDTH)
            
            # Ensure minimum reasonable width
            if calculated_width < 400:
                calculated_width = 400

        # Create and add message bubble
        bubble = MessageBubble(
            message,
            on_edit_message=self.on_edit_message_request,
            on_repush_message=self.on_repush_message_request,
            on_delete_message=self.on_delete_message_request,
            on_message_edited=self.on_message_edited_request, # Pass the new callback
            max_content_width=calculated_width,
        )
        self.messages_box.add(bubble)
        bubble.show()  # Show bubble itself, not all children recursively
        # If it's a user message, ensure edit container stays hidden
        if message.role == MessageRole.USER and hasattr(bubble, 'message_edit_container'):
            bubble.message_edit_container.hide()

        # Update context display
        self._update_subtitle()

        # Auto scroll to bottom
        self._request_scroll_to_bottom(10)

    def show_typing_indicator(self) -> None:
        """Show the typing indicator."""
        if not self._typing_shown:
            indicator = TypingIndicator()
            self._typing_indicator_widget = indicator
            self.messages_box.add(indicator)
            self._typing_shown = True
            self._request_scroll_to_bottom(8)

    def hide_typing_indicator(self) -> None:
        """Hide the typing indicator."""
        if self._typing_shown and hasattr(self, "_typing_indicator_widget"):
            # Stop animation before removing
            if hasattr(self._typing_indicator_widget, "stop_animation"):
                self._typing_indicator_widget.stop_animation()
            self.messages_box.remove(self._typing_indicator_widget)
            del self._typing_indicator_widget
        self._typing_shown = False
        self._request_scroll_to_bottom(4)

    def clear(self) -> None:
        """Clear all messages from the display."""
        # Stop typing indicator animation if active
        if hasattr(self, "_typing_indicator_widget"):
            if hasattr(self._typing_indicator_widget, "stop_animation"):
                self._typing_indicator_widget.stop_animation()
            del self._typing_indicator_widget

        for child in list(self.messages_box.get_children()):
            self.messages_box.remove(child)
        self._last_date = None
        self._typing_shown = False
        self._current_conversation = None

    def _build_chat_settings_popover(self) -> None:
        """Create per-chat popout settings controls."""
        self.chat_settings_popover = Gtk.Popover.new(self.chat_settings_btn)
        self.chat_settings_popover.set_border_width(10)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_size_request(360, 420)

        title = Gtk.Label()
        title.set_halign(Gtk.Align.START)
        title.set_markup("<span weight='600'>Per-Chat Overrides</span>")
        outer.pack_start(title, False, False, 0)

        hint = Gtk.Label()
        hint.set_halign(Gtk.Align.START)
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.set_markup("<span size='9000' foreground='#909090'>These settings apply only to the current conversation and override global settings.</span>")
        outer.pack_start(hint, False, False, 0)

        enable_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        enable_label = Gtk.Label(label="Enable per-chat overrides")
        enable_label.set_halign(Gtk.Align.START)
        enable_label.set_hexpand(True)
        enable_label.set_xalign(0.0)
        self.chat_override_switch = Gtk.Switch()
        self.chat_override_switch.connect("notify::active", self._on_chat_setting_changed)
        enable_row.pack_start(enable_label, True, True, 0)
        enable_row.pack_end(self.chat_override_switch, False, False, 0)
        outer.pack_start(enable_row, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(4)

        self.chat_temp = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1)
        self.chat_temp.set_digits(2)
        self.chat_temp.set_draw_value(True)
        self.chat_temp.connect("value-changed", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Temperature", self.chat_temp)

        self.chat_top_p = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self.chat_top_p.set_digits(2)
        self.chat_top_p.set_draw_value(True)
        self.chat_top_p.connect("value-changed", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Top P", self.chat_top_p)

        self.chat_rep_penalty = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1)
        self.chat_rep_penalty.set_digits(2)
        self.chat_rep_penalty.set_draw_value(True)
        self.chat_rep_penalty.connect("value-changed", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Repetition Penalty", self.chat_rep_penalty)

        self.chat_max_tokens = Gtk.SpinButton()
        self.chat_max_tokens.set_range(1, 32000)
        self.chat_max_tokens.set_increments(64, 256)
        self.chat_max_tokens.connect("value-changed", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Max Tokens", self.chat_max_tokens)

        self.chat_context_limit = Gtk.SpinButton()
        self.chat_context_limit.set_range(256, 32000)
        self.chat_context_limit.set_increments(256, 1024)
        self.chat_context_limit.connect("value-changed", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Context Limit", self.chat_context_limit)

        self.chat_token_saver = Gtk.CheckButton(label="Compress history (token saver)")
        self.chat_token_saver.connect("toggled", self._on_chat_setting_changed)
        self._add_popover_setting(content, "Token Saver", self.chat_token_saver)

        prompt_label = Gtk.Label()
        prompt_label.set_halign(Gtk.Align.START)
        prompt_label.set_xalign(0.0)
        prompt_label.set_markup("<span size='10500'>System Prompt</span>")
        content.pack_start(prompt_label, False, False, 0)

        prompt_scrolled = Gtk.ScrolledWindow()
        prompt_scrolled.set_size_request(-1, 130)
        self.chat_system_prompt = Gtk.TextView()
        self.chat_system_prompt.set_wrap_mode(Gtk.WrapMode.WORD)
        prompt_buf = self.chat_system_prompt.get_buffer()
        prompt_buf.connect("changed", self._on_chat_setting_changed)
        prompt_scrolled.add(self.chat_system_prompt)
        content.pack_start(prompt_scrolled, False, False, 0)

        scrolled.add(content)
        outer.pack_start(scrolled, True, True, 0)

        self.chat_settings_btn.connect("clicked", self._on_chat_settings_clicked)

        self.chat_settings_popover.add(outer)
        outer.show_all()
        self.chat_settings_popover.hide()

    def _on_chat_settings_clicked(self, *_args) -> None:
        if hasattr(self.chat_settings_popover, "popup"):
            self.chat_settings_popover.popup()
        else:
            self.chat_settings_popover.show_all()

    def _add_popover_setting(self, container: Gtk.Box, label_text: str, control: Gtk.Widget) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_xalign(0.0)
        row.pack_start(label, False, False, 0)
        row.pack_start(control, False, False, 0)
        container.pack_start(row, False, False, 0)

    def _load_chat_settings_into_ui(self) -> None:
        """Load current conversation chat-settings into popover controls."""
        self._loading_chat_settings = True
        try:
            global_settings = self._get_global_settings()
            raw = {}
            if self._current_conversation and isinstance(self._current_conversation.chat_settings, dict):
                raw = self._current_conversation.chat_settings

            enabled = bool(raw.get("enabled", False))
            self.chat_override_switch.set_active(enabled)

            self.chat_temp.set_value(float(raw.get("temperature", global_settings.temperature)))
            self.chat_top_p.set_value(float(raw.get("top_p", global_settings.top_p)))
            self.chat_rep_penalty.set_value(float(raw.get("repetition_penalty", global_settings.repetition_penalty)))
            self.chat_max_tokens.set_value(int(raw.get("max_tokens", global_settings.max_tokens)))
            self.chat_context_limit.set_value(int(raw.get("context_limit", global_settings.context_limit)))
            self.chat_token_saver.set_active(bool(raw.get("token_saver", global_settings.token_saver)))

            system_prompt = str(raw.get("system_prompt", global_settings.system_prompt))
            buffer = self.chat_system_prompt.get_buffer()
            buffer.set_text(system_prompt, -1)

            self._set_chat_settings_widgets_sensitive(enabled)
        finally:
            self._loading_chat_settings = False

    def _set_chat_settings_widgets_sensitive(self, enabled: bool) -> None:
        self.chat_temp.set_sensitive(enabled)
        self.chat_top_p.set_sensitive(enabled)
        self.chat_rep_penalty.set_sensitive(enabled)
        self.chat_max_tokens.set_sensitive(enabled)
        self.chat_context_limit.set_sensitive(enabled)
        self.chat_token_saver.set_sensitive(enabled)
        self.chat_system_prompt.set_sensitive(enabled)

    def _on_chat_setting_changed(self, *_args) -> None:
        if self._loading_chat_settings:
            return

        enabled = self.chat_override_switch.get_active()
        self._set_chat_settings_widgets_sensitive(enabled)

        if not self._current_conversation:
            return

        payload = self.get_chat_settings_payload()
        self._current_conversation.chat_settings = payload

        if self.on_chat_settings_changed:
            self.on_chat_settings_changed(self._current_conversation, payload)

    def get_chat_settings_payload(self) -> dict:
        """Collect per-chat override payload from UI."""
        prompt_buf = self.chat_system_prompt.get_buffer()
        start, end = prompt_buf.get_bounds()
        prompt_text = prompt_buf.get_text(start, end, False)
        return {
            "enabled": self.chat_override_switch.get_active(),
            "temperature": self.chat_temp.get_value(),
            "top_p": self.chat_top_p.get_value(),
            "repetition_penalty": self.chat_rep_penalty.get_value(),
            "max_tokens": int(self.chat_max_tokens.get_value()),
            "context_limit": int(self.chat_context_limit.get_value()),
            "token_saver": self.chat_token_saver.get_active(),
            "system_prompt": prompt_text,
        }

    def _get_global_settings(self) -> ConversationSettings:
        if callable(self._global_settings_provider):
            settings = self._global_settings_provider()
            if isinstance(settings, ConversationSettings):
                return settings
        return ConversationSettings()

    def _update_subtitle(self) -> None:
        """Update the subtitle with model and context usage information."""
        if not self._current_conversation:
            return

        # Calculate context tokens
        context_tokens = self._current_conversation.estimate_context_tokens(
            model=self._current_conversation.model
        )

        # Color code based on usage percentage
        usage_percent = (context_tokens / self._context_limit * 100) if self._context_limit > 0 else 0

        # Choose color based on usage
        if usage_percent > 90:
            color = "#FF5252"  # Red - critical
        elif usage_percent > 70:
            color = "#FFA726"  # Orange - warning
        else:
            color = "#00E676"  # Green - good

        # Format the subtitle
        subtitle = (
            f"Model: {self._current_conversation.model} • "
            f"<span foreground='{color}'>Context: {context_tokens:,} / {self._context_limit:,} tokens</span>"
        )
        self._subtitle_label.set_markup(f"<span size='10000'>{subtitle}</span>")

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

    def _on_messages_size_allocate(self, widget, allocation) -> None:
        """Update message widths when container is resized and keep viewport pinned."""
        # Recalculate message widths if container width changed
        # This makes the chat adapt when sidebar/tools panels are resized
        current_width = allocation.width if allocation else 0
        if current_width > 1 and current_width != self._last_known_container_width:
            self._last_known_container_width = current_width
            self._update_message_widths_for_container(current_width)
        
        # Keep viewport pinned to newest message as content grows
        if self._autoscroll_enabled:
            self._request_scroll_to_bottom(3)
    
    def _on_chat_area_size_allocate(self, widget, allocation) -> None:
        """Handle ChatArea's initial layout - fixes width on app launch.
        
        On application launch, the widget doesn't have a real width until after
        the initial size-allocate. This ensures messages get correct widths.
        """
        if not self._initial_layout_done and allocation.width > 1:
            self._initial_layout_done = True
            # Now that we have a real width, update all messages
            self._update_message_widths_for_container(allocation.width)
    
    def _schedule_width_fixup(self) -> bool:
        """Deferred callback to fix message widths after initial layout.
        
        This is called via idle_add to ensure GTK has completed the initial layout
        before we try to update message widths.
        """
        # Get the actual allocated width from messages_box
        allocated_width = self.messages_box.get_allocated_width()
        if allocated_width > 1:
            self._update_message_widths_for_container(allocated_width)
        else:
            # If still not allocated, try again next iteration
            return True
        return False
    
    def _update_message_widths_for_container(self, container_width: int) -> None:
        """Update all message bubble widths to fit the current container width."""
        if container_width <= 1:
            return
        
        total_horizontal_margins = 20 + 20  # MessageBubble's own margins
        new_width = container_width - total_horizontal_margins
        new_width = min(new_width, C.CHAT_MAX_WIDTH)  # Cap to sensible max
        new_width = max(new_width, 400)  # Ensure minimum
        
        # Update all message bubbles with the new width
        for child in self.messages_box.get_children():
            if isinstance(child, MessageBubble):
                child.update_max_content_width(new_width)

    def _request_scroll_to_bottom(self, pulses: int = 6) -> None:
        """Schedule repeated bottom-scroll ticks to handle delayed layout updates."""
        if pulses > self._autoscroll_pulses:
            self._autoscroll_pulses = pulses
        if self._autoscroll_source_id is None:
            self._autoscroll_source_id = GLib.timeout_add(16, self._autoscroll_tick)

    def _autoscroll_tick(self) -> bool:
        """Autoscroll tick; keeps following newest message until pulses exhaust."""
        adj = self.scrolled.get_vadjustment()
        if adj: # Check if adjustment exists
            adj.set_value(adj.get_upper() - adj.get_page_size())
        self._autoscroll_pulses -= 1
        if self._autoscroll_pulses > 0:
            return True
        self._autoscroll_source_id = None
        return False

    def _update_open_dir_button(self) -> None:
        """Show/hide the open dir button based on whether project directory exists."""
        if not self._current_conversation:
            self.open_dir_btn.hide()
            return
        
        agent_config = self._current_conversation.agent_config
        if agent_config and isinstance(agent_config, dict):
            project_dir = agent_config.get("project_dir")
            if project_dir and os.path.isdir(project_dir):
                self.open_dir_btn.show()
                self.open_dir_btn.set_tooltip_text(f"Open project directory: {project_dir}")
                return
        
        self.open_dir_btn.hide()

    def _on_open_dir_clicked(self, button) -> None:
        """Open the project directory in the file browser."""
        if not self._current_conversation:
            return
        
        agent_config = self._current_conversation.agent_config
        if not agent_config or not isinstance(agent_config, dict):
            return
        
        project_dir = agent_config.get("project_dir")
        if not project_dir or not os.path.isdir(project_dir):
            return
        
        self._open_directory_in_file_browser(project_dir)

    def _open_directory_in_file_browser(self, directory: str) -> None:
        """Open a directory in the system file browser."""
        import subprocess
        import sys
        
        try:
            if sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", directory])
            elif sys.platform == "win32":  # Windows
                subprocess.Popen(["explorer", directory])
            else:  # Linux and other Unix-like systems
                subprocess.Popen(["xdg-open", directory])
        except Exception as e:
            print(f"Failed to open directory: {e}")
