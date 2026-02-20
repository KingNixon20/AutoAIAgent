"""
Settings panel widget for model and conversation configuration.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio

from models import ConversationSettings
import constants as C


class SettingsPanel(Gtk.Box):
    """Right side panel with model settings and system prompt."""

    def __init__(self):
        """Initialize the settings panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(280, -1)
        self.get_style_context().add_class("settings-panel")
        
        # Header with close button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_size_request(-1, 70)
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(14)
        header.set_margin_bottom(14)
        
        title = Gtk.Label(label="Settings")
        title.set_markup("<span font='14500' weight='600'>⚙️ Settings</span>")
        title.set_halign(Gtk.Align.START)
        header.pack_start(title, True, True, 0)
        
        self.close_btn = Gtk.Button()
        close_icon = Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        self.close_btn.set_image(close_icon)
        self.close_btn.set_halign(Gtk.Align.END)
        self.close_btn.set_tooltip_text("Close settings")
        header.pack_end(self.close_btn, False, False, 0)
        
        self.add(header)
        
        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(sep)
        
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
        tab_bar.pack_start(self.settings_tab, True, True, 0)
        
        self.prompt_tab = Gtk.Button(label="System")
        self.prompt_tab.set_size_request(-1, 32)
        self.prompt_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.prompt_tab, True, True, 0)
        
        self.stats_tab = Gtk.Button(label="Stats")
        self.stats_tab.set_size_request(-1, 32)
        self.stats_tab.get_style_context().add_class("settings-tab")
        tab_bar.pack_start(self.stats_tab, True, True, 0)
        
        self.add(tab_bar)
        
        # Content area
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content_box.set_vexpand(True)
        self.add(self.content_box)
        
        # Show settings tab by default
        self._show_settings_tab()
        
        # Tab switching
        self.settings_tab.connect("clicked", self._switch_tabs_settings)
        self.prompt_tab.connect("clicked", self._switch_tabs_prompt)
        self.stats_tab.connect("clicked", self._switch_tabs_stats)

    def _show_settings_tab(self) -> None:
        """Display the model settings tab."""
        # Clear content
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)
        
        # Scrollable container
        scrolled = Gtk.ScrolledWindow()
        settings_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        settings_content.set_margin_start(8)
        settings_content.set_margin_end(8)
        settings_content.set_margin_top(8)
        settings_content.set_margin_bottom(8)
        
        # Temperature
        temp_label = Gtk.Label(label="Temperature")
        settings_content.add(temp_label)
        
        temp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.temp_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1
        )
        self.temp_scale.set_value(C.DEFAULT_TEMPERATURE)
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_draw_value(True)
        self.temp_scale.set_digits(2)
        temp_box.add(self.temp_scale)
        settings_content.add(temp_box)
        
        # Max tokens
        tokens_label = Gtk.Label(label="Max Tokens")
        settings_content.add(tokens_label)
        
        tokens_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.tokens_spin = Gtk.SpinButton()
        self.tokens_spin.set_range(1, 32000)
        self.tokens_spin.set_value(C.DEFAULT_MAX_TOKENS)
        self.tokens_spin.set_increments(64, 256)
        tokens_box.add(self.tokens_spin)
        settings_content.add(tokens_box)
        
        # Top P
        top_p_label = Gtk.Label(label="Top P (nucleus sampling)")
        settings_content.add(top_p_label)
        
        top_p_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.top_p_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05
        )
        self.top_p_scale.set_value(C.DEFAULT_TOP_P)
        self.top_p_scale.set_hexpand(True)
        self.top_p_scale.set_draw_value(True)
        self.top_p_scale.set_digits(2)
        top_p_box.add(self.top_p_scale)
        settings_content.add(top_p_box)
        
        # Repetition penalty
        rep_label = Gtk.Label(label="Repetition Penalty")
        settings_content.add(rep_label)
        
        rep_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.rep_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.1
        )
        self.rep_scale.set_value(C.DEFAULT_REPETITION_PENALTY)
        self.rep_scale.set_hexpand(True)
        self.rep_scale.set_draw_value(True)
        self.rep_scale.set_digits(2)
        rep_box.add(self.rep_scale)
        settings_content.add(rep_box)
        
        scrolled.add(settings_content)
        self.content_box.add(scrolled)

    def _show_prompt_tab(self) -> None:
        """Display the system prompt tab."""
        # Clear content
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)
        
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        container.set_margin_start(8)
        container.set_margin_end(8)
        container.set_margin_top(8)
        container.set_margin_bottom(8)
        
        label = Gtk.Label(label="System Prompt")
        container.add(label)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        
        self.prompt_view = Gtk.TextView()
        self.prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(C.DEFAULT_SYSTEM_PROMPT, -1)
        scrolled.add(self.prompt_view)
        
        container.add(scrolled)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        reset_btn = Gtk.Button(label="Reset")
        reset_btn.connect("clicked", self._reset_prompt)
        button_box.add(reset_btn)
        
        save_btn = Gtk.Button(label="Save")
        button_box.add(save_btn)
        
        container.add(button_box)
        self.content_box.add(container)

    def _show_stats_tab(self) -> None:
        """Display the stats and info tab."""
        # Clear content
        for child in list(self.content_box.get_children()):
            self.content_box.remove(child)
        
        scrolled = Gtk.ScrolledWindow()
        stats_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        stats_content.set_margin_start(8)
        stats_content.set_margin_end(8)
        stats_content.set_margin_top(8)
        stats_content.set_margin_bottom(8)
        
        # Connection status
        conn_title = Gtk.Label(label="Connection")
        stats_content.add(conn_title)
        
        conn_label = Gtk.Label(label="Connected to local LM Studio\nlocalhost:1234")
        conn_label.set_selectable(True)
        conn_label.set_wrap(True)
        stats_content.add(conn_label)
        
        # Model info
        model_title = Gtk.Label(label="Model Information")
        stats_content.add(model_title)
        
        model_details = Gtk.Label(label="Name: llama2-7b\nBase Model: Llama 2\nQuantization: Q4_K_M")
        model_details.set_selectable(True)
        model_details.set_wrap(True)
        stats_content.add(model_details)
        
        # Session usage
        usage_title = Gtk.Label(label="Session Usage")
        stats_content.add(usage_title)
        
        usage_label = Gtk.Label(label="Tokens Used: 2,048 / 16,384\nContext Window: 8,192 tokens")
        usage_label.set_selectable(True)
        stats_content.add(usage_label)
        
        scrolled.add(stats_content)
        self.content_box.add(scrolled)

    def _switch_tabs_settings(self, button):
        """Switch to settings tab."""
        # Mark tab as active (GTK3 doesn't use CSS classes)
        self.prompt_tab.remove_css_class("active")
        self.stats_tab.remove_css_class("active")
        self._show_settings_tab()

    def _switch_tabs_prompt(self, button):
        """Switch to prompt tab."""
        self.settings_tab.remove_css_class("active")
        # Mark tab as active (GTK3 doesn't use CSS classes)
        self.stats_tab.remove_css_class("active")
        self._show_prompt_tab()

    def _switch_tabs_stats(self, button):
        """Switch to stats tab."""
        self.settings_tab.remove_css_class("active")
        self.prompt_tab.remove_css_class("active")
        # Mark tab as active (GTK3 doesn't use CSS classes)
        self._show_stats_tab()

    def _reset_prompt(self, button):
        """Reset the system prompt to default."""
        buffer = self.prompt_view.get_buffer()
        buffer.set_text(C.DEFAULT_SYSTEM_PROMPT, -1)

    def get_settings(self) -> ConversationSettings:
        """Get the current settings values.
        
        Returns:
            ConversationSettings object with current values.
        """
        return ConversationSettings(
            temperature=self.temp_scale.get_value(),
            max_tokens=int(self.tokens_spin.get_value()),
            top_p=self.top_p_scale.get_value(),
            repetition_penalty=self.rep_scale.get_value(),
            system_prompt=self._get_system_prompt(),
        )

    def _get_system_prompt(self) -> str:
        """Get the current system prompt text."""
        if hasattr(self, "prompt_view"):
            buffer = self.prompt_view.get_buffer()
            start, end = buffer.get_bounds()
            return buffer.get_text(start, end, False)
        return C.DEFAULT_SYSTEM_PROMPT
