"""
Tools bar widget for enabling/disabling MCP tools above the chat input.

Each tool is shown as a compact row containing:
- display label
- a slide `Gtk.Switch` to enable/disable usage of the tool
- a dropdown (popover) listing available individual calls and their full definitions

The widget expects a list of dicts from `load_mcp_servers()` with keys
`id`, `name`, and optional `calls` (list of strings).

When initialized with mcp_discovery and server_configs, it will discover tool
definitions on demand when the dropdown is clicked, showing detailed function
signatures and parameter information similar to LM Studio.
"""

import asyncio
import logging
import threading
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject, GLib

logger = logging.getLogger(__name__)


class ToolsBar(Gtk.Box):
    """Vertical MCP tools list with switches and call-dropdowns."""

    __gsignals__ = {
        # integration_id (str), enabled (bool)
        "tool-toggled": (GObject.SIGNAL_RUN_FIRST, None, (str, bool)),
    }

    def __init__(self, tools: list[dict], mcp_discovery=None, server_configs: dict = None):
        """Initialize with list of tool dicts from `load_mcp_servers()`.

        Each tool dict should look like: {"id": "mcp/name", "name": "name", "calls": [..]}
        
        Args:
            tools: List of tool dicts from load_mcp_servers()
            mcp_discovery: MCPToolDiscovery instance for discovering tools on demand
            server_configs: Dict of server configs from load_mcp_server_configs()
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.get_style_context().add_class("tools-list")
        self._tools = tools or []
        self._switches: dict[str, Gtk.Switch] = {}
        self._tools_by_id: dict[str, dict] = {}
        self._mcp_discovery = mcp_discovery
        self._server_configs = server_configs or {}
        self._discovered_tools_cache: dict[str, list[dict]] = {}
        # Map of integration_id -> popover container widget created during init
        self._popover_containers: dict[str, Gtk.Box] = {}
        self._loading_popovers: set[str] = set()

        if not self._tools:
            label = Gtk.Label(label="No MCP tools found. Add in LM Studio or Settings → Add MCP Server")
            label.set_markup("<span size='10000' foreground='#808080'>No MCP tools found</span>")
            self.pack_start(label, False, False, 0)
            return

        # Use a vertical list in a scroller for an organized right-side panel.
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.add(vbox)

        for tool in self._tools:
            integration_id = tool.get("id")
            name = tool.get("name") or integration_id
            calls = tool.get("calls") or []
            self._tools_by_id[integration_id] = {
                "id": integration_id,
                "name": name,
                "calls": calls,
            }

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.get_style_context().add_class("tool-row")
            row.set_margin_start(2)
            row.set_margin_end(2)
            row.set_margin_top(1)
            row.set_margin_bottom(1)

            label = Gtk.Label(label=name)
            label.set_xalign(0)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(True)

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
            menu_btn.set_tooltip_text(f"Show functions for {name}")
            menu_btn.set_size_request(32, 28)  # Stable button sizing
            arrow = Gtk.Arrow(arrow_type=Gtk.ArrowType.DOWN, shadow_type=Gtk.ShadowType.NONE)
            menu_btn.add(arrow)

            popover = Gtk.Popover.new(menu_btn)
            popover.set_size_request(460, -1)  # Comfortable width for tool details
            popover.set_modal(False)  # Allow interaction outside popover
            
            # Create scrolled container for tool list
            scroll_box = Gtk.ScrolledWindow()
            scroll_box.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll_box.set_max_content_height(800)  # Increased to show more tools
            scroll_box.set_propagate_natural_height(True)
            
            popover_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            popover_container.set_margin_top(8)
            popover_container.set_margin_bottom(8)
            popover_container.set_margin_start(8)
            popover_container.set_margin_end(8)
            
            # Store the container so we can update it when tools are discovered
            popover_container._integration_id = integration_id
            popover_container._popover = popover
            # Keep a reference to the container so callers can refresh it
            self._popover_containers[integration_id] = popover_container
            
            # Initially show config-declared calls or placeholder
            self._populate_tool_popover(popover_container, integration_id)
            
            # Connect to show signal to discover tools on demand
            popover.connect("show", self._on_popover_show, integration_id, popover_container)
            
            scroll_box.add(popover_container)
            popover.add(scroll_box)
            scroll_box.show_all()
            menu_btn.set_popover(popover)

            # Pack row: label, switch, dropdown
            row.pack_start(label, True, True, 0)
            row.pack_start(switch, False, False, 0)
            row.pack_start(menu_btn, False, False, 0)

            # Pack each tool row into the vertical list.
            vbox.pack_start(row, False, False, 0)

        self.pack_start(scroller, True, True, 0)

        # Add a separator
        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10, margin_bottom=5), False, False, 0)

        # Add the critique checkbox
        self.critique_checkbox = Gtk.CheckButton(label="Enable Self-Critique (Token Heavy)")
        self.text = "Enable this to have the Agent critique its own work and suggest improvements."
        self.critique_checkbox.set_active(True) # Enabled by default
        self.critique_checkbox.set_tooltip_text("Enable this to have the Agent critique its own work and suggest improvements.")
        vbox.pack_start(self.critique_checkbox, False, False, 0)

    def get_critique_enabled(self) -> bool:
        """Return whether the critique checkbox is enabled."""
        return self.critique_checkbox.get_active()

    def _populate_tool_popover(self, container: Gtk.Box, integration_id: str) -> None:
        """Populate a popover container with tool definitions."""
        # Clear existing children
        for child in container.get_children():
            container.remove(child)
        
        # Check if we have cached discovered tools
        if integration_id in self._discovered_tools_cache:
            tools = self._discovered_tools_cache[integration_id]
            if tools:
                self._add_tool_definitions(container, tools)
            else:
                lbl = Gtk.Label(label="(no functions discovered)")
                lbl.get_style_context().add_class("dim-label")
                container.pack_start(lbl, False, False, 0)
        else:
            # Show config-declared calls as fallback
            calls = self._tools_by_id.get(integration_id, {}).get("calls", [])
            if calls:
                self._add_tool_definitions(container, [
                    {
                        "type": "function",
                        "function": {
                            "name": call,
                            "description": f"Call '{call}'",
                            "parameters": {"type": "object", "properties": {}}
                        }
                    }
                    for call in calls
                ])
            else:
                lbl = Gtk.Label(label="(no functions available)")
                lbl.get_style_context().add_class("dim-label")
                container.pack_start(lbl, False, False, 0)

    def _add_tool_definitions(self, container: Gtk.Box, tools: list[dict]) -> None:
        """Add formatted tool definitions to the popover container."""
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                continue
            
            fn = tool.get("function") or {}
            if not isinstance(fn, dict):
                continue
            
            name = str(fn.get("name", "")).strip()
            description = str(fn.get("description", "")).strip()
            params = fn.get("parameters", {})
            
            if not name:
                continue
            
            # Separator between tools
            if i > 0:
                sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                container.pack_start(sep, False, False, 4)
            
            # Tool name (bold)
            name_lbl = Gtk.Label()
            name_lbl.set_markup(f"<b>{self._escape_markup(name)}</b>")
            name_lbl.set_xalign(0)
            name_lbl.set_line_wrap(True)
            container.pack_start(name_lbl, False, False, 2)
            
            # Tool description
            if description:
                desc_lbl = Gtk.Label(label=description)
                desc_lbl.set_xalign(0)
                desc_lbl.set_line_wrap(True)
                desc_lbl.get_style_context().add_class("dim-label")
                container.pack_start(desc_lbl, False, False, 2)
            
            # Parameters section
            if isinstance(params, dict) and params.get("properties"):
                props = params.get("properties", {})
                if props:
                    param_title = Gtk.Label()
                    param_title.set_markup("<small><b>Parameters:</b></small>")
                    param_title.set_xalign(0)
                    container.pack_start(param_title, False, False, 2)
                    
                    for prop_name, prop_schema in props.items():
                        if isinstance(prop_schema, dict):
                            prop_type = prop_schema.get("type", "unknown")
                            prop_desc = prop_schema.get("description", "")
                            
                            if prop_desc:
                                prop_lbl = Gtk.Label()
                                prop_lbl.set_markup(
                                    f"  <tt>{self._escape_markup(prop_name)}</tt>: <i>{prop_type}</i>\n    {self._escape_markup(prop_desc)}"
                                )
                                prop_lbl.set_xalign(0)
                                prop_lbl.set_line_wrap(True)
                                container.pack_start(prop_lbl, False, False, 2)
                            else:
                                prop_lbl = Gtk.Label()
                                prop_lbl.set_markup(
                                    f"  <tt>{self._escape_markup(prop_name)}</tt>: <i>{prop_type}</i>"
                                )
                                prop_lbl.set_xalign(0)
                                prop_lbl.set_line_wrap(True)
                                container.pack_start(prop_lbl, False, False, 2)
            
            # Required fields (if any)
            required = params.get("required", [])
            if required:
                req_title = Gtk.Label()
                req_title.set_markup(f"<small><b>Required:</b> {', '.join(str(r) for r in required)}</small>")
                req_title.set_xalign(0)
                req_title.set_line_wrap(True)
                container.pack_start(req_title, False, False, 2)

    def _escape_markup(self, text: str) -> str:
        """Escape text for use in markup."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _on_popover_show(self, popover, integration_id: str, container: Gtk.Box) -> None:
        """Handle popover show signal - discover tools on demand if not cached."""
        if integration_id in self._discovered_tools_cache or integration_id in self._loading_popovers:
            return
        
        if not self._mcp_discovery or integration_id not in self._server_configs:
            # No discovery capability, use existing content
            return
        
        # Mark as loading to avoid duplicate discovery
        self._loading_popovers.add(integration_id)
        
        def discover_and_update():
            """Run discovery in background and update UI."""
            try:
                server_config = self._server_configs.get(integration_id, {})
                if not isinstance(server_config, dict):
                    self._loading_popovers.discard(integration_id)
                    return
                
                cfg = server_config.get("config", {})
                name = server_config.get("name", integration_id)
                
                # Run discovery using new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    tools = loop.run_until_complete(
                        self._mcp_discovery._discover_single(integration_id, name, cfg)
                    )
                    
                    # Cache the result
                    self._discovered_tools_cache[integration_id] = tools
                    logger.debug(
                        "Discovered %d tools for %s in popover",
                        len(tools),
                        integration_id,
                    )
                    
                    # Update popover on main thread
                    GLib.idle_add(lambda: self._populate_tool_popover(container, integration_id) or False)
                    GLib.idle_add(lambda: container.show_all() or False)
                finally:
                    loop.close()
            except Exception as e:
                logger.debug("Tool discovery failed for %s: %s", integration_id, e)
                self._discovered_tools_cache[integration_id] = []
                GLib.idle_add(lambda: self._populate_tool_popover(container, integration_id) or False)
                GLib.idle_add(lambda: container.show_all() or False)
            finally:
                self._loading_popovers.discard(integration_id)
        
        # Run discovery in background thread
        threading.Thread(target=discover_and_update, daemon=True).start()

    def set_mcp_discovery(self, mcp_discovery, server_configs: dict) -> None:
        """Set or update MCP discovery capability after initialization."""
        self._mcp_discovery = mcp_discovery
        self._server_configs = server_configs or {}

    def refresh_all_popovers(self) -> None:
        """Refresh all popover containers from the discovered tools cache."""
        for integration_id, container in getattr(self, "_popover_containers", {}).items():
            try:
                self._populate_tool_popover(container, integration_id)
            except Exception:
                logger.debug("Failed to refresh popover for %s", integration_id)

    def get_enabled_tools(self) -> list[str]:
        """Return integration ids of currently enabled tools (switch on)."""
        return [iid for iid, sw in self._switches.items() if sw.get_active()]

    def set_tool_enabled(self, integration_id: str, enabled: bool) -> None:
        """Programmatically set a tool's enabled state if present."""
        sw = self._switches.get(integration_id)
        if sw is not None:
            sw.set_active(bool(enabled))

    def get_enabled_tool_metadata(self) -> list[dict]:
        """Return metadata for currently enabled tools."""
        enabled = []
        for integration_id, sw in self._switches.items():
            if sw.get_active() and integration_id in self._tools_by_id:
                enabled.append(self._tools_by_id[integration_id])
        return enabled
