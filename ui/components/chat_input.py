"""
Chat input widget for user message composition.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib


class ChatInput(Gtk.Box):
    """Chat input area with text view and send button."""

    def __init__(self):
        """Initialize the chat input widget."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(8)
        self.set_margin_bottom(10)
        
        # Input wrapper box - horizontal layout with text and button
        input_wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_wrapper.set_homogeneous(False)
        input_wrapper.get_style_context().add_class("input-wrapper")
        
        # Text view with scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_can_focus(False)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(84)
        scrolled.set_vexpand(False)
        scrolled.set_hexpand(True)
        scrolled.set_shadow_type(Gtk.ShadowType.NONE)
        scrolled.set_margin_start(0)
        scrolled.set_margin_end(0)
        scrolled.get_style_context().add_class("chat-input-scroll")
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(6)
        self.text_view.set_bottom_margin(6)
        self.text_view.set_accepts_tab(False)
        self.text_view.get_style_context().add_class("chat-input-text")
        scrolled.add(self.text_view)
        
        input_wrapper.pack_start(scrolled, True, True, 0)
        
        # Send button - compact and properly positioned
        self.send_button = Gtk.Button(label="")
        self._send_icon = Gtk.Image.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self._stop_icon = Gtk.Image.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self.send_button.set_image(self._send_icon)
        self.send_button.set_tooltip_text("Send message")
        self.send_button.set_sensitive(False)
        self.send_button.set_size_request(28, 28)
        self.send_button.set_halign(Gtk.Align.END)
        self.send_button.set_valign(Gtk.Align.CENTER)
        self.send_button.get_style_context().add_class("primary")
        self.send_button.get_style_context().add_class("send-button-small")
        input_wrapper.pack_end(self.send_button, False, False, 0)
        
        # mark this widget with the input-container styling so it is visible
        self.get_style_context().add_class("input-container")
        self.pack_start(input_wrapper, False, False, 0)
        
        # Status bar
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_margin_top(6)
        status_box.get_style_context().add_class("model-status-bar")
        
        # Status indicator dot
        self.status_dot = Gtk.Box()
        self.status_dot.set_size_request(6, 6)
        self.status_dot.get_style_context().add_class("status-active")
        status_box.pack_start(self.status_dot, False, False, 0)

        # Mode selector (left of connection status)
        mode_label = Gtk.Label(label="Mode")
        mode_label.set_markup("<span size='9000' foreground='#8a8a8a'>Mode</span>")
        mode_label.set_halign(Gtk.Align.START)
        status_box.pack_start(mode_label, False, False, 4)

        self.mode_combo = Gtk.ComboBoxText()
        self.mode_combo.append("ask", "Ask")
        self.mode_combo.append("plan", "Plan")
        self.mode_combo.append("agent", "Agent")
        self.mode_combo.set_active_id("ask")
        self.mode_combo.set_tooltip_text(
            "Ask: normal chat\nPlan: generate task plan and store in AI Tasks\nAgent: execute using saved tasks and tools"
        )
        status_box.pack_start(self.mode_combo, False, False, 0)

        # Status label
        self.status_label = Gtk.Label(label="Connected · Ready")
        self.status_label.set_markup("<span size='10000' foreground='#808080'>Connected · Ready</span>")
        self.status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(self.status_label, False, False, 0)
        
        # Refresh connection button (only shown when disconnected)
        self.refresh_button = Gtk.Button()
        refresh_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_button.set_image(refresh_icon)
        self.refresh_button.set_tooltip_text("Retry connection to LM Studio")
        self.refresh_button.set_relief(Gtk.ReliefStyle.NONE)
        self.refresh_button.set_no_show_all(True)  # Hidden by default
        self.refresh_button.hide()
        status_box.pack_start(self.refresh_button, False, False, 0)
        
        self._api_client = None
        self._refresh_callback = None
        self._generation_active = False
        self._state_anim_source_id = None
        
        # Autoscroll checkbox on the right side
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        status_box.pack_start(spacer, True, True, 0)
        
        self.autoscroll_check = Gtk.CheckButton(label="Autoscroll")
        self.autoscroll_check.set_active(True)
        self.autoscroll_check.set_halign(Gtk.Align.END)
        self.autoscroll_check.set_margin_end(4)
        status_box.pack_end(self.autoscroll_check, False, False, 0)
        
        self.pack_start(status_box, False, False, 0)
        
        # Connect text buffer signals for send button state
        self.text_buffer = self.text_view.get_buffer()
        self.text_buffer.connect("changed", self._on_text_changed)
        self.text_view.connect("key-press-event", self._on_text_key_press)

    def _on_text_changed(self, buffer):
        """Update send button state based on text content."""
        self._refresh_send_button_state()

    def _refresh_send_button_state(self) -> None:
        """Refresh send/stop button sensitivity from current state."""
        if self._generation_active:
            self.send_button.set_sensitive(True)
            return
        has_text = self.text_buffer.get_char_count() > 0
        self.send_button.set_sensitive(has_text)

    def set_generation_active(self, active: bool) -> None:
        """Switch send button between Send and Stop states."""
        active = bool(active)
        if self._generation_active == active:
            self._refresh_send_button_state()
            return
        self._generation_active = active
        self._animate_button_state_swap()
        self._refresh_send_button_state()

    def is_generation_active(self) -> bool:
        """Return whether the input is in generating (Stop) state."""
        return self._generation_active

    def _apply_button_state_now(self) -> None:
        """Apply the current visual state without animation."""
        ctx = self.send_button.get_style_context()
        if self._generation_active:
            self.send_button.set_image(self._stop_icon)
            self.send_button.set_tooltip_text("Stop generation")
            ctx.remove_class("primary")
            ctx.add_class("stop-button")
        else:
            self.send_button.set_image(self._send_icon)
            self.send_button.set_tooltip_text("Send message")
            ctx.remove_class("stop-button")
            ctx.add_class("primary")

    def _animate_button_state_swap(self) -> None:
        """Fade button out, swap icon/style, and fade back in."""
        if self._state_anim_source_id:
            GLib.source_remove(self._state_anim_source_id)
            self._state_anim_source_id = None

        steps = {"value": 0}
        total_steps = 6
        tick_ms = 16

        def _tick() -> bool:
            steps["value"] += 1
            progress = steps["value"] / float(total_steps)
            if progress < 0.5:
                self.send_button.set_opacity(max(0.0, 1.0 - (progress * 2.0)))
            elif progress < 0.67:
                self._apply_button_state_now()
                self.send_button.set_opacity(0.0)
            else:
                self.send_button.set_opacity(min(1.0, (progress - 0.5) * 2.0))

            if steps["value"] >= total_steps:
                self.send_button.set_opacity(1.0)
                self._apply_button_state_now()
                self._state_anim_source_id = None
                return False
            return True

        self._state_anim_source_id = GLib.timeout_add(tick_ms, _tick)

    def get_text(self) -> str:
        """Get the current input text.
        
        Returns:
            The text from the input field.
        """
        start, end = self.text_buffer.get_bounds()
        return self.text_buffer.get_text(start, end, False)

    def set_text(self, text: str) -> None:
        """Set the content of the input field.
        
        Args:
            text: The text to set in the input field.
        """
        self.text_buffer.set_text(text, -1)

    def clear(self) -> None:
        """Clear the input field."""
        self.text_buffer.set_text("", -1)

    def focus(self) -> None:
        """Focus the text view."""
        self.text_view.grab_focus()

    def set_api_client(self, api_client) -> None:
        """Set the API client for connection status monitoring.
        
        Args:
            api_client: The LMStudioClient instance.
        """
        self._api_client = api_client

    def update_connection_status(self, connected: bool, message: str = "") -> None:
        """Backward-compatible alias used by main window to update connection state.

        Args:
            connected: Whether the API is connected.
            message: Optional status message to display.
        """
        # Forward to the existing `set_model_status` implementation.
        self.set_model_status(connected, message)

    def set_model_status(self, connected: bool, message: str = "") -> None:
        """Update the connection status display.
        
        Args:
            connected: Whether the API is connected.
            message: Optional custom message to display. Defaults to generic message.
        """
        if connected:
            msg = message or "Connected · Ready"
            color = "#00E676"  # Green
            self.status_dot.get_style_context().add_class("status-active")
            self.status_dot.get_style_context().remove_class("status-inactive")
            self.refresh_button.hide()  # Hide refresh button when connected
        else:
            msg = message or "Disconnected · LM Studio"
            color = "#FF5252"  # Red
            self.status_dot.get_style_context().remove_class("status-active")
            self.status_dot.get_style_context().add_class("status-inactive")
            self.refresh_button.show()  # Show refresh button when disconnected
        
        self.status_label.set_markup(f"<span size='10000' foreground='{color}'>{msg}</span>")

    def connect_send(self, callback):
        """Connect the send button click signal.
        
        Args:
            callback: Function to call when send is clicked.
        """
        self.send_button.connect("clicked", callback)

    def connect_mode_changed(self, callback):
        """Connect mode selector changed signal."""
        self.mode_combo.connect("changed", callback)

    def _on_text_key_press(self, _widget, event) -> bool:
        """Handle Enter/Shift+Enter behavior in the message input."""
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            # Let TextView insert a newline.
            return False
        if self._generation_active:
            # Ignore Enter while generating; stop is explicit via button.
            return True
        # Plain Enter sends message.
        if self.send_button.get_sensitive():
            self.send_button.clicked()
        return True

    def is_autoscroll_enabled(self) -> bool:
        """Check if autoscroll is enabled.
        
        Returns:
            True if autoscroll checkbox is checked, False otherwise.
        """
        return self.autoscroll_check.get_active()

    def get_mode(self) -> str:
        """Get current assistant mode: ask, plan, or agent."""
        mode = self.mode_combo.get_active_id()
        if mode in ("ask", "plan", "agent"):
            return mode
        return "ask"

    def set_mode(self, mode: str) -> None:
        """Set current assistant mode."""
        normalized = str(mode or "ask").strip().lower()
        if normalized not in ("ask", "plan", "agent"):
            normalized = "ask"
        self.mode_combo.set_active_id(normalized)

    def connect_refresh(self, callback):
        """Connect the refresh button click signal.
        
        Args:
            callback: Function to call when refresh is clicked.
        """
        self._refresh_callback = callback
        self.refresh_button.connect("clicked", lambda btn: callback())

    def connect_autoscroll_changed(self, callback):
        """Connect autoscroll toggle changed signal."""
        self.autoscroll_check.connect("toggled", callback)
