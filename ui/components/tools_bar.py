"""
Tools bar widget for enabling/disabling MCP tools above the chat input.

Each tool is shown as a compact row containing:
- display label
- a slide `Gtk.Switch` to enable/disable usage of the tool
- a dropdown (popover) listing available individual calls the tool can make

The widget expects a list of dicts from `load_mcp_servers()` with keys
`id`, `name`, and optional `calls` (list of strings).
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject


class ToolsBar(Gtk.Box):
    """Horizontal bar of tool rows with switches and call-dropdowns."""

    __gsignals__ = {
        # integration_id (str), enabled (bool)
        "tool-toggled": (GObject.SIGNAL_RUN_FIRST, None, (str, bool)),
    }

    def __init__(self, tools: list[dict]):
        """Initialize with list of tool dicts from `load_mcp_servers()`.

        Each tool dict should look like: {"id": "mcp/name", "name": "name", "calls": [..]}
        """
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_bottom(6)
        self._tools = tools or []
        self._switches: dict[str, Gtk.Switch] = {}

        if not self._tools:
            label = Gtk.Label(label="No MCP tools found. Add servers in ~/.lmstudio/mcp.json")
            label.set_markup("<span size='10000' foreground='#808080'>No MCP tools found</span>")
            self.pack_start(label, False, False, 0)
            return

        # Use a horizontal box inside a scrolled window so tools appear side-by-side
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroller.add(hbox)

        for tool in self._tools:
            integration_id = tool.get("id")
            name = tool.get("name") or integration_id
            calls = tool.get("calls") or []

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.get_style_context().add_class("tool-row")

            label = Gtk.Label(label=name)
            label.set_xalign(0)

            # Switch to enable/disable the tool
            switch = Gtk.Switch()
            switch.set_active(False)
            switch.set_tooltip_text(f"Enable {name} for use in completions")
            self._switches[integration_id] = switch
            # Emit a signal when the switch state changes so outer code can react
            switch.connect(
                "notify::active",
                lambda sw, pspec, iid=integration_id: self.emit("tool-toggled", iid, sw.get_active()),
            )

            # Dropdown/popover to show available calls
            menu_btn = Gtk.MenuButton()
            menu_btn.set_tooltip_text(f"Show calls for {name}")
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.DOWN, shadow_type=Gtk.ShadowType.NONE)
            menu_btn.add(arrow)

            popover = Gtk.Popover.new(menu_btn)
            popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            popover_box.set_margin_top(8)
            popover_box.set_margin_bottom(8)
            popover_box.set_margin_start(8)
            popover_box.set_margin_end(8)

            if calls:
                for call in calls:
                    lbl = Gtk.Label(label=call)
                    lbl.set_xalign(0)
                    popover_box.pack_start(lbl, False, False, 0)
            else:
                lbl = Gtk.Label(label="(no calls discovered)")
                lbl.get_style_context().add_class("dim-label")
                popover_box.pack_start(lbl, False, False, 0)

            popover.add(popover_box)
            popover_box.show_all()
            menu_btn.set_popover(popover)

            # Pack row: label, switch, dropdown
            row.pack_start(label, True, True, 0)
            row.pack_start(switch, False, False, 0)
            row.pack_start(menu_btn, False, False, 0)

            # Pack each tool row into the horizontal box without expanding vertically
            hbox.pack_start(row, False, False, 0)

        self.pack_start(scroller, True, True, 0)

    def get_enabled_tools(self) -> list[str]:
        """Return integration ids of currently enabled tools (switch on)."""
        return [iid for iid, sw in self._switches.items() if sw.get_active()]

    def set_tool_enabled(self, integration_id: str, enabled: bool) -> None:
        """Programmatically set a tool's enabled state if present."""
        sw = self._switches.get(integration_id)
        if sw is not None:
            sw.set_active(bool(enabled))
