"""
Full-screen settings overlay window.
Opens above the main chat interface with tabbed configuration UI.
"""
import gi
import json

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

from models import ConversationSettings
from storage import (
    save_app_mcp_server,
    load_app_mcp_servers,
    delete_app_mcp_server,
)
import constants as C


class SettingsWindow(Gtk.Box):
    """Full overlay settings window with tabs and all controls visible."""

    def __init__(self):
        """Initialize the settings window."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.get_style_context().add_class("settings-panel")
        
        self._system_prompt_text = C.DEFAULT_SYSTEM_PROMPT
        self._model_settings_state = {
            "temperature": C.DEFAULT_TEMPERATURE,
            "top_p": C.DEFAULT_TOP_P,
            "repetition_penalty": C.DEFAULT_REPETITION_PENALTY,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "max_tokens": C.DEFAULT_MAX_TOKENS,
            "seed_enabled": False,
            "seed": 0,
            "stop_sequences": "",
            "context_limit": C.DEFAULT_CONTEXT_LIMIT,
            "include_system_prompt": True,
            "token_saver": bool(getattr(C, "DEFAULT_TOKEN_SAVER", False)),
            "auto_tool_approval": False,
        }
        self.on_mcp_servers_changed = None
        self._active_scrolled = None

        # Header with title and close button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(14)
        header.set_margin_bottom(14)

        title = Gtk.Label(label="Settings")
        title.set_markup("<span font='bold' size='16000'>Settings</span>")
        title.set_halign(Gtk.Align.START)
        title.set_hexpand(True)
        header.pack_start(title, True, True, 0)

        self.close_btn = Gtk.Button()
        close_icon = Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        self.close_btn.set_image(close_icon)
        self.close_btn.set_tooltip_text("Close settings")
        header.pack_end(self.close_btn, False, False, 0)

        self.add(header)
        self.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Tab buttons
        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.set_margin_start(12)
        tab_bar.set_margin_end(12)
        tab_bar.set_margin_top(8)
        tab_bar.set_margin_bottom(8)
        tab_bar.set_homogeneous(True)

        self.settings_tab = Gtk.Button(label="Model")
        self.settings_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.settings_tab, True, True, 0)

        self.prompt_tab = Gtk.Button(label="System")
        self.prompt_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.prompt_tab, True, True, 0)

        self.stats_tab = Gtk.Button(label="Stats")
        self.stats_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.stats_tab, True, True, 0)

        self.mcp_tab = Gtk.Button(label="MCP")
        self.mcp_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.mcp_tab, True, True, 0)

        self.add(tab_bar)
        self.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Content area
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content_box.set_vexpand(True)
        self.content_box.set_hexpand(True)
        self.add(self.content_box)

        # Show Model tab by default
        self._show_settings_tab()
        self._set_tab_active(self.settings_tab)

        # Tab switching
        self.settings_tab.connect("clicked", self._switch_tabs_settings)
        self.prompt_tab.connect("clicked", self._switch_tabs_prompt)
        self.stats_tab.connect("clicked", self._switch_tabs_stats)
        self.mcp_tab.connect("clicked", self._switch_tabs_mcp)

    def _add_group_title(self, container: Gtk.Box, text: str, tooltip: str = "") -> None:
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_markup(f"<span weight='600'>{text}</span>")
        label.get_style_context().add_class("settings-group-title")
        if tooltip:
            label.set_tooltip_text(tooltip)
        container.pack_start(label, False, False, 0)

    def _add_setting_row(
        self,
        container: Gtk.Box,
        label_text: str,
        widget: Gtk.Widget,
        tooltip: str = "",
        hint: str = "",
    ) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_markup(f"<span size='10500'>{label_text}</span>")
        if tooltip:
            label.set_tooltip_text(tooltip)
        row.pack_start(label, False, False, 0)

        if hint:
            hint_label = Gtk.Label()
            hint_label.set_halign(Gtk.Align.START)
            hint_label.set_markup(f"<span size='9000' foreground='#888888'>{hint}</span>")
            row.pack_start(hint_label, False, False, 0)

        if tooltip:
            widget.set_tooltip_text(tooltip)

        row.pack_start(widget, False, False, 0)
        container.pack_start(row, False, False, 0)

    def _set_active_scrolled(self, scrolled: Gtk.ScrolledWindow) -> None:
        """Track the scrolled window for the currently visible tab."""
        self._active_scrolled = scrolled

    def _connect_wheel_passthrough(self, widget: Gtk.Widget) -> None:
        """Prevent wheel from changing values; use it to scroll the page instead."""
        try:
            widget.add_events(Gdk.EventMask.SCROLL_MASK)
        except Exception:
            pass
        widget.connect("scroll-event", self._on_setting_input_scroll)

    def _on_setting_input_scroll(self, widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        """Route wheel events from controls to the active page scroller."""
        scrolled = self._active_scrolled
        if not isinstance(scrolled, Gtk.ScrolledWindow):
            ancestor = widget.get_ancestor(Gtk.ScrolledWindow)
            if isinstance(ancestor, Gtk.ScrolledWindow):
                scrolled = ancestor
        if not isinstance(scrolled, Gtk.ScrolledWindow):
            return True

        vadj = scrolled.get_vadjustment()
        if vadj is None:
            return True

        step = float(vadj.get_step_increment() or 24.0)
        if step <= 0:
            step = 24.0

        delta = 0.0
        direction = event.direction
        if direction == Gdk.ScrollDirection.UP:
            delta = -step
        elif direction == Gdk.ScrollDirection.DOWN:
            delta = step
        elif direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = event.get_scroll_deltas()
            if ok:
                delta = float(dy) * max(step, 32.0)

        if delta:
            lower = float(vadj.get_lower())
            upper = float(vadj.get_upper() - vadj.get_page_size())
            target = float(vadj.get_value()) + delta
            vadj.set_value(max(lower, min(upper, target)))
        return True

    def _show_settings_tab(self) -> None:
        """Display the model settings tab."""
        self._capture_model_settings_state()
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._set_active_scrolled(scrolled)

        settings_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        settings_content.set_margin_start(10)
        settings_content.set_margin_end(10)
        settings_content.set_margin_top(10)
        settings_content.set_margin_bottom(10)

        self._add_group_title(
            settings_content,
            "Sampling",
            "Controls randomness and style of generated responses.",
        )

        self.temp_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1)
        self._connect_wheel_passthrough(self.temp_scale)
        self.temp_scale.set_value(self._model_settings_state["temperature"])
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_draw_value(True)
        self.temp_scale.set_digits(2)
        self._add_setting_row(
            settings_content,
            "Temperature",
            self.temp_scale,
            "Lower values are more deterministic; higher values are more creative.",
            "Recommended: 0.2-0.8 for reliable chat behavior.",
        )

        self.top_p_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        self._connect_wheel_passthrough(self.top_p_scale)
        self.top_p_scale.set_value(self._model_settings_state["top_p"])
        self.top_p_scale.set_hexpand(True)
        self.top_p_scale.set_draw_value(True)
        self.top_p_scale.set_digits(2)
        self._add_setting_row(
            settings_content,
            "Top P",
            self.top_p_scale,
            "Nucleus sampling cutoff. Lower values keep only likely tokens.",
        )

        self.rep_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1)
        self._connect_wheel_passthrough(self.rep_scale)
        self.rep_scale.set_value(self._model_settings_state["repetition_penalty"])
        self.rep_scale.set_hexpand(True)
        self.rep_scale.set_draw_value(True)
        self.rep_scale.set_digits(2)
        self._add_setting_row(
            settings_content,
            "Repetition Penalty",
            self.rep_scale,
            "Penalizes repeating tokens or phrases.",
        )

        self.presence_penalty_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -2.0, 2.0, 0.1)
        self._connect_wheel_passthrough(self.presence_penalty_scale)
        self.presence_penalty_scale.set_value(self._model_settings_state["presence_penalty"])
        self.presence_penalty_scale.set_hexpand(True)
        self.presence_penalty_scale.set_draw_value(True)
        self.presence_penalty_scale.set_digits(1)
        self._add_setting_row(
            settings_content,
            "Presence Penalty",
            self.presence_penalty_scale,
            "Encourages introducing new topics (higher values).",
        )

        self.frequency_penalty_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -2.0, 2.0, 0.1)
        self._connect_wheel_passthrough(self.frequency_penalty_scale)
        self.frequency_penalty_scale.set_value(self._model_settings_state["frequency_penalty"])
        self.frequency_penalty_scale.set_hexpand(True)
        self.frequency_penalty_scale.set_draw_value(True)
        self.frequency_penalty_scale.set_digits(1)
        self._add_setting_row(
            settings_content,
            "Frequency Penalty",
            self.frequency_penalty_scale,
            "Penalizes tokens already used often in the response.",
        )

        self._add_group_title(
            settings_content,
            "Output",
            "Controls response length, stop criteria, and reproducibility.",
        )

        self.tokens_spin = Gtk.SpinButton()
        self._connect_wheel_passthrough(self.tokens_spin)
        self.tokens_spin.set_range(1, 32000)
        self.tokens_spin.set_value(self._model_settings_state["max_tokens"])
        self.tokens_spin.set_increments(64, 256)
        self._add_setting_row(
            settings_content,
            "Max Tokens",
            self.tokens_spin,
            "Upper bound on tokens generated for each response.",
        )

        self.seed_spin = Gtk.SpinButton()
        self._connect_wheel_passthrough(self.seed_spin)
        self.seed_spin.set_range(0, 2147483647)
        self.seed_spin.set_increments(1, 100)
        self.seed_spin.set_value(self._model_settings_state["seed"])
        self.seed_spin.set_numeric(True)

        self.seed_enable = Gtk.CheckButton(label="Enable fixed seed")
        self.seed_enable.set_active(self._model_settings_state["seed_enabled"])
        seed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        seed_box.pack_start(self.seed_enable, False, False, 0)
        seed_box.pack_start(self.seed_spin, True, True, 0)
        self._add_setting_row(
            settings_content,
            "Seed",
            seed_box,
            "Optional deterministic seed. Disabled means no seed is sent.",
        )

        self.stop_entry = Gtk.Entry()
        self._connect_wheel_passthrough(self.stop_entry)
        self.stop_entry.set_placeholder_text("e.g. ###, END")
        self.stop_entry.set_text(self._model_settings_state["stop_sequences"])
        self._add_setting_row(
            settings_content,
            "Stop Sequences",
            self.stop_entry,
            "Comma-separated sequences that stop generation.",
            "Leave empty to disable.",
        )

        self._add_group_title(
            settings_content,
            "Context",
            "Conversation memory window and prompt behavior.",
        )

        self.context_limit_spin = Gtk.SpinButton()
        self._connect_wheel_passthrough(self.context_limit_spin)
        self.context_limit_spin.set_range(256, 32000)
        self.context_limit_spin.set_value(self._model_settings_state["context_limit"])
        self.context_limit_spin.set_increments(256, 1024)
        self._add_setting_row(
            settings_content,
            "Context Limit (tokens)",
            self.context_limit_spin,
            "Maximum message history included in each API call.",
        )

        self.include_system_prompt = Gtk.CheckButton(label="Include system prompt in each request")
        self.include_system_prompt.set_active(self._model_settings_state["include_system_prompt"])
        self._add_setting_row(
            settings_content,
            "System Prompt Delivery",
            self.include_system_prompt,
            "When enabled, the system prompt is prepended to request messages.",
        )

        self.token_saver_toggle = Gtk.CheckButton(label="Compress history before each reply")
        self.token_saver_toggle.set_active(bool(self._model_settings_state["token_saver"]))
        self._add_setting_row(
            settings_content,
            "Token Saver",
            self.token_saver_toggle,
            "Summarizes prior conversation history and sends summary + latest user message.",
            "Reduces prompt tokens while keeping key context.",
        )

        self.auto_tool_approval_toggle = Gtk.CheckButton(label="Allow tools without prompting")
        self.auto_tool_approval_toggle.set_active(bool(self._model_settings_state["auto_tool_approval"]))
        self._add_setting_row(
            settings_content,
            "Auto-Approve Tools",
            self.auto_tool_approval_toggle,
            "When enabled, tools requested by the model run immediately without confirmation.",
        )

        scrolled.add(settings_content)
        self.content_box.add(scrolled)
        self.content_box.show_all()

    def _show_prompt_tab(self) -> None:
        """Display the system prompt tab."""
        self._capture_model_settings_state()
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_vexpand(True)
        container.set_hexpand(True)
        container.set_margin_start(8)
        container.set_margin_end(8)
        container.set_margin_top(8)
        container.set_margin_bottom(8)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_markup("<span weight='600'>System Prompt</span>")
        container.add(label)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self._set_active_scrolled(scrolled)

        self.prompt_view = Gtk.TextView()
        self.prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(self._system_prompt_text, -1)

        def _sync_prompt_text(buf):
            start, end = buf.get_bounds()
            self._system_prompt_text = buf.get_text(start, end, False)

        buffer.connect("changed", _sync_prompt_text)
        scrolled.add(self.prompt_view)
        container.add(scrolled)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_btn = Gtk.Button(label="Reset")
        reset_btn.set_tooltip_text("Reset to default system prompt")
        reset_btn.connect("clicked", self._reset_prompt)
        button_box.add(reset_btn)

        container.add(button_box)
        self.content_box.add(container)
        self.content_box.show_all()

    def _show_stats_tab(self) -> None:
        """Display the stats and info tab."""
        self._capture_model_settings_state()
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._set_active_scrolled(scrolled)

        stats_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        stats_content.set_margin_start(8)
        stats_content.set_margin_end(8)
        stats_content.set_margin_top(8)
        stats_content.set_margin_bottom(8)

        conn_title = Gtk.Label(label="Connection")
        conn_title.set_halign(Gtk.Align.START)
        conn_title.set_markup("<b>Connection</b>")
        stats_content.add(conn_title)

        conn_label = Gtk.Label(label="Connected to local LM Studio\nlocalhost:1234")
        conn_label.set_halign(Gtk.Align.START)
        conn_label.set_selectable(True)
        conn_label.set_wrap(True)
        stats_content.add(conn_label)

        scrolled.add(stats_content)
        self.content_box.add(scrolled)
        self.content_box.show_all()

    def _show_mcp_tab(self) -> None:
        """Display MCP server management tab."""
        self._capture_model_settings_state()
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_vexpand(True)
        container.set_hexpand(True)
        container.set_margin_start(8)
        container.set_margin_end(8)
        container.set_margin_top(8)
        container.set_margin_bottom(8)

        title = Gtk.Label()
        title.set_halign(Gtk.Align.START)
        title.set_markup("<span weight='600'>MCP Servers</span>")
        container.pack_start(title, False, False, 0)

        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        label.set_markup("<span size='9000'>MCP server configuration</span>")
        container.pack_start(label, False, False, 0)

        self.content_box.add(container)
        self.content_box.show_all()

    def _set_tab_active(self, active_button: Gtk.Button) -> None:
        for button in (self.settings_tab, self.prompt_tab, self.stats_tab, self.mcp_tab):
            style = button.get_style_context()
            if button is active_button:
                style.add_class("active")
            else:
                style.remove_class("active")

    def _switch_tabs_settings(self, button):
        self._set_tab_active(self.settings_tab)
        self._show_settings_tab()

    def _switch_tabs_prompt(self, button):
        self._set_tab_active(self.prompt_tab)
        self._show_prompt_tab()

    def _switch_tabs_stats(self, button):
        self._set_tab_active(self.stats_tab)
        self._show_stats_tab()

    def _switch_tabs_mcp(self, button):
        self._set_tab_active(self.mcp_tab)
        self._show_mcp_tab()

    def _reset_prompt(self, button):
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(C.DEFAULT_SYSTEM_PROMPT, -1)
        self._system_prompt_text = C.DEFAULT_SYSTEM_PROMPT

    def _capture_model_settings_state(self) -> None:
        """Capture current model tab values if controls are initialized."""
        if hasattr(self, "temp_scale"):
            self._model_settings_state["temperature"] = self.temp_scale.get_value()
        if hasattr(self, "top_p_scale"):
            self._model_settings_state["top_p"] = self.top_p_scale.get_value()
        if hasattr(self, "rep_scale"):
            self._model_settings_state["repetition_penalty"] = self.rep_scale.get_value()
        if hasattr(self, "presence_penalty_scale"):
            self._model_settings_state["presence_penalty"] = self.presence_penalty_scale.get_value()
        if hasattr(self, "frequency_penalty_scale"):
            self._model_settings_state["frequency_penalty"] = self.frequency_penalty_scale.get_value()
        if hasattr(self, "tokens_spin"):
            self._model_settings_state["max_tokens"] = int(self.tokens_spin.get_value())
        if hasattr(self, "seed_spin"):
            self._model_settings_state["seed"] = int(self.seed_spin.get_value())
        if hasattr(self, "seed_enable"):
            self._model_settings_state["seed_enabled"] = self.seed_enable.get_active()
        if hasattr(self, "stop_entry"):
            self._model_settings_state["stop_sequences"] = self.stop_entry.get_text()
        if hasattr(self, "context_limit_spin"):
            self._model_settings_state["context_limit"] = int(self.context_limit_spin.get_value())
        if hasattr(self, "include_system_prompt"):
            self._model_settings_state["include_system_prompt"] = self.include_system_prompt.get_active()
        if hasattr(self, "token_saver_toggle"):
            self._model_settings_state["token_saver"] = self.token_saver_toggle.get_active()
        if hasattr(self, "auto_tool_approval_toggle"):
            self._model_settings_state["auto_tool_approval"] = self.auto_tool_approval_toggle.get_active()

    def get_settings(self) -> ConversationSettings:
        """Get the current settings values."""
        self._capture_model_settings_state()

        seed = None
        if getattr(self, "seed_enable", None) and self.seed_enable.get_active():
            seed = int(self.seed_spin.get_value())

        stop_sequences = None
        if hasattr(self, "stop_entry"):
            raw = self.stop_entry.get_text().strip()
            if raw:
                stop_sequences = [item.strip() for item in raw.split(",") if item.strip()]

        system_prompt = self._system_prompt_text if self.include_system_prompt.get_active() else ""

        return ConversationSettings(
            temperature=self.temp_scale.get_value(),
            max_tokens=int(self.tokens_spin.get_value()),
            top_p=self.top_p_scale.get_value(),
            repetition_penalty=self.rep_scale.get_value(),
            presence_penalty=self.presence_penalty_scale.get_value(),
            frequency_penalty=self.frequency_penalty_scale.get_value(),
            seed=seed,
            stop_sequences=stop_sequences,
            system_prompt=system_prompt,
            context_limit=int(self.context_limit_spin.get_value()),
            token_saver=bool(self._model_settings_state.get("token_saver", False)),
            auto_tool_approval=bool(self._model_settings_state.get("auto_tool_approval", False)),
        )

    def set_auto_tool_approval(self, enabled: bool) -> None:
        """Programmatically set tool auto-approval and keep UI in sync."""
        value = bool(enabled)
        self._model_settings_state["auto_tool_approval"] = value
        if hasattr(self, "auto_tool_approval_toggle"):
            self.auto_tool_approval_toggle.set_active(value)
