"""
Chat input widget for user message composition.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib


class ChatInput(Gtk.Box):
    """Chat input area with text view and send button."""

    def __init__(self):
        """Initialize the chat input widget."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(12)
        self.set_margin_bottom(16)
        
        # Input wrapper box - horizontal layout with text and button
        input_wrapper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        input_wrapper.set_homogeneous(False)
        input_wrapper.get_style_context().add_class("input-wrapper")
        
        # Text view with scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_can_focus(False)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(100)
        scrolled.set_vexpand(False)
        scrolled.set_hexpand(True)
        scrolled.set_margin_start(0)
        scrolled.set_margin_end(0)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_left_margin(10)
        self.text_view.set_right_margin(10)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.set_accepts_tab(False)
        scrolled.add(self.text_view)
        
        input_wrapper.pack_start(scrolled, True, True, 0)
        
        # Send button - compact and properly positioned
        self.send_button = Gtk.Button(label="")
        send_icon = Gtk.Image.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
        self.send_button.set_image(send_icon)
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
        
        status_dot = Gtk.Box()
        status_dot.set_size_request(6, 6)
        status_dot.get_style_context().add_class("status-active")
        status_box.pack_start(status_dot, False, False, 0)
        
        status_label = Gtk.Label(label="Connected · Ready")
        status_label.set_markup("<span size='10000' foreground='#808080'>Connected · Ready</span>")
        status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(status_label, False, False, 0)
        
        self.pack_start(status_box, False, False, 0)
        
        # Connect text buffer signals for send button state
        self.text_buffer = self.text_view.get_buffer()
        self.text_buffer.connect("changed", self._on_text_changed)

    def _on_text_changed(self, buffer):
        """Update send button state based on text content."""
        has_text = buffer.get_char_count() > 0
        self.send_button.set_sensitive(has_text)

    def get_text(self) -> str:
        """Get the current input text.
        
        Returns:
            The text from the input field.
        """
        start, end = self.text_buffer.get_bounds()
        return self.text_buffer.get_text(start, end, False)

    def clear(self) -> None:
        """Clear the input field."""
        self.text_buffer.set_text("", -1)

    def focus(self) -> None:
        """Focus the text view."""
        self.text_view.grab_focus()

    def connect_send(self, callback):
        """Connect the send button click signal.
        
        Args:
            callback: Function to call when send is clicked.
        """
        self.send_button.connect("clicked", callback)
