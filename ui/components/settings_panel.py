"""
Settings panel widget for model and conversation configuration.
"""
import gi
import json

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from models import ConversationSettings
from storage import (
    save_app_mcp_server,
    load_app_mcp_servers,
    delete_app_mcp_server,
)
import constants as C


class SettingsPanel(Gtk.Box):
    """Right side panel with model settings and system prompt."""

    def __init__(self):
        """Initialize the settings panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        try:
            self.set_size_request(int(C.SETTINGS_PANEL_WIDTH), -1)
        except Exception:
            self.set_size_request(320, -1)
        # Allow expansion when the parent allocates space so content becomes visible.
        self.set_hexpand(True)
        self.set_halign(Gtk.Align.END)
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
        }
        self.on_mcp_servers_changed = None

        # Header with close button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_size_request(-1, 70)
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(14)
        header.set_margin_bottom(14)

        title = Gtk.Label(label="Settings")
        title.set_markup("<span font='14500' weight='600'>Settings</span>")
        title.set_halign(Gtk.Align.START)
        header.pack_start(title, True, True, 0)

        self.close_btn = Gtk.Button(label="Close")
        close_icon = Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        self.close_btn.set_image(close_icon)
        self.close_btn.set_always_show_image(True)
        self.close_btn.set_halign(Gtk.Align.END)
        self.close_btn.set_tooltip_text("Close settings panel")
        header.pack_end(self.close_btn, False, False, 0)

        self.pack_start(header, False, False, 0)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.pack_start(sep, False, False, 0)

        # Tab buttons
        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.set_margin_start(12)
        tab_bar.set_margin_end(12)
        tab_bar.set_margin_top(8)
        tab_bar.set_margin_bottom(8)
        tab_bar.set_homogeneous(True)

        self.settings_tab = Gtk.Button(label="Model")
        self.settings_tab.set_size_request(-1, 32)
        self.settings_tab.get_style_context().add_class("settings-tab")
        self.settings_tab.set_tooltip_text("Model behavior and output settings")
        tab_bar.pack_start(self.settings_tab, True, True, 0)

        self.prompt_tab = Gtk.Button(label="System")
        self.prompt_tab.set_size_request(-1, 32)
        self.prompt_tab.get_style_context().add_class("settings-tab")
        self.prompt_tab.set_tooltip_text("Set or reset the system prompt")
        tab_bar.pack_start(self.prompt_tab, True, True, 0)

        self.stats_tab = Gtk.Button(label="Stats")
        self.stats_tab.set_size_request(-1, 32)
        self.stats_tab.get_style_context().add_class("settings-tab")
        self.stats_tab.set_tooltip_text("Connection and session details")
        tab_bar.pack_start(self.stats_tab, True, True, 0)

        self.mcp_tab = Gtk.Button(label="MCP")
        self.mcp_tab.set_size_request(-1, 32)
        self.mcp_tab.get_style_context().add_class("settings-tab")
        self.mcp_tab.set_tooltip_text("Manage app-local MCP servers")
        tab_bar.pack_start(self.mcp_tab, True, True, 0)

        self.pack_start(tab_bar, False, False, 0)

        # Content area
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content_box.set_hexpand(True)
        self.content_box.set_vexpand(True)
        self.pack_start(self.content_box, True, True, 0)

        # Show settings tab by default
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
            if tooltip:
                hint_label.set_tooltip_text(tooltip)
            row.pack_start(hint_label, False, False, 0)

        if tooltip:
            widget.set_tooltip_text(tooltip)

        row.pack_start(widget, False, False, 0)
        container.pack_start(row, False, False, 0)

    def _show_settings_tab(self) -> None:
        """Display the model settings tab."""
        self._capture_model_settings_state()
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

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
        self.seed_spin.set_range(0, 2147483647)
        self.seed_spin.set_increments(1, 100)
        self.seed_spin.set_value(self._model_settings_state["seed"])
        self.seed_spin.set_numeric(True)
        self.seed_spin.set_tooltip_text("Seed value for reproducible generations.")

        self.seed_enable = Gtk.CheckButton(label="Enable fixed seed")
        self.seed_enable.set_active(self._model_settings_state["seed_enabled"])
        self.seed_enable.set_tooltip_text("Use a deterministic seed for reproducible outputs.")
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
        label.set_tooltip_text("High-priority instruction sent before user/assistant messages.")
        container.add(label)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.prompt_view = Gtk.TextView()
        self.prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.prompt_view.set_tooltip_text("Define assistant behavior and constraints for this chat.")
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(self._system_prompt_text, -1)

        def _sync_prompt_text(buf):
            start, end = buf.get_bounds()
            self._system_prompt_text = buf.get_text(start, end, False)

        buffer.connect("changed", _sync_prompt_text)
        scrolled.add(self.prompt_view)

        container.add(scrolled)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        reset_btn = Gtk.Button(label="Reset")
        reset_btn.set_tooltip_text("Reset to default system prompt")
        reset_btn.connect("clicked", self._reset_prompt)
        button_box.add(reset_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.set_tooltip_text("Prompt is also applied automatically when sending")
        save_btn.connect("clicked", lambda *_: (buffer := self.prompt_view.get_buffer()) and self._save_prompt_from_buffer(buffer))
        button_box.add(save_btn)

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

        model_title = Gtk.Label(label="Model Information")
        model_title.set_halign(Gtk.Align.START)
        model_title.set_markup("<b>Model Information</b>")
        stats_content.add(model_title)

        model_details = Gtk.Label(label="Name: llama2-7b\nBase Model: Llama 2\nQuantization: Q4_K_M")
        model_details.set_halign(Gtk.Align.START)
        model_details.set_selectable(True)
        model_details.set_wrap(True)
        stats_content.add(model_details)

        usage_title = Gtk.Label(label="Session Usage")
        usage_title.set_halign(Gtk.Align.START)
        usage_title.set_markup("<b>Session Usage</b>")
        stats_content.add(usage_title)

        usage_label = Gtk.Label(label="Tokens Used: 2,048 / 16,384\nContext Window: 8,192 tokens")
        usage_label.set_halign(Gtk.Align.START)
        usage_label.set_selectable(True)
        stats_content.add(usage_label)

        # MCP management
        mcp_title = Gtk.Label(label="MCP Servers")
        mcp_title.set_halign(Gtk.Align.START)
        mcp_title.set_markup("<b>MCP Servers</b>")
        stats_content.add(mcp_title)

        mcp_hint = Gtk.Label()
        mcp_hint.set_halign(Gtk.Align.START)
        mcp_hint.set_xalign(0.0)
        mcp_hint.set_line_wrap(True)
        mcp_hint.set_markup(
            "<span size='9000' foreground='#888888'>Add custom MCP servers for this app client.</span>"
        )
        stats_content.add(mcp_hint)

        add_mcp_btn = Gtk.Button(label="Add MCP Server")
        add_mcp_btn.set_tooltip_text("Open a dialog to add a custom MCP server")
        add_mcp_btn.connect("clicked", self._open_add_mcp_dialog)
        stats_content.add(add_mcp_btn)

        scrolled.add(stats_content)
        self.content_box.add(scrolled)
        self.content_box.show_all()

    def _set_tab_active(self, active_button: Gtk.Button) -> None:
        for button in (self.settings_tab, self.prompt_tab, self.stats_tab, self.mcp_tab):
            style = button.get_style_context()
            if button is active_button:
                style.add_class("active")
            else:
                style.remove_class("active")

    def _switch_tabs_settings(self, button):
        """Switch to settings tab."""
        self._set_tab_active(self.settings_tab)
        self._show_settings_tab()

    def _switch_tabs_prompt(self, button):
        """Switch to prompt tab."""
        self._set_tab_active(self.prompt_tab)
        self._show_prompt_tab()

    def _switch_tabs_stats(self, button):
        """Switch to stats tab."""
        self._set_tab_active(self.stats_tab)
        self._show_stats_tab()

    def _switch_tabs_mcp(self, button):
        """Switch to MCP tab."""
        self._set_tab_active(self.mcp_tab)
        self._show_mcp_tab()

    def _reset_prompt(self, button):
        """Reset the system prompt to default."""
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(C.DEFAULT_SYSTEM_PROMPT, -1)
        self._system_prompt_text = C.DEFAULT_SYSTEM_PROMPT

    def get_settings(self) -> ConversationSettings:
        """Get the current settings values.

        Returns:
            ConversationSettings object with current values.
        """
        self._capture_model_settings_state()

        seed = None
        if getattr(self, "seed_enable", None) and self.seed_enable.get_active():
            seed = int(self.seed_spin.get_value())

        stop_sequences = None
        if hasattr(self, "stop_entry"):
            raw = self.stop_entry.get_text().strip()
            if raw:
                stop_sequences = [item.strip() for item in raw.split(",") if item.strip()]

        system_prompt = self._get_system_prompt() if self._is_system_prompt_enabled() else ""

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
        )

    def _is_system_prompt_enabled(self) -> bool:
        if hasattr(self, "include_system_prompt"):
            return self.include_system_prompt.get_active()
        return bool(self._model_settings_state.get("include_system_prompt", True))

    def _get_system_prompt(self) -> str:
        """Get the current system prompt text."""
        if hasattr(self, "prompt_view"):
            buffer = self.prompt_view.get_buffer()
            start, end = buffer.get_bounds()
            return buffer.get_text(start, end, False)
        return self._system_prompt_text

    def _save_prompt_from_buffer(self, buffer: Gtk.TextBuffer) -> None:
        """Save the prompt text from a TextBuffer into the panel state."""
        try:
            start, end = buffer.get_bounds()
            text = buffer.get_text(start, end, False)
            self._system_prompt_text = text
            # Capture current model settings as well so get_settings reflects latest values
            self._capture_model_settings_state()
        except Exception:
            pass

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

    def _open_add_mcp_dialog(self, _button=None, existing_name: str = "", existing_config: dict | None = None) -> None:
        """Open dialog for creating/updating app-local MCP server config."""
        dialog = Gtk.Dialog(
            title="Edit MCP Server" if existing_name else "Add MCP Server",
            transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None,
            flags=0,
        )
        dialog.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Save", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(520, 420)

        content = dialog.get_content_area()
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_spacing(10)

        form = Gtk.Grid()
        form.set_row_spacing(8)
        form.set_column_spacing(10)
        content.pack_start(form, True, True, 0)

        def add_row(row: int, label_text: str, widget: Gtk.Widget):
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0.0)
            form.attach(label, 0, row, 1, 1)
            form.attach(widget, 1, row, 1, 1)

        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("e.g. playwright")
        if existing_name:
            name_entry.set_text(existing_name)
        add_row(0, "Name*", name_entry)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("e.g. http://127.0.0.1:3001/mcp")
        if existing_config and existing_config.get("url"):
            url_entry.set_text(str(existing_config.get("url")))
        add_row(1, "URL", url_entry)

        command_entry = Gtk.Entry()
        command_entry.set_placeholder_text("e.g. npx")
        if existing_config and existing_config.get("command"):
            command_entry.set_text(str(existing_config.get("command")))
        add_row(2, "Command", command_entry)

        args_entry = Gtk.Entry()
        args_entry.set_placeholder_text("comma-separated, e.g. -y,@modelcontextprotocol/server-filesystem,/tmp")
        if existing_config and isinstance(existing_config.get("args"), list):
            args_entry.set_text(",".join(str(x) for x in existing_config.get("args")))
        add_row(3, "Args", args_entry)

        env_view = Gtk.TextView()
        env_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        env_view.set_size_request(-1, 120)
        env_buf = env_view.get_buffer()
        if existing_config and isinstance(existing_config.get("env"), dict):
            env_buf.set_text(json.dumps(existing_config.get("env"), indent=2, ensure_ascii=False), -1)
        else:
            env_buf.set_text("{}", -1)

        env_scroll = Gtk.ScrolledWindow()
        env_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        env_scroll.add(env_view)
        add_row(4, "Env JSON", env_scroll)

        hint = Gtk.Label()
        hint.set_halign(Gtk.Align.START)
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.set_markup(
            "<span size='9000' foreground='#888888'>Provide either URL for HTTP/SSE transport or command/args for stdio transport.</span>"
        )
        content.pack_start(hint, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return

        name = name_entry.get_text().strip()
        url = url_entry.get_text().strip()
        command = command_entry.get_text().strip()
        args_text = args_entry.get_text().strip()
        args = [item.strip() for item in args_text.split(",") if item.strip()] if args_text else []
        env = {}
        env_start, env_end = env_buf.get_bounds()
        env_text = env_buf.get_text(env_start, env_end, False).strip()
        if env_text and env_text != "{}":
            try:
                parsed_env = json.loads(env_text)
                if isinstance(parsed_env, dict):
                    env = parsed_env
                else:
                    raise ValueError("Env must be a JSON object.")
            except Exception as e:
                self._show_simple_error("Invalid Env JSON", str(e))
                dialog.destroy()
                return

        server_config = {}
        if url:
            server_config["url"] = url
        if command:
            server_config["command"] = command
        if args:
            server_config["args"] = args
        if env:
            server_config["env"] = env

        if not server_config:
            self._show_simple_error(
                "Missing Server Details",
                "Provide at least URL or command details.",
            )
            dialog.destroy()
            return

        ok, msg = save_app_mcp_server(name, server_config)
        dialog.destroy()
        if not ok:
            self._show_simple_error("Save Failed", msg)
            return
        self._show_simple_info("MCP Server Saved", msg)
        self._refresh_mcp_server_list()
        if callable(self.on_mcp_servers_changed):
            self.on_mcp_servers_changed()

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
        title.set_markup("<span weight='600'>MCP Server Manager</span>")
        container.pack_start(title, False, False, 0)

        hint = Gtk.Label()
        hint.set_halign(Gtk.Align.START)
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        hint.set_markup(
            "<span size='9000' foreground='#888888'>Manage app-local MCP servers. These are merged with LM Studio servers.</span>"
        )
        container.pack_start(hint, False, False, 0)

        self.mcp_list = Gtk.ListBox()
        self.mcp_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.mcp_list.connect("row-selected", self._on_mcp_row_selected)
        mcp_scrolled = Gtk.ScrolledWindow()
        mcp_scrolled.set_vexpand(True)
        mcp_scrolled.set_hexpand(True)
        mcp_scrolled.add(self.mcp_list)
        container.pack_start(mcp_scrolled, True, True, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.mcp_add_btn = Gtk.Button(label="Add")
        self.mcp_add_btn.connect("clicked", self._open_add_mcp_dialog)
        btn_row.pack_start(self.mcp_add_btn, True, True, 0)

        self.mcp_edit_btn = Gtk.Button(label="Edit")
        self.mcp_edit_btn.set_sensitive(False)
        self.mcp_edit_btn.connect("clicked", self._edit_selected_mcp_server)
        btn_row.pack_start(self.mcp_edit_btn, True, True, 0)

        self.mcp_delete_btn = Gtk.Button(label="Delete")
        self.mcp_delete_btn.set_sensitive(False)
        self.mcp_delete_btn.connect("clicked", self._delete_selected_mcp_server)
        btn_row.pack_start(self.mcp_delete_btn, True, True, 0)
        container.pack_start(btn_row, False, False, 0)

        self.content_box.add(container)
        self._selected_mcp_name = None
        self._mcp_row_names = {}
        self._refresh_mcp_server_list()
        self.content_box.show_all()

    def _refresh_mcp_server_list(self) -> None:
        if not hasattr(self, "mcp_list"):
            return
        for row in list(self.mcp_list.get_children()):
            self.mcp_list.remove(row)
        self._mcp_row_names = {}

        servers = load_app_mcp_servers()
        if not servers:
            row = Gtk.ListBoxRow()
            label = Gtk.Label()
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0.0)
            label.set_markup("<span foreground='#888888'>No app-local MCP servers yet.</span>")
            row.add(label)
            row.set_selectable(False)
            self.mcp_list.add(row)
        else:
            for name in sorted(servers.keys()):
                cfg = servers.get(name) or {}
                summary = cfg.get("url") or cfg.get("command") or "(no transport set)"
                row = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                title = Gtk.Label()
                title.set_halign(Gtk.Align.START)
                title.set_xalign(0.0)
                title.set_markup(f"<span weight='600'>{name}</span>")
                subtitle = Gtk.Label()
                subtitle.set_halign(Gtk.Align.START)
                subtitle.set_xalign(0.0)
                subtitle.set_markup(f"<span size='9000' foreground='#888888'>{summary}</span>")
                box.pack_start(title, False, False, 0)
                box.pack_start(subtitle, False, False, 0)
                row.add(box)
                self._mcp_row_names[id(row)] = name
                self.mcp_list.add(row)
        self.mcp_list.show_all()
        self._set_mcp_action_buttons_enabled(False)

    def _on_mcp_row_selected(self, _listbox, row) -> None:
        if row is None or not row.get_selectable():
            self._selected_mcp_name = None
            self._set_mcp_action_buttons_enabled(False)
            return
        name = self._mcp_row_names.get(id(row))
        self._selected_mcp_name = name if isinstance(name, str) else None
        self._set_mcp_action_buttons_enabled(bool(self._selected_mcp_name))

    def _set_mcp_action_buttons_enabled(self, enabled: bool) -> None:
        if hasattr(self, "mcp_edit_btn"):
            self.mcp_edit_btn.set_sensitive(enabled)
        if hasattr(self, "mcp_delete_btn"):
            self.mcp_delete_btn.set_sensitive(enabled)

    def _edit_selected_mcp_server(self, _button) -> None:
        if not getattr(self, "_selected_mcp_name", None):
            return
        servers = load_app_mcp_servers()
        name = self._selected_mcp_name
        cfg = servers.get(name) if isinstance(servers, dict) else None
        self._open_add_mcp_dialog(existing_name=name, existing_config=cfg if isinstance(cfg, dict) else {})

    def _delete_selected_mcp_server(self, _button) -> None:
        name = getattr(self, "_selected_mcp_name", None)
        if not name:
            return
        ok, msg = delete_app_mcp_server(name)
        if not ok:
            self._show_simple_error("Delete Failed", msg)
            return
        self._show_simple_info("MCP Server Deleted", msg)
        self._selected_mcp_name = None
        self._refresh_mcp_server_list()
        if callable(self.on_mcp_servers_changed):
            self.on_mcp_servers_changed()

    def _show_simple_error(self, title: str, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _show_simple_info(self, title: str, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel() if isinstance(self.get_toplevel(), Gtk.Window) else None,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
