"""
Main application window orchestrating all UI components.
"""
import constants as C
from ui.components import (
    ChatArea,
    ChatInput,
    Sidebar,
    SettingsWindow,
    ToolsBar,
)
from mcp_discovery import MCPToolDiscovery
from storage import (
    load_conversations,
    load_tools,
    load_mcp_servers,
    load_mcp_server_configs,
    save_app_mcp_server,
    save_conversations,
    write_file,
    append_file,
)
from api import LMStudioClient
from models import Message, MessageRole, Conversation, ConversationSettings
from gi.repository import Gtk, Gio, GLib, Gdk
import logging
import threading
import uuid
import asyncio
from dataclasses import replace
from typing import Optional, Callable
import re
import os
import json
import shlex
import difflib # Added for diff generation
from token_counter import count_text_tokens
from project_map import refresh_project_map
import gi

gi.require_version("Gtk", "3.0")

logger = logging.getLogger(__name__)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("AutoAI - Local AI Chat")
        screen = Gdk.Screen.get_default()
        # Prefer the monitor workarea (usable desktop) when available so default
        # window size is based on the real usable area (avoids panels/docks).
        screen_width = None
        screen_height = None
        if screen:
            try:
                rect = Gdk.Rectangle()
                # Use monitor 0 workarea as a reasonable default
                screen.get_monitor_workarea(0, rect)
                screen_width = int(rect.width)
                screen_height = int(rect.height)
            except Exception:
                try:
                    screen_width = int(screen.get_width())
                    screen_height = int(screen.get_height())
                except Exception:
                    screen_width = int(C.WINDOW_DEFAULT_WIDTH)
                    screen_height = int(C.WINDOW_DEFAULT_HEIGHT)
        else:
            screen_width = int(C.WINDOW_DEFAULT_WIDTH)
            screen_height = int(C.WINDOW_DEFAULT_HEIGHT)

        # Hard cap: window may not exceed actual screen resolution.
        self._window_max_width = min(
            int(getattr(C, "WINDOW_MAX_WIDTH", 2560)), int(screen_width))
        self._window_max_height = min(
            int(getattr(C, "WINDOW_MAX_HEIGHT", 1440)), int(screen_height))
        self._window_min_width = min(
            int(C.WINDOW_MIN_WIDTH), self._window_max_width)
        self._window_min_height = min(
            int(C.WINDOW_MIN_HEIGHT), self._window_max_height)
        start_w = int(getattr(C, "WINDOW_START_WIDTH", 0) or 0)
        start_h = int(getattr(C, "WINDOW_START_HEIGHT", 0) or 0)
        if start_w > 0:
            self._window_min_width = min(self._window_min_width, start_w)
        if start_h > 0:
            self._window_min_height = min(self._window_min_height, start_h)

        # Default window size: use a fraction of the screen (responsive)
        try:
            ratio = float(getattr(C, "WINDOW_DEFAULT_RATIO", 0.5))
            default_width = int(min(
                max(int(screen_width * ratio), self._window_min_width), self._window_max_width))
            default_height = int(min(max(
                int(screen_height * ratio), self._window_min_height), self._window_max_height))
        except Exception:
            default_width = min(int(C.WINDOW_DEFAULT_WIDTH),
                                self._window_max_width)
            default_height = min(
                int(C.WINDOW_DEFAULT_HEIGHT), self._window_max_height)
        # Optional fixed startup dimensions (still clamped by screen and
        # min/max).
        if start_w > 0:
            default_width = min(
                max(start_w, self._window_min_width), self._window_max_width)
        if start_h > 0:
            default_height = min(
                max(start_h, self._window_min_height), self._window_max_height)
        # Keep startup size comfortable even on very large monitors — allow
        # larger initial heights so content fits, but clamp to overall max.
        startup_cap_w = max(self._window_min_width, min(
            int(screen_width * 0.8), int(self._window_max_width)))
        startup_cap_h = max(self._window_min_height, min(
            int(screen_height * 0.85), int(self._window_max_height)))
        default_width = min(default_width, startup_cap_w)
        default_height = min(default_height, startup_cap_h)
        self.set_default_size(default_width, default_height)
        # Allow the window to be resized by the user.
        self.set_resizable(True)
        self.set_size_request(self._window_min_width, self._window_min_height)
        self._apply_window_geometry_hints()
        self.connect("configure-event", self._on_configure_event)

        # Apply CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_path(
            "/home/kingnixon/Documents/Python Projects/AutoAIAgent/ui/styles.css")
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # API client
        self.api_client = LMStudioClient()
        self._loop = None
        self.mcp_discovery = MCPToolDiscovery()

        # Data
        self.conversations = {}
        self.current_conversation: Optional[Conversation] = None
        self.settings = ConversationSettings()
        self.workspace_root = os.path.abspath(os.getcwd())
        self.loaded_model_id: Optional[str] = None
        self._suppress_mode_change = False
        self._agent_running_conversations: set[str] = set()
        self._agent_stop_requests: set[str] = set()
        self._agent_state_lock = threading.Lock()

        # Create layout: a resizable split between sidebar and chat center
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        main_box.set_homogeneous(False)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.new_chat_button.connect("clicked", self._on_new_chat)
        self.sidebar.settings_btn.connect("clicked", self._on_toggle_settings)
        self.sidebar.on_conversation_selected = self._on_conversation_selected
        self.sidebar.on_conversation_delete = self._on_delete_conversation
        self.sidebar.on_tasks_changed = self._on_sidebar_tasks_changed

        # Center: Chat area - constrain width for improved readability
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.center_box = center_box
        center_box.set_homogeneous(False)
        center_box.set_size_request(-1, -1)

        self.chat_area = ChatArea(
            on_edit_message_request=self._on_edit_message,
            on_repush_message_request=self._on_repush_message,
            on_delete_message_request=self._on_delete_message,
        )
        self.chat_area.on_chat_settings_changed = self._on_chat_settings_changed
        center_box.pack_start(self.chat_area, True, True, 0)

        # Input area
        self.chat_input = ChatInput()
        self.chat_input.set_api_client(self.api_client)
        self.chat_input.connect_send(self._on_send_message)
        self.chat_input.connect_mode_changed(self._on_chat_mode_changed)
        self.chat_input.connect_refresh(self._on_refresh_connection)
        center_box.pack_end(self.chat_input, False, False, 0)

        # Right tools panel (resizable)
        self.tools_panel = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tools_panel.get_style_context().add_class("tools-side-panel")

        tools_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tools_header.get_style_context().add_class("tools-side-header")
        tools_header.set_margin_start(12)
        tools_header.set_margin_end(12)
        tools_header.set_margin_top(12)
        tools_header.set_margin_bottom(10)
        tools_title = Gtk.Label()
        tools_title.set_halign(Gtk.Align.START)
        tools_title.set_xalign(0.0)
        tools_title.set_markup(
            "<span weight='600' size='11000'>MCP Tools</span>")
        tools_header.pack_start(tools_title, True, True, 0)
        add_tool_btn = Gtk.Button(label="Add")
        add_tool_btn.set_tooltip_text("Add app-local MCP server")
        add_tool_btn.connect("clicked", self._on_add_mcp_server_clicked)
        tools_header.pack_end(add_tool_btn, False, False, 0)
        self.tools_panel.pack_start(tools_header, False, False, 0)
        self.tools_panel.pack_start(
            Gtk.Separator(
                orientation=Gtk.Orientation.HORIZONTAL),
            False,
            False,
            0)

        mcp_servers = load_mcp_servers()
        self.tools_bar = ToolsBar(
            mcp_servers,
            mcp_discovery=self.mcp_discovery,
            server_configs=load_mcp_server_configs(),
        )
        self.tools_panel.pack_start(self.tools_bar, True, True, 0)

        chat_tools_paned = Gtk.HPaned()
        self.chat_tools_paned = chat_tools_paned
        chat_tools_paned.add1(center_box)
        chat_tools_paned.add2(self.tools_panel)
        # Seed position before first allocation; exact size is applied in idle.
        chat_tools_paned.set_position(max(260, int(default_width * 0.7)))

        # Use a paned splitter so the user can resize sidebar <-> chat area
        paned = Gtk.HPaned()
        self.paned = paned
        paned.add1(self.sidebar)
        paned.add2(chat_tools_paned)
        # Start with a conservative sidebar width so both panes remain visible.
        try:
            base_sidebar = int(getattr(C, "SIDEBAR_WIDTH", 240))
            # Start slightly wider so more conversation titles/content are
            # visible.
            desired = max(250, min(390, base_sidebar + 28))
            desired = min(desired, max(220, int(default_width * 0.3)))
            self._initial_pane_position = desired
            paned.set_position(desired)
            # Right tools panel defaults to roughly sidebar width (+divider
            # allowance).
            self._initial_tools_panel_width = max(220, min(360, desired + 8))
        except Exception:
            self._initial_pane_position = 240
            paned.set_position(260)
            self._initial_tools_panel_width = 248

        # Settings window - opens as full overlay tab with all controls visible
        self.settings_window = SettingsWindow()
        self.settings_window.close_btn.connect(
            "clicked", lambda *_: self._hide_settings_overlay())
        self.settings_window.on_mcp_servers_changed = self._reload_tools_bar
        self.chat_area.set_global_settings_provider(
            self.settings_window.get_settings)

        main_box.pack_start(paned, True, True, 0)

        # Create overlay for settings window
        self.settings_overlay = Gtk.Overlay()
        self.settings_overlay.add(main_box)
        self.settings_overlay.add_overlay(self.settings_window)
        try:
            self.settings_overlay.set_overlay_pass_through(
                self.settings_window, False)
        except Exception:
            pass

        self.add(self.settings_overlay)
        self.show_all()
        GLib.idle_add(self._apply_initial_pane_position)
        # Hide settings window at startup
        self.settings_window.hide()

        # Initialize conversations - load saved or create sample
        self._load_or_create_conversations()

        # Setup keyboard shortcuts
        self._setup_shortcuts()



    def _on_configure_event(self, widget, event):
        """Handle window configure events (e.g. size changes)."""
        print("Configure event triggered")

    async def _async_init(self) -> None:
        """Perform asynchronous initialization tasks."""
        await self.api_client.initialize()
        # Potentially add other async setup tasks here
        await self._check_api_connection_and_update_status()

    async def _check_api_connection_and_update_status(self) -> None:
        """Check API connection and update UI."""
        logger.info("Checking LM Studio API connection...")
        connected = await self.api_client.check_connection()
        if connected:
            model_id = await self.api_client.get_loaded_model_id()
            if model_id:
                logger.info("Connected to LM Studio. Loaded model: %s", model_id)
                GLib.idle_add(
                    self.chat_input.set_model_status,
                    True,
                    f"Connected ({model_id})",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                self.loaded_model_id = model_id
            else:
                logger.warning("Connected to LM Studio, but no model is loaded.")
                GLib.idle_add(
                    self.chat_input.set_model_status,
                    False,
                    "Connected (no model)",
                    priority=GLib.PRIORITY_DEFAULT,
                )
        else:
            logger.error("Failed to connect to LM Studio at %s", self.api_client.endpoint)
            GLib.idle_add(
                self.chat_input.set_model_status,
                False,
                "Disconnected",
                priority=GLib.PRIORITY_DEFAULT,
            )

    def _apply_initial_pane_position(self) -> bool:
        """Apply sidebar split after initial allocation for reliable startup layout."""
        if hasattr(self, "paned"):
            total_width = max(1, self.get_allocated_width())
            desired = int(getattr(self, "_initial_pane_position", 240))
            # Keep divider in a practical range relative to live window width.
            desired = max(160, min(desired, max(200, int(total_width * 0.45))))
            self.paned.set_position(desired)
        if hasattr(self, "chat_tools_paned"):
            pane_width = max(1, self.chat_tools_paned.get_allocated_width())
            target_tools_width = int(
                getattr(
                    self,
                    "_initial_tools_panel_width",
                    248))
            # Keep tools panel visible and avoid collapsing chat area.
            target_tools_width = max(
                200, min(
                    target_tools_width, max(
                        220, int(
                            pane_width * 0.45))))
            desired = pane_width - target_tools_width
            desired = max(260, min(desired, max(320, int(pane_width * 0.8))))
            self.chat_tools_paned.set_position(desired)
        return False

    def _apply_window_geometry_hints(self) -> None:
        """Set min/max geometry hints for the main window."""
        geom = Gdk.Geometry()
        geom.min_width = int(self._window_min_width)
        geom.min_height = int(self._window_min_height)
        geom.max_width = int(self._window_max_width)
        geom.max_height = int(self._window_max_height)
        self.set_geometry_hints(
            None,
            geom,
            Gdk.WindowHints.MIN_SIZE | Gdk.WindowHints.MAX_SIZE,
        )

    def _load_project_constitution(self) -> str:
        """Load the project constitution file."""
        constitution_path = os.path.join(self.workspace_root, "PROJECT_CONSTITUTION.md")
        if not os.path.exists(constitution_path):
            logger.warning("PROJECT_CONSTITUTION.md not found at %s", constitution_path)
            return ""
        try:
            with open(constitution_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Error reading PROJECT_CONSTITUTION.md: %s", e)
            return ""

    def _load_project_index(self) -> dict:
        """Load the project index file."""
        index_path = os.path.join(self.workspace_root, "PROJECT_INDEX.json")
        if not os.path.exists(index_path):
            logger.info("PROJECT_INDEX.json not found at %s. Returning empty index.", index_path)
            return {}
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error("Error decoding PROJECT_INDEX.json: %s", e)
            return {}
        except Exception as e:
            logger.error("Error reading PROJECT_INDEX.md: %s", e)
            return {}

    def _save_project_index(self, index_data: dict) -> None:
        """Save the project index file."""
        index_path = os.path.join(self.workspace_root, "PROJECT_INDEX.json")
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
            logger.info("Successfully saved PROJECT_INDEX.json")
        except Exception as e:
            logger.error("Error saving PROJECT_INDEX.json: %s", e)

    def _load_decision_log(self) -> str:
        """Load the decision log file."""
        log_path = os.path.join(self.workspace_root, "DECISION_LOG.md")
        if not os.path.exists(log_path):
            logger.warning("DECISION_LOG.md not found at %s", log_path)
            return ""
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Error reading DECISION_LOG.md: %s", e)
            return ""
        """Clamp runtime resize requests to safe max bounds.

        We only enforce upper bounds here. Lower bounds are already handled by
        geometry hints, and forcing min-size from transient configure events can
        cause unwanted window snaps while interacting with popovers.
        """
        width = int(getattr(event, "width", 0) or 0)
        height = int(getattr(event, "height", 0) or 0)
        clamped_w = min(width, self._window_max_width)
        clamped_h = min(height, self._window_max_height)
        if (width > self._window_max_width) or (
                height > self._window_max_height):
            GLib.idle_add(lambda: self.resize(clamped_w, clamped_h) or False)
        return False

    def _load_or_create_conversations(self) -> None:
        """Load saved conversations from disk, or create a sample if none exist."""
        saved = load_conversations()
        if saved:
            for conv in saved:
                conv.estimate_context_tokens(model=conv.model)
                self.conversations[conv.id] = conv
                self.sidebar.add_conversation(conv)
            # Load the most recently updated conversation
            latest = max(saved, key=lambda c: c.updated_at)
            self._load_conversation(latest.id)
            logger.info(f"Loaded {len(saved)} saved conversation(s)")
        else:
            # Create sample conversation
            conv = Conversation(
                id=str(uuid.uuid4()),
                title="GTK UI Design",
                model=self._default_model_name(),
            )
            conv.add_message(Message(
                id=str(uuid.uuid4()),
                role=MessageRole.USER,
                content="What are the best practices for GTK4 UI design?"
            ))
            conv.add_message(Message(
                id=str(uuid.uuid4()),
                role=MessageRole.ASSISTANT,
                content="GTK4 emphasizes modern design principles. Key practices include:\n\n- Use CSS for styling and theming\n- Leverage hardware acceleration\n- Design responsive layouts\n- Follow GNOME design guidelines\n- Use reactive programming patterns"
            ))
            self.conversations[conv.id] = conv
            self.sidebar.add_conversation(conv)
            self._load_conversation(conv.id)
            self._save_conversations()

    def _load_conversation(self, conversation_id: str) -> None:
        """Load a conversation into the chat area.

        Args:
            conversation_id: ID of the conversation to load.
        """
        if conversation_id in self.conversations:
            self.current_conversation = self.conversations[conversation_id]
            self.sidebar.set_active_conversation(conversation_id)
            self.sidebar.set_ai_tasks(
                conversation_id, self.current_conversation.ai_tasks)
            self._suppress_mode_change = True
            self.chat_input.set_mode(
                getattr(
                    self.current_conversation,
                    "chat_mode",
                    "ask"))
            self._suppress_mode_change = False
            settings = self._get_effective_settings(self.current_conversation)
            self.chat_area.set_conversation(
                self.current_conversation,
                context_limit=settings.context_limit)
            self.chat_input.focus()

    def _on_chat_settings_changed(
            self, conversation: Conversation, payload: dict) -> None:
        """Handle updates from per-chat popout settings."""
        if conversation.id not in self.conversations:
            return
        self.conversations[conversation.id].chat_settings = payload
        if self.current_conversation and self.current_conversation.id == conversation.id:
            effective = self._get_effective_settings(conversation)
            self.chat_area.set_context_limit(effective.context_limit)
        self._save_conversations()

    def _on_chat_mode_changed(self, _combo) -> None:
        """Persist per-conversation mode selection from input footer."""
        if self._suppress_mode_change:
            return
        if not self.current_conversation:
            return
        mode = self.chat_input.get_mode()
        if mode == "agent":
            if not self._ensure_agent_config(self.current_conversation):
                self._suppress_mode_change = True
                self.chat_input.set_mode("ask")
                self._suppress_mode_change = False
                self.current_conversation.chat_mode = "ask"
                self._save_conversations()
                return
        if getattr(self.current_conversation, "chat_mode", "ask") == mode:
            return
        if mode != "agent":
            self._request_agent_stop(
                self.current_conversation.id,
                "Mode switched away from Agent.")
        self.current_conversation.chat_mode = mode
        self._save_conversations()

    def _on_sidebar_tasks_changed(
            self, conversation_id: str, tasks: list[dict]) -> None:
        """Persist AI task changes coming from sidebar AI Tasks tab."""
        if conversation_id not in self.conversations:
            return
        cleaned = self._normalize_task_list(tasks)
        self.conversations[conversation_id].ai_tasks = cleaned
        self._save_conversations()

    def _get_effective_settings(
            self, conversation: Conversation) -> ConversationSettings:
        """Merge per-chat overrides on top of global settings."""
        global_settings = self.settings_window.get_settings()
        chat_settings = conversation.chat_settings if isinstance(
            conversation.chat_settings, dict) else None
        if not chat_settings or not chat_settings.get("enabled"):
            return global_settings

        overrides = {}
        for key in (
            "temperature",
            "top_p",
            "repetition_penalty",
            "max_tokens",
            "context_limit",
            "token_saver",
            "system_prompt",
        ):
            if key in chat_settings:
                overrides[key] = chat_settings[key]
        return replace(global_settings, **overrides)

    def _on_conversation_selected(self, conversation: Conversation) -> None:
        """Handle conversation selection from sidebar.

        Args:
            conversation: The selected conversation.
        """
        self._load_conversation(conversation.id)

    def _on_delete_conversation(self, conversation: Conversation) -> None:
        """Handle conversation delete request with confirmation."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Delete conversation?",
        )
        dialog.format_secondary_text(
            f'"{conversation.title}" and all its messages will be permanently deleted.'
        )
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        conv_id = conversation.id
        self.sidebar.remove_conversation(conv_id)
        del self.conversations[conv_id]
        self._save_conversations()
        if self.current_conversation and self.current_conversation.id == conv_id:
            remaining = list(self.conversations.values())
            if remaining:
                next_conv = max(remaining, key=lambda c: c.updated_at)
                self._load_conversation(next_conv.id)
            else:
                self.current_conversation = None
                self.chat_area.clear()
                self.chat_area._title_label.set_label("New Conversation")
                self.chat_area._subtitle_label.set_label("")

    def _show_context_limit_warning(
            self, current_tokens: int, limit: int) -> None:
        """Show a warning dialog when context limit is exceeded.

        Args:
            current_tokens: Current context tokens.
            limit: The context limit in tokens.
        """
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="Context Limit Exceeded",
        )
        dialog.format_secondary_text(
            f"The conversation context ({current_tokens:,} tokens) exceeds your limit "
            f"({limit:,} tokens). "
            "The API will use a sliding window to keep the most recent messages. "
            "You can adjust the context limit in Settings → Model."
        )
        dialog.run()
        dialog.destroy()

    def _on_toggle_settings(self, button) -> None:
        """Toggle settings window visibility."""
        visible = bool(self.settings_window.get_visible())
        if visible:
            self._hide_settings_overlay()
        else:
            self._show_settings_overlay()

    def _on_settings_window_delete(self, _window, _event) -> bool:
        """Compatibility handler; hide settings panel."""
        self._hide_settings_overlay()
        return True

    def _show_settings_overlay(self) -> None:
        """Show settings window overlay with all controls visible."""
        self.settings_window.show_all()
        self.settings_window.grab_focus()

    def _hide_settings_overlay(self) -> None:
        """Hide settings window overlay."""
        self.settings_window.hide()

    def _save_conversations(self) -> None:
        """Persist all conversations to disk."""
        save_conversations(list(self.conversations.values()))

    def _on_new_chat(self, button) -> None:
        """Create a new conversation.

        Args:
            button: The clicked button.
        """
        new_id = str(uuid.uuid4())
        new_conv = Conversation(
            id=new_id,
            title=f"Conversation {len(self.conversations) + 1}",
            model=self._default_model_name(),
        )
        self.conversations[new_id] = new_conv
        self.sidebar.add_conversation(new_conv)
        self._load_conversation(new_id)
        self._save_conversations()

    def _on_refresh_connection(self, _button) -> None:
        """Handle refresh button click in chat input to re-check API connection."""
        GLib.idle_add(
            lambda: asyncio.ensure_future(self._check_api_connection_and_update_status()),
            priority=GLib.PRIORITY_DEFAULT,
        )

    def _on_send_message(self, button) -> None:
        """Handle message sending.

        Args:
            button: The send button.
        """
        logger.debug("Entering _on_send_message")
        if not self.current_conversation:
            logger.debug("_on_send_message: No current conversation.")
            return

        text = self.chat_input.get_text().strip()
        if not text:
            logger.debug("_on_send_message: Empty message text.")
            return
        logger.debug("_on_send_message: Message text received. Mode: %s", self.chat_input.get_mode())

        mode = self.chat_input.get_mode()
        if mode == "agent":
            if not self._ensure_agent_config(self.current_conversation):
                logger.debug("_on_send_message: Agent config not ensured.")
                return
        conv_id = self.current_conversation.id
        if self._is_agent_running(conv_id):
            self._request_agent_stop(
                conv_id,
                "User submitted a new message. Current agent run will stop after the active step.",
            )
            logger.debug("_on_send_message: Agent is running, request stop.")
        if getattr(self.current_conversation, "chat_mode", "ask") != mode:
            self.current_conversation.chat_mode = mode
            self._save_conversations()
            logger.debug("_on_send_message: Chat mode changed and saved.")

        logger.info("User: %s", text)
        logger.info("Mode: %s", mode)

        # Add user message
        logger.debug("_on_send_message: Adding user message to conversation.")
        user_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=text,
            tokens=asyncio.run(
                self.api_client.count_tokens(
                    text, model=self.current_conversation.model
                )
            ),
        )
        self.current_conversation.add_message(user_msg)
        self.chat_area.add_message(user_msg)
        self._save_conversations()
        logger.debug("_on_send_message: User message added and conversation saved.")

        # Clear input
        self.chat_input.clear()
        logger.debug("_on_send_message: Chat input cleared.")

        # Check context limit before proceeding
        settings = self._get_effective_settings(self.current_conversation)
        context_tokens = self.current_conversation.estimate_context_tokens(
            model=self.current_conversation.model
        )
        if (not settings.token_saver) and context_tokens > settings.context_limit:
            self._show_context_limit_warning(
                context_tokens, settings.context_limit)
            # Show typing indicator anyway since user message is added
            self.chat_area.show_typing_indicator()
            logger.debug("_on_send_message: Context limit exceeded, warning shown.")
        else:
            # Show typing indicator
            self.chat_area.show_typing_indicator()
            logger.debug("_on_send_message: Showing typing indicator.")

        # Capture conversation for this request - ensures full context is sent
        # even if user switches conversations before response arrives
        conv = self.current_conversation
        conv_id = conv.id
        if mode == "agent" and self._is_agent_running(conv_id):
            self.chat_area.hide_typing_indicator()
            logger.debug("_on_send_message: Agent is running, hiding typing indicator and returning.")
            return
        
        logger.debug("_on_send_message: Starting _fetch_ai_response in a new thread.")
        threading.Thread(
            target=self._fetch_ai_response,
            args=(text, conv, conv_id, settings, mode),
            daemon=True,
        ).start()
        logger.debug("Exiting _on_send_message.")

    def _fetch_ai_response(
        self, user_text: str, conversation: Conversation, conversation_id: str,
        settings: ConversationSettings, mode: str
    ) -> None:
        """Fetch AI response from API (runs in background thread).

        Uses the captured conversation so full context (all prior messages)
        is always sent to the API for memory.

        Args:
            user_text: The user's message text.
            conversation: The conversation object.
            conversation_id: ID of the conversation.
            settings: The current conversation settings.
        """
        logger.debug("Entering _fetch_ai_response for conversation: %s, mode: %s", conversation_id, mode)

        if mode == "agent":
            logger.debug("_fetch_ai_response: Agent mode detected.")
            if self._is_agent_running(conversation_id):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    "Agent is already running for this conversation.",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                GLib.idle_add(
                    self._hide_typing_indicator_for_conversation,
                    conversation_id,
                    priority=GLib.PRIORITY_DEFAULT,
                )
                logger.debug("_fetch_ai_response: Agent already running, returning.")
                return
            self._set_agent_running(conversation_id, True)
            self._clear_agent_stop_request(conversation_id)
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    logger.debug("_fetch_ai_response: Starting agent mode sequence.")
                    loop.run_until_complete(
                        self._run_agent_mode_sequence(
                            conversation=conversation,
                            conversation_id=conversation_id,
                            settings=settings,
                            user_text=user_text,
                        )
                    )
                    logger.debug("_fetch_ai_response: Agent mode sequence completed.")
                finally:
                    loop.close()
            except Exception as e:
                logger.warning("_fetch_ai_response: Agent mode run failed: %s", e)
                GLib.idle_add(
                    self._add_assistant_message_and_save,
                    "Agent mode encountered an error and stopped. Check logs and task list, then retry.",
                    conversation_id,
                    [],
                    None,
                    priority=GLib.PRIORITY_DEFAULT,
                )
            finally:
                self._set_agent_running(conversation_id, False)
                GLib.idle_add(
                    self._hide_typing_indicator_for_conversation,
                    conversation_id,
                    priority=GLib.PRIORITY_DEFAULT,
                )
            logger.debug("Exiting _fetch_ai_response (agent mode).")
            return

        response_text = None
        tool_events = []
        followup_message = ""
        followup_tasks: list[dict] = []
        try:
            global asyncio_thread # Access the global asyncio thread
            if asyncio_thread.loop and asyncio_thread.loop.is_running():
                logger.debug("_fetch_ai_response: Submitting _get_api_response to asyncio_thread.")
                
                # Submit _get_api_response to the asyncio thread and wait for its result.
                # asyncio.run_coroutine_threadsafe returns a Future.
                # .result() blocks until the coroutine completes or raises an exception.
                future = asyncio.run_coroutine_threadsafe(
                    self._get_api_response(conversation, settings, mode=mode),
                    asyncio_thread.loop
                )
                response_text, tool_events, planned_tasks = future.result() # This will block until result is ready
                
                logger.debug("_fetch_ai_response: _get_api_response returned from asyncio_thread. Response text length: %d", len(response_text) if response_text else 0)
                
                if mode == "plan" and response_text:
                    logger.debug("_fetch_ai_response: Submitting _plan_mode_review_for_missing_info to asyncio_thread.")
                    plan_review_future = asyncio.run_coroutine_threadsafe(
                        self._plan_mode_review_for_missing_info(
                            conversation=conversation,
                            settings=settings,
                            plan_response=response_text,
                            planned_tasks=planned_tasks,
                        ),
                        asyncio_thread.loop
                    )
                    followup_message, followup_tasks = plan_review_future.result()
                    logger.debug("_fetch_ai_response: _plan_mode_review_for_missing_info returned.")
            else:
                logger.error("Asyncio loop not running in separate thread during _fetch_ai_response.")
                raise ConnectionError("Asyncio event loop is not running. Cannot reach LM Studio.")
        except Exception as e:
            logger.warning("API request failed (%s), using fallback: %s", type(e).__name__, e)
            GLib.idle_add(
                self._add_assistant_message_and_save,
                f"API request failed: {type(e).__name__} - {e}. Using fallback response.",
                conversation_id,
                [],
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )
            planned_tasks = []
            followup_message = ""
            followup_tasks = []

        if response_text is None:
            logger.debug("_fetch_ai_response: response_text is None, generating random fallback.")
            import random
            responses = [
                "That's a great question! Let me think about that...",
                "I understand. Here's what I think about that topic.",
                "Interesting point. In my experience, the key considerations are:",
                "I can help with that. Let me break it down for you.",
            ]
            response_text = random.choice(responses)

        logger.info("Assistant: %s", response_text)

        # Update UI on main thread - pass conv id so we add to correct
        # conversation
        logger.debug("_fetch_ai_response: Updating UI on main thread.")
        GLib.idle_add(
            self._add_assistant_message_and_save,
            response_text,
            conversation_id,
            tool_events,
            planned_tasks,
            priority=GLib.PRIORITY_DEFAULT,
        )
        if followup_message or followup_tasks:
            logger.debug("_fetch_ai_response: Adding plan followup.")
            GLib.idle_add(
                self._add_plan_followup_and_save,
                followup_message,
                conversation_id,
                followup_tasks,
                priority=GLib.PRIORITY_DEFAULT,
            )
        logger.debug("Exiting _fetch_ai_response.")

    async def _get_api_response(
        self,
        conversation: Conversation,
        settings: ConversationSettings,
        mode: str = "ask",
    ) -> tuple[Optional[str], list[dict], list[dict]]:
        """Call LM Studio API with conversation context and current settings.

        Args:
            conversation: The conversation with message history.
            settings: The current conversation settings including context limit.

        Returns:
            Tuple of (response text, tool events list).
        """
        if not conversation or not self.api_client.is_connected:
            return (None, [], [])
        # Start with the provided settings
        current_settings = settings
        current_settings = replace(
            current_settings,
            system_prompt=self._build_mode_system_prompt(
                mode=mode,
                base_prompt=str(current_settings.system_prompt or ""),
                tasks=conversation.ai_tasks if isinstance(
                    conversation.ai_tasks, list) else [],
            ),
        )
        configured_tools, configured_tool_choice = load_tools()
        enabled_tool_metadata = self.tools_bar.get_enabled_tool_metadata()
        enabled_mcp = [tool["id"] for tool in enabled_tool_metadata]
        builtin_enabled = "mcp/builtin_filesystem" in enabled_mcp
        enabled_mcp_external = [
            iid for iid in enabled_mcp if iid != "mcp/builtin_filesystem"]
        selected_tools: list[dict] = []
        tool_choice = None

        # Discover full MCP tool definitions (name/description/input schema)
        # from enabled endpoints.
        if enabled_mcp_external:
            server_configs = load_mcp_server_configs()
            discovered_tools = await self.mcp_discovery.discover_tools(
                server_configs=server_configs,
                enabled_integrations=enabled_mcp_external,
            )
            logger.info(
                "Discovered %d tools from %d enabled integrations (%s)",
                len(discovered_tools),
                len(enabled_mcp_external),
                ", ".join(enabled_mcp_external),
            )
            # Log each discovered tool
            for tool in discovered_tools:
                if isinstance(tool, dict):
                    fn = tool.get("function") or {}
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")
                    params = fn.get("parameters", {})
                    logger.debug(
                        "Tool: %s - %s (params: %s)",
                        name,
                        desc,
                        "object" if isinstance(params, dict) else "unknown",
                    )
            selected_tools.extend(discovered_tools)
        else:
            server_configs = {}

        # Optionally merge configured tools tied to enabled integrations.
        if configured_tools is not None and enabled_mcp_external:
            selected_tools.extend(
                self._select_tools_for_enabled_integrations(
                    configured_tools, enabled_mcp_external)
            )

        if builtin_enabled:
            selected_tools.extend(self._builtin_filesystem_tools())

        # Dedupe by function name to avoid duplicates when merging sources.
        selected_tools = self._dedupe_tool_definitions(selected_tools)

        # Fallback: if we have enabled integrations but no discovered tools, create minimal placeholders
        # so the API receives tool definitions to work with
        if enabled_mcp_external and not selected_tools and not builtin_enabled:
            logger.warning(
                "No tools discovered for enabled integrations %s; creating placeholder tools",
                enabled_mcp_external,
            )
            for integration_id in enabled_mcp_external:
                # Create a minimal tool definition to send to the API
                # This allows the API to reference the integration even if full
                # discovery failed
                placeholder_tool = {
                    "type": "function",
                    "function": {
                        "name": integration_id.replace("/", "_").replace("-", "_"),
                        "description": f"Call {integration_id} MCP integration (discovery details unavailable)",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "method": {
                                    "type": "string",
                                    "description": "The method name to call on this integration"
                                },
                                "args": {
                                    "type": "object",
                                    "description": "Arguments for the method"
                                }
                            },
                            "required": ["method"]
                        }
                    }
                }
                selected_tools.append(placeholder_tool)

        if selected_tools:
            tool_choice = configured_tool_choice if configured_tool_choice is not None else "auto"
            current_settings = replace(
                current_settings, tools=selected_tools, tool_choice=tool_choice
            )
            # Log final tool list being sent to API
            logger.info(
                "Sending %d tools to API with tool_choice='%s'",
                len(selected_tools),
                tool_choice)
            for tool in selected_tools:
                if isinstance(tool, dict):
                    fn = tool.get("function") or {}
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")
                    logger.info("  • %s: %s", name, desc)

        if enabled_mcp_external:
            current_settings = replace(
                current_settings, integrations=enabled_mcp_external)
        mcp_tool_map = self._build_mcp_tool_map(selected_tools)
        tool_events: list[dict] = []
        ev_collector = lambda ev: tool_events.append(ev) # Define the event collector
        response_text = await self.api_client.chat_completion_with_tools(
            conversation=conversation,
            settings=current_settings,
            tool_executor=lambda name, args: self._execute_tool_call_with_approval(
                name,
                args,
                settings=current_settings,
                mcp_tool_map=mcp_tool_map,
                server_configs=server_configs,
                on_tool_event=ev_collector, # Pass the collector function
            ),
            on_tool_event=lambda ev: tool_events.append(ev),
        )
        planned_tasks = []
        if mode == "plan" and response_text:
            planned_tasks = self._extract_tasks_from_plan_response(
                response_text)
        return (response_text, tool_events, planned_tasks)

    async def _execute_tool_call_with_approval(
        self,
        tool_name: str,
        args: dict,
        settings: ConversationSettings,
        mcp_tool_map: Optional[dict[str, dict]] = None,
        server_configs: Optional[dict[str, dict]] = None,
        on_tool_event: Optional[Callable[[dict], None]] = None, # Added on_tool_event
    ) -> str:
        """Prompt user for tool permission before execution unless auto-approved."""
        if not settings.auto_tool_approval:
            approved, enable_auto = await asyncio.to_thread(
                self._request_tool_permission_blocking, tool_name, args
            )
            if enable_auto:
                settings.auto_tool_approval = True
                GLib.idle_add(lambda: self.settings_window.set_auto_tool_approval(True) or False)
            if not approved:
                tool_event = {
                    "name": tool_name,
                    "args": args,
                    "status": "error",
                    "result": {"ok": False, "error": "Tool execution rejected by user."},
                    "details": {"type": "tool_error", "message": "Tool execution rejected by user."}
                }
                if on_tool_event:
                    on_tool_event(tool_event)
                return json.dumps(tool_event["result"], ensure_ascii=False)
        
        json_result, tool_event = await self._execute_tool_call(
            tool_name,
            args,
            mcp_tool_map=mcp_tool_map,
            server_configs=server_configs,
        )
        if on_tool_event:
            on_tool_event(tool_event)
        return json_result

    def _request_tool_permission_blocking(self, tool_name: str, args: dict) -> tuple[bool, bool]:
        """Show a blocking permission dialog on the GTK thread.

        Returns:
            (approved, enable_auto_approval)
        """
        done = threading.Event()
        result = {"approved": False, "enable_auto": False}

        def _show_dialog() -> bool:
            dialog = Gtk.Dialog(
                title="Tool Permission Required",
                transient_for=self,
                flags=0,
            )
            dialog.set_modal(True)
            dialog.add_button("Deny", Gtk.ResponseType.CANCEL)
            dialog.add_button("Approve", Gtk.ResponseType.OK)
            dialog.add_button("Approve + Auto", Gtk.ResponseType.APPLY)
            dialog.set_default_response(Gtk.ResponseType.OK)
            dialog.set_default_size(620, 360)

            area = dialog.get_content_area()
            area.set_spacing(8)
            area.set_margin_start(12)
            area.set_margin_end(12)
            area.set_margin_top(12)
            area.set_margin_bottom(12)

            title = Gtk.Label()
            title.set_xalign(0.0)
            title.set_markup(
                f"<b>The AI wants to run tool:</b> <tt>{GLib.markup_escape_text(str(tool_name))}</tt>"
            )
            area.pack_start(title, False, False, 0)

            args_label = Gtk.Label(label="Arguments:")
            args_label.set_xalign(0.0)
            area.pack_start(args_label, False, False, 0)

            args_view = Gtk.TextView()
            args_view.set_editable(False)
            args_view.set_cursor_visible(False)
            args_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            args_text = json.dumps(args or {}, indent=2, ensure_ascii=False)
            if len(args_text) > 8000:
                args_text = args_text[:8000] + "\n... [truncated]"
            args_view.get_buffer().set_text(args_text, -1)

            args_scroll = Gtk.ScrolledWindow()
            args_scroll.set_hexpand(True)
            args_scroll.set_vexpand(True)
            args_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            args_scroll.add(args_view)
            area.pack_start(args_scroll, True, True, 0)

            dialog.show_all()
            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.OK:
                result["approved"] = True
            elif response == Gtk.ResponseType.APPLY:
                result["approved"] = True
                result["enable_auto"] = True
            done.set()
            return False

        GLib.idle_add(_show_dialog)
        done.wait(timeout=600.0)
        return (bool(result["approved"]), bool(result["enable_auto"]))

    def _add_assistant_message_and_save(
        self,
        response_text: str,
        conversation_id: str,
        tool_events: Optional[list[dict]] = None,
        planned_tasks: Optional[list[dict]] = None,
    ) -> bool:
        """Add assistant message to UI and save (runs on main thread)."""
        if conversation_id not in self.conversations:
            return False
        conv = self.conversations[conversation_id]
        ai_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content=response_text,
            tokens=count_text_tokens(response_text, model=conv.model),
            meta={"tool_events": tool_events or []},
        )
        conv.add_message(ai_msg)
        if planned_tasks:
            conv.ai_tasks = planned_tasks
            self.sidebar.set_ai_tasks(conversation_id, planned_tasks)
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.current_conversation = conv
            self.chat_area.hide_typing_indicator()
            self.chat_area.add_message(ai_msg)
        self._save_conversations()
        return False  # Don't reschedule idle

    async def _run_agent_mode_sequence(
        self,
        conversation: Conversation,
        conversation_id: str,
        settings: ConversationSettings,
        user_text: str,
    ) -> None:
        """Execute pending tasks one-by-one in agent mode with compile checks."""
        task_list = self._normalize_task_list(conversation.ai_tasks)
        pending_indices = [
            idx for idx, t in enumerate(task_list)
            if str(t.get("status", "uncompleted")) != "completed"
        ]
        if not pending_indices:
            GLib.idle_add(
                self._add_assistant_message_and_save,
                "[Agent] No pending tasks in AI Tasks.",
                conversation_id,
                [],
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )
            return

        cfg = conversation.agent_config if isinstance(conversation.agent_config, dict) else {}
        project_name = str(cfg.get("project_name", "Project")).strip() or "Project"
        project_dir = os.path.abspath(str(cfg.get("project_dir", self.workspace_root)).strip() or self.workspace_root)
        
        project_constitution = self._load_project_constitution()
        if project_constitution:
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                "Loaded Project Constitution.",
                priority=GLib.PRIORITY_DEFAULT,
            )

        project_index_data = self._load_project_index()
        if project_index_data:
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                "Loaded Dynamic Project Index.",
                priority=GLib.PRIORITY_DEFAULT,
            )

        decision_log_content = self._load_decision_log()
        if decision_log_content:
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                "Loaded Architectural Decision Log.",
                priority=GLib.PRIORITY_DEFAULT,
            )

        GLib.idle_add(
            self._add_agent_progress_message,
            conversation_id,
            f"Starting implementation for {project_name} in {project_dir}.",
            priority=GLib.PRIORITY_DEFAULT,
        )

        for iteration_num, task_index in enumerate(pending_indices, start=1):
            if self._is_agent_stop_requested(conversation_id):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    "Agent run paused by user. Resume in Agent mode to continue from current task.",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return
            conv_live = self.conversations.get(conversation_id)
            if not conv_live:
                return
            live_tasks = self._normalize_task_list(conv_live.ai_tasks)
            if task_index >= len(live_tasks):
                continue
            task = live_tasks[task_index]
            task_text = str(task.get("text", "")).strip()
            if not task_text:
                continue

            GLib.idle_add(
                self._set_task_status_and_save,
                conversation_id,
                task_index,
                "in_progress",
                priority=GLib.PRIORITY_DEFAULT,
            )
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Task {iteration_num}/{len(pending_indices)} in progress: {task_text}",
                priority=GLib.PRIORITY_DEFAULT,
            )

            # --- Prepare Global Context ---
            global_context = ""
            if project_constitution:
                global_context += f"PROJECT CONSTITUTION:\n{project_constitution}\n\n"
            if project_index_data:
                global_context += f"DYNAMIC PROJECT INDEX:\n```json\n{json.dumps(project_index_data, indent=2, ensure_ascii=False)}\n```\n\n"
            if decision_log_content:
                global_context += f"ARCHITECTURAL DECISION LOG:\n```markdown\n{decision_log_content}\n```\n\n"
            if conv_live.active_context_files:
                active_files_context_parts = []
                for path, content in conv_live.active_context_files.items():
                    active_files_context_parts.append(f"--- ACTIVE FILE: {path} ---\n```\n{content}\n```")
                global_context += "ACTIVE CONTEXT FILES:\n" + "\n\n".join(active_files_context_parts) + "\n\n"
            
            global_context += (
                f"Project name: {project_name}\n"
                f"Project directory: {project_dir}\n"
                f"User request context: {user_text}\n"
            )

            # --- Phase 1: Intent Validation ---
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Phase 1: Validating intent for task {iteration_num}...",
                priority=GLib.PRIORITY_DEFAULT,
            )
            validation_response = await self._phase1_intent_validation(
                conversation=conv_live,
                conversation_id=conversation_id,
                settings=settings,
                user_text=user_text,
                task_text=task_text,
                global_context=global_context,
                iteration_num=iteration_num,
            )

            if not validation_response.get("ok"):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    f"Intent Validation failed for Task {iteration_num}: {validation_response.get('error')}",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run on validation failure

            validation_result = validation_response.get("result", {})
            GLib.idle_add(
                self._add_assistant_message_and_save,
                f"[Agent - Phase 1 Validation]\n{json.dumps(validation_result, indent=2)}",
                conversation_id,
                [],
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )

            if not validation_result.get("proceed_with_task"):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    f"Intent Validation for Task {iteration_num} advised NOT to proceed: {validation_result.get('reason_for_decision')}. Agent run stopped.",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                GLib.idle_add(
                    self._set_task_status_and_save,
                    conversation_id,
                    task_index,
                    "uncompleted", # Mark as uncompleted for reconsideration
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run if validation says not to proceed

            # --- Phase 2: Design Draft ---
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Phase 2: Drafting design for task {iteration_num}...",
                priority=GLib.PRIORITY_DEFAULT,
            )
            design_response = await self._phase2_design_draft(
                conversation=conv_live,
                conversation_id=conversation_id,
                settings=settings,
                user_text=user_text,
                task_text=task_text,
                global_context=global_context,
                iteration_num=iteration_num,
                validation_feedback=validation_result,
            )

            if not design_response.get("ok"):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    f"Design Draft failed for Task {iteration_num}: {design_response.get('error')}",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run on design failure

            design_draft_content = design_response.get("result", "No design draft provided.")
            GLib.idle_add(
                self._add_assistant_message_and_save,
                f"[Agent - Phase 2 Design Draft]\n{design_draft_content}",
                conversation_id,
                [],
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )
            
            # --- Phase 3: Implementation ---
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Phase 3: Implementing task {iteration_num}...",
                priority=GLib.PRIORITY_DEFAULT,
            )
            
            # This is the existing implementation logic, encapsulated
            implementation_instruction = (
                f"{global_context}"
                f"Execute exactly this one task now: {task_text}\n"
                "Use tools if needed. After finishing, summarize what changed."
            )
            temp_conv = Conversation(
                id=conv_live.id,
                title=conv_live.title,
                messages=list(conv_live.messages),
                created_at=conv_live.created_at,
                updated_at=conv_live.updated_at,
                model=conv_live.model,
                total_tokens=conv_live.total_tokens,
                chat_settings=conv_live.chat_settings,
                ai_tasks=list(live_tasks),
                chat_mode=conv_live.chat_mode,
                agent_config=conv_live.agent_config,
                active_context_files=conv_live.active_context_files,
            )
            temp_conv.add_message(
                Message(
                    id=str(uuid.uuid4()),
                    role=MessageRole.USER,
                    content=implementation_instruction,
                )
            )

            # Agent calls can occasionally time out while local model is busy.
            # Retry once after a short pause before failing the whole run.
            response_text = None
            tool_events = []
            last_err: Optional[Exception] = None
            for attempt in range(2):
                try:
                    response_text, tool_events, _ = await self._get_api_response(
                        temp_conv,
                        settings,
                        mode="agent",
                    )
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    err_text = str(e).lower()
                    is_timeout = ("timed out" in err_text) or ("timeout" in err_text)
                    if (attempt == 0) and is_timeout:
                        if self._is_agent_stop_requested(conversation_id):
                            GLib.idle_add(
                                self._add_agent_progress_message,
                                conversation_id,
                                "Agent run paused by user.",
                                priority=GLib.PRIORITY_DEFAULT,
                            )
                            return
                        GLib.idle_add(
                            self._add_agent_progress_message,
                            conversation_id,
                            "Model request timed out. Waiting 10 seconds, then retrying...",
                            priority=GLib.PRIORITY_DEFAULT,
                        )
                        await asyncio.sleep(10)
                        if self._is_agent_stop_requested(conversation_id):
                            GLib.idle_add(
                                self._add_agent_progress_message,
                                conversation_id,
                                "Agent run paused by user.",
                                priority=GLib.PRIORITY_DEFAULT,
                            )
                            return
                        continue
                    break
            if last_err is not None:
                raise last_err
            if self._is_agent_stop_requested(conversation_id):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    "Agent run paused by user. Resume in Agent mode to continue.",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return

            # Add detailed activity log for each tool event
            if tool_events:
                for event in tool_events:
                    GLib.idle_add(
                        self._add_agent_activity_log,
                        conversation_id,
                        event,
                        iteration_num,
                        priority=GLib.PRIORITY_DEFAULT,
                    )

            GLib.idle_add(
                self._add_assistant_message_and_save,
                response_text or f"[Agent] Task {iteration_num} completed with no summary.",
                conversation_id,
                tool_events,
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )
            if tool_events:
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    self._format_agent_tool_output(iteration_num, tool_events),
                    priority=GLib.PRIORITY_DEFAULT,
                )

            compile_ok, compile_detail = await self._run_compile_check(project_dir)
            compile_status = {"ok": compile_ok, "detail": compile_detail}
            if not compile_ok:
                GLib.idle_add(
                    self._set_task_status_and_save,
                    conversation_id,
                    task_index,
                    "uncompleted",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    "Compile check failed. Agent stopped.\n"
                    f"{compile_detail}",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run on compile failure

            # --- Phase 4: Post-Implementation Critique ---
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Phase 4: Critiquing implementation for task {iteration_num}...",
                priority=GLib.PRIORITY_DEFAULT,
            )
            critique_response = await self._phase4_post_implementation_critique(
                conversation=conv_live,
                conversation_id=conversation_id,
                settings=settings,
                user_text=user_text,
                task_text=task_text,
                global_context=global_context,
                implementation_summary=implementation_summary,
                iteration_num=iteration_num,
                compile_status=compile_status,
            )

            if not critique_response.get("ok"):
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    f"Post-Implementation Critique failed for Task {iteration_num}: {critique_response.get('error')}",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run on critique failure

            critique_result = critique_response.get("result", {})
            GLib.idle_add(
                self._add_assistant_message_and_save,
                f"[Agent - Phase 4 Critique]\n{json.dumps(critique_result, indent=2)}",
                conversation_id,
                [],
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )

            if critique_result.get("flaws_found"):
                new_tasks = critique_result.get("new_tasks_needed", [])
                if new_tasks and isinstance(new_tasks, list):
                    current_ai_tasks = self._normalize_task_list(conv_live.ai_tasks)
                    for new_task_desc in new_tasks:
                        current_ai_tasks.append({"text": new_task_desc, "done": False, "status": "uncompleted"})
                    conv_live.ai_tasks = current_ai_tasks
                    self._save_conversations()
                    self.sidebar.set_ai_tasks(conversation_id, current_ai_tasks)
                    GLib.idle_add(
                        self._add_agent_progress_message,
                        conversation_id,
                        f"Critique found flaws. Added {len(new_tasks)} new tasks for reconsideration.",
                        priority=GLib.PRIORITY_DEFAULT,
                    )
                else:
                    GLib.idle_add(
                        self._add_agent_progress_message,
                        conversation_id,
                        "Critique found flaws but no new tasks were suggested. Agent run stopped.",
                        priority=GLib.PRIORITY_DEFAULT,
                    )
                GLib.idle_add(
                    self._set_task_status_and_save,
                    conversation_id,
                    task_index,
                    "uncompleted", # Mark as uncompleted for reconsideration
                    priority=GLib.PRIORITY_DEFAULT,
                )
                return # Stop agent run if flaws found

            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                f"Task {iteration_num} accepted. Marking as completed.",
                priority=GLib.PRIORITY_DEFAULT,
            )
            GLib.idle_add(
                self._set_task_status_and_save,
                conversation_id,
                task_index,
                "completed",
                priority=GLib.PRIORITY_DEFAULT,
            )

        GLib.idle_add(
            self._add_agent_progress_message,
            conversation_id,
            "All pending tasks completed.",
            priority=GLib.PRIORITY_DEFAULT,
        )

    def _add_agent_activity_log(
        self, conversation_id: str, tool_event: dict, task_ordinal: int
    ) -> bool:
        """Add a formatted agent tool activity log message."""
        if conversation_id not in self.conversations:
            return False
        
        name = str(tool_event.get("name", "tool"))
        status = str(tool_event.get("status", "unknown"))
        details = tool_event.get("details", {})
        
        icon = self._get_tool_event_icon(details.get("type", ""), status)
        title = f"{icon} **Tool: {name}** (Task {task_ordinal})"
        body = self._format_tool_event_details(name, details)
        
        message_content = f"{title}\n{body}"
        
        return self._add_assistant_message_and_save(
            message_content,
            conversation_id,
            tool_events=[tool_event], # Include the event for detailed view
            planned_tasks=None,
        )

    def _get_tool_event_icon(self, detail_type: str, status: str) -> str:
        """Helper to get an icon for a tool event."""
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
        return "🛠️" # Default tool icon

    def _format_agent_tool_output(self, task_num: int, tool_events: list[dict]) -> str:
        """Build readable per-task tool execution output for chat."""
        lines = []
        for ev in tool_events or []:
            if not isinstance(ev, dict):
                continue
            name = str(ev.get("name", "tool"))
            status = str(ev.get("status", "unknown"))
            details = ev.get("details", {})
            error_message = ""
            if status == "error":
                error_message = str(details.get("message", "An unknown error occurred."))
                if "exception" in details:
                    error_message += f" ({details['exception']})"
            
            icon = self._get_tool_event_icon(details.get("type", ""), status)
            lines.append(f"{icon} ### Tool: `{name}` (Status: {status.upper()})")
            if error_message:
                lines.append(f"**Error:** {error_message}")
            lines.append(self._format_tool_event_details(name, details))

        return "\n".join(lines)

    def _format_tool_event_details(self, tool_name: str, details: dict) -> str:
        """Format specific tool event details into a human-readable string."""
        detail_type = details.get("type")
        
        if detail_type == "file_edit":
            path = details.get("path", "unknown file")
            diff = details.get("diff", "No diff available.")
            return f"**File Edited:** `{path}`\n```diff\n{diff}\n```"
        
        elif detail_type == "file_write":
            path = details.get("path", "unknown file")
            bytes_written = details.get("bytes_written", 0)
            content_preview = details.get("content_preview", "")
            preview_line = f"\nContent Preview:\n```\n{content_preview}\n```" if content_preview else ""
            return f"**File Written:** `{path}` ({bytes_written} bytes){preview_line}"
        
        elif detail_type == "file_read":
            path = details.get("path", "unknown file")
            content_preview = details.get("content_preview", "")
            preview_line = f"\nContent Preview:\n```\n{content_preview}\n```" if content_preview else ""
            return f"**File Read:** `{path}`{preview_line}"

        elif detail_type == "file_delete":
            path = details.get("path", "unknown file")
            return f"**File Deleted:** `{path}`"
        
        elif detail_type == "file_listing":
            path = details.get("path", ".")
            entries = details.get("entries", [])
            entries_list = "\n".join([f"- `{e}`" for e in entries[:10]]) # Limit to 10 for brevity
            if len(entries) > 10:
                entries_list += f"\n- ... ({len(entries) - 10} more)"
            return f"**Listed Directory:** `{path}`\nFiles/Dirs:\n{entries_list}"
        
        elif detail_type == "command_execution":
            command = details.get("command", "unknown command")
            stdout = details.get("stdout", "").strip()
            stderr = details.get("stderr", "").strip()
            output_lines = []
            if stdout:
                output_lines.append(f"**Stdout:**\n```bash\n{stdout}\n```")
            if stderr:
                output_lines.append(f"**Stderr:**\n```bash\n{stderr}\n```")
            return f"**Command Executed:** `{command}`\n" + "\n".join(output_lines)
        
        elif detail_type == "text_search":
            pattern = details.get("pattern", "")
            path = details.get("path", "")
            matches = details.get("matches", [])
            matches_list = "\n".join([f"- `{m}`" for m in matches[:10]])
            if len(matches) > 10:
                matches_list += f"\n- ... ({len(matches) - 10} more)"
            return f"**Searched for:** `{pattern}` in `{path}`\nMatches:\n{matches_list}"
        
        # Fallback for generic or unknown tool event types
        result_content = json.dumps(details.get("result", {}), indent=2, ensure_ascii=False)
        if result_content != "{}":
            return f"**Result:**\n```json\n{result_content}\n```"
        
        return "No specific details available."

    def _add_agent_progress_message(
            self, conversation_id: str, text: str) -> bool:
        """Add a progress message for agent workflow."""
        return self._add_assistant_message_and_save(
            f"[Agent] {text}",
            conversation_id,
            tool_events=[],
            planned_tasks=None,
        )

    def _set_task_status_and_save(
            self, conversation_id: str, task_index: int, status: str) -> bool:
        """Set one task status and persist."""
        conv = self.conversations.get(conversation_id)
        if not conv or not isinstance(conv.ai_tasks, list):
            return False
        normalized = self._normalize_task_list(conv.ai_tasks)
        if task_index < 0 or task_index >= len(normalized):
            return False
        final_status = str(status or "").strip().lower()
        if final_status not in ("uncompleted", "in_progress", "completed"):
            final_status = "uncompleted"
        normalized[task_index]["status"] = final_status
        normalized[task_index]["done"] = (final_status == "completed")
        conv.ai_tasks = normalized
        self.sidebar.set_ai_tasks(conversation_id, normalized)
        self._save_conversations()
        return False

    def _hide_typing_indicator_for_conversation(
            self, conversation_id: str) -> bool:
        """Hide typing indicator if this conversation is active."""
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.chat_area.hide_typing_indicator()
        return False

    def _set_agent_running(self, conversation_id: str, running: bool) -> None:
        """Mark/unmark agent run state for a conversation."""
        with self._agent_state_lock:
            if running:
                self._agent_running_conversations.add(conversation_id)
            else:
                self._agent_running_conversations.discard(conversation_id)

    def _is_agent_running(self, conversation_id: str) -> bool:
        """Check whether an agent run is currently active for conversation."""
        with self._agent_state_lock:
            return conversation_id in self._agent_running_conversations

    def _request_agent_stop(self, conversation_id: str, reason: str = "") -> None:
        """Request graceful stop for running agent in a conversation."""
        with self._agent_state_lock:
            self._agent_stop_requests.add(conversation_id)
        if reason:
            GLib.idle_add(
                self._add_agent_progress_message,
                conversation_id,
                reason,
                priority=GLib.PRIORITY_DEFAULT,
            )

    def _clear_agent_stop_request(self, conversation_id: str) -> None:
        """Clear stop request flag for a conversation."""
        with self._agent_state_lock:
            self._agent_stop_requests.discard(conversation_id)

    def _is_agent_stop_requested(self, conversation_id: str) -> bool:
        """Check whether a stop was requested for this conversation."""
        with self._agent_state_lock:
            return conversation_id in self._agent_stop_requests

    def _open_project_directory_after_agent_complete(
            self, conversation_id: str) -> bool:
        """Open project directory in file browser after agent completes all tasks."""
        conv = self.conversations.get(conversation_id)
        if not conv:
            return False

        agent_config = conv.agent_config
        if not agent_config or not isinstance(agent_config, dict):
            return False

        project_dir = agent_config.get("project_dir")
        if not project_dir or not os.path.isdir(project_dir):
            return False

        # Open the directory in the file browser
        import subprocess
        import sys

        try:
            if sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", project_dir])
            elif sys.platform == "win32":  # Windows
                subprocess.Popen(["explorer", project_dir])
            else:  # Linux and other Unix-like systems
                subprocess.Popen(["xdg-open", project_dir])

            # Add a message indicating the directory was opened
            self._add_agent_progress_message(
                conversation_id,
                f"Project directory opened: {project_dir}"
            )
        except Exception as e:
            logger.error(f"Failed to open directory {project_dir}: {e}")

        return False

    def _build_mode_system_prompt(
            self, mode: str, base_prompt: str, tasks: list[dict]) -> str:
        """Build an augmented system prompt according to selected mode."""
        base = (base_prompt or "You are a helpful AI assistant.").strip()
        if mode == "plan":
            return (
                f"{base}\n\n"
                "You are in planning mode.\n"
                "Do not write code.\n"
                "Do not call tools.\n"
                "Only output a clear step-by-step task plan.\n"
                "Each step must describe a concrete action (for example: create file X, "
                "implement function Y, test Z).\n"
                "Transform the user's request into an implementation plan with concrete steps.\n"
                "Return ONLY valid JSON (no markdown, no prose) with this exact schema:\n"
                "{\n"
                '  "steps": [\n'
                "    {\n"
                '      "step_number": 1,\n'
                '      "description": "Concrete action",\n'
                '      "goal": "Why this step matters",\n'
                '      "expected_output": "Artifact or result expected"\n'
                "    }\n"
                "  ]\n"
                "}\n"
                "Do not include extra keys. Keep each field concise and actionable."
            )
        if mode == "agent":
            task_lines = []
            for idx, task in enumerate(tasks or [], start=1):
                if not isinstance(task, dict):
                    continue
                txt = str(task.get("text", "")).strip()
                if not txt:
                    continue
                done = bool(task.get("done", False))
                task_lines.append(f"{idx}. [{'x' if done else ' '}] {txt}")
            task_context = "\n".join(
                task_lines) if task_lines else "(no saved tasks)"
            return (
                f"{base}\n\n"
                "You are in AGENT mode.\n"
                "Act as an implementation agent, not a planner.\n"
                "Execute tasks sequentially, one step at a time, and prefer concrete actions.\n"
                "Use available tools whenever they help you inspect files, edit code, run checks, or verify results.\n"
                "When you use a tool, interpret the result and continue toward task completion.\n"
                "Do not ask for unnecessary confirmation; proceed unless blocked by missing required information.\n"
                "IMPORTANT: You are sandboxed to the project directory. All file system operations MUST be relative to the project directory. Any attempt to access files or directories outside of the project directory will be denied.\n"
                "After each task, provide a concise progress update and what changed.\n"
                "Saved tasks:\n"
                f"{task_context}\n"
                "Reference the current task you are executing."
            )
        return base

    def _extract_tasks_from_plan_response(
            self, response_text: str) -> list[dict]:
        """Extract task lines from a planning response."""
        text = response_text or ""
        tasks: list[dict] = []

        # Preferred format: strict JSON with "steps".
        json_payload = self._parse_json_object_from_text(text)
        if isinstance(json_payload, dict):
            steps = json_payload.get("steps")
            if isinstance(steps, list):
                seen = set()
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    step_no = step.get("step_number")
                    desc = str(step.get("description", "")).strip()
                    goal = str(step.get("goal", "")).strip()
                    expected = str(step.get("expected_output", "")).strip()
                    if not desc:
                        continue
                    prefix = f"Step {step_no}: " if isinstance(
                        step_no, int) else "Step: "
                    parts = [f"{prefix}{desc}"]
                    if goal:
                        parts.append(f"Goal: {goal}")
                    if expected:
                        parts.append(f"Expected: {expected}")
                    task_text = " | ".join(parts).strip()
                    key = task_text.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    tasks.append(
                        {"text": task_text, "done": False, "status": "uncompleted"})
                if tasks:
                    return tasks[:24]

        block_match = re.search(
            r"<ai_tasks>(.*?)</ai_tasks>",
            text,
            flags=re.IGNORECASE | re.DOTALL)
        candidate = block_match.group(1) if block_match else text

        seen = set()
        for raw_line in candidate.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Markdown checkbox
            m = re.match(r"^[-*]\s*\[(?: |x|X)\]\s+(.+)$", line)
            if m:
                task_text = m.group(1).strip()
                key = task_text.lower()
                if task_text and key not in seen:
                    seen.add(key)
                    tasks.append(
                        {"text": task_text, "done": False, "status": "uncompleted"})
                continue
            # Numbered/bulleted fallback
            m2 = re.match(r"^(?:\d+[.)]|[-*])\s+(.+)$", line)
            if m2:
                task_text = m2.group(1).strip()
                key = task_text.lower()
                if task_text and key not in seen:
                    seen.add(key)
                    tasks.append(
                        {"text": task_text, "done": False, "status": "uncompleted"})

        return tasks[:24]

    def _parse_json_object_from_text(self, text: str) -> Optional[dict]:
        """Parse the first JSON object from text, including fenced blocks."""
        raw = (text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            raw,
            flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            try:
                parsed = json.loads(fenced.group(1))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                pass

        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(raw[start:end + 1])
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None

    async def _plan_mode_review_for_missing_info(
        self,
        conversation: Conversation,
        settings: ConversationSettings,
        plan_response: str,
        planned_tasks: list[dict],
    ) -> tuple[str, list[dict]]:
        """Ask a second background question in plan mode to detect missing user info."""
        try:
            ordered_tasks_text = self._render_ordered_tasks(planned_tasks)
            review_prompt = (
                "Review this newly created plan and determine if any additional information "
                "is required from the user before implementation can proceed.\n\n"
                f"Plan tasks (in order):\n{ordered_tasks_text}\n\n"
                "Return ONLY valid JSON with this schema:\n"
                "{"
                '"needs_info": boolean, '
                '"assistant_message": string, '
                '"updated_tasks": [{"text": string, "status": "uncompleted|in_progress|completed", "done": boolean}]'
                "}\n"
                "Rules:\n"
                "- If no additional user info is needed, set needs_info=false and assistant_message=\"\".\n"
                "- If user clarification is needed, set needs_info=true and assistant_message to a concise question.\n"
                "- updated_tasks must preserve execution order and include any edits."
            )

            # Build temporary conversation context including the generated
            # plan.
            temp_conv = Conversation(
                id=conversation.id,
                title=conversation.title,
                messages=list(conversation.messages),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                model=conversation.model,
                total_tokens=conversation.total_tokens,
                chat_settings=conversation.chat_settings,
                ai_tasks=list(
                    conversation.ai_tasks) if isinstance(
                    conversation.ai_tasks,
                    list) else [],
                chat_mode=conversation.chat_mode,
            )
            temp_conv.add_message(
                Message(
                    id=str(uuid.uuid4()),
                    role=MessageRole.ASSISTANT,
                    content=plan_response,
                )
            )
            temp_conv.add_message(
                Message(
                    id=str(uuid.uuid4()),
                    role=MessageRole.USER,
                    content=review_prompt,
                )
            )

            review_settings = replace(
                settings,
                token_saver=False,
                tools=None,
                tool_choice=None,
                integrations=None,
                system_prompt=(
                    "You are validating a project plan. "
                    "Respond with strict JSON only and no extra text."
                ),
            )
            raw = await self.api_client.chat_completion_with_tools(
                conversation=temp_conv,
                settings=review_settings,
                tool_executor=None,
            )
            needs_info, assistant_message, updated_tasks = self._parse_plan_review_response(
                raw_response=raw,
                fallback_tasks=planned_tasks,
            )
            if not needs_info:
                # No user-facing follow-up needed, but allow task refinements.
                return ("", updated_tasks)
            return (assistant_message, updated_tasks)
        except Exception as e:
            logger.warning("Plan-mode review pass failed: %s", e)
            return ("", planned_tasks)

    def _render_ordered_tasks(self, tasks: list[dict]) -> str:
        """Render task list in deterministic ordered format."""
        cleaned = self._normalize_task_list(tasks)
        if not cleaned:
            return "1. [ ] Define plan tasks"
        lines = []
        for i, task in enumerate(cleaned, start=1):
            status = str(task.get("status", "uncompleted"))
            mark = "x" if status == "completed" else (
                "~" if status == "in_progress" else " ")
            lines.append(f"{i}. [{mark}] {task.get('text', '')}")
        return "\n".join(lines)

    def _parse_plan_review_response(
        self,
        raw_response: str,
        fallback_tasks: list[dict],
    ) -> tuple[bool, str, list[dict]]:
        """Parse strict JSON review response; fallback safely on parse failures."""
        text = (raw_response or "").strip()
        payload = None

        # Prefer full JSON body.
        try:
            payload = json.loads(text)
        except Exception:
            payload = None

        # Fallback: extract first JSON object region.
        if not isinstance(payload, dict):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    payload = json.loads(text[start:end + 1])
                except Exception:
                    payload = None

        if not isinstance(payload, dict):
            # Heuristic fallback if model ignored JSON contract.
            needs_info = "?" in text and len(text) < 900
            return (
                needs_info,
                text if needs_info else "",
                self._normalize_task_list(fallback_tasks),
            )

        needs_info = bool(payload.get("needs_info", False))
        assistant_message = str(
            payload.get(
                "assistant_message",
                "") or "").strip()
        updated_tasks = self._normalize_task_list(payload.get("updated_tasks"))
        if not updated_tasks:
            updated_tasks = self._normalize_task_list(fallback_tasks)
        if not needs_info:
            assistant_message = ""
        return (needs_info, assistant_message, updated_tasks)

    def _normalize_task_list(self, tasks: object) -> list[dict]:
        """Normalize generic task payload to persisted task dicts."""
        cleaned = []
        seen = set()
        if not isinstance(tasks, list):
            return cleaned
        for task in tasks:
            if not isinstance(task, dict):
                continue
            text = str(task.get("text", "")).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            status = str(task.get("status", "")).strip().lower()
            if status not in ("uncompleted", "in_progress", "completed"):
                status = "completed" if bool(
                    task.get("done", False)) else "uncompleted"
            cleaned.append(
                {
                    "text": text,
                    "status": status,
                    "done": (status == "completed"),
                }
            )
        return cleaned[:24]

    def _ensure_agent_config(self, conversation: Conversation) -> bool:
        """Ensure per-conversation agent config exists; prompt user if missing."""
        cfg = conversation.agent_config if isinstance(
            conversation.agent_config, dict) else {}
        project_name = str(cfg.get("project_name", "")).strip()
        project_dir = str(cfg.get("project_dir", "")).strip()
        if project_name and project_dir and os.path.isdir(project_dir):
            return True

        dialog = Gtk.Dialog(
            title="Agent Setup",
            transient_for=self,
            flags=0,
        )
        dialog.set_modal(True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.set_default_size(560, 220)

        area = dialog.get_content_area()
        area.set_margin_start(12)
        area.set_margin_end(12)
        area.set_margin_top(12)
        area.set_margin_bottom(12)
        area.set_spacing(10)

        info = Gtk.Label()
        info.set_halign(Gtk.Align.START)
        info.set_xalign(0.0)
        info.set_line_wrap(True)
        info.set_markup(
            "<span size='9500'>Configure this conversation for Agent mode.</span>")
        area.pack_start(info, False, False, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(10)
        area.pack_start(grid, True, True, 0)

        name_label = Gtk.Label(label="Project Name")
        name_label.set_halign(Gtk.Align.START)
        name_entry = Gtk.Entry()
        name_entry.set_text(project_name or conversation.title or "My Project")
        grid.attach(name_label, 0, 0, 1, 1)
        grid.attach(name_entry, 1, 0, 1, 1)

        dir_label = Gtk.Label(label="Project Directory")
        dir_label.set_halign(Gtk.Align.START)
        dir_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        dir_entry = Gtk.Entry()
        dir_entry.set_hexpand(True)
        dir_entry.set_text(project_dir or self.workspace_root)
        browse_btn = Gtk.Button(label="Browse…")

        def _on_browse_clicked(_btn):
            chooser = Gtk.FileChooserDialog(
                title="Select Project Directory",
                transient_for=self,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
            chooser.add_button("Select", Gtk.ResponseType.OK)
            chooser.set_modal(True)
            chooser.set_create_folders(True)
            current = dir_entry.get_text().strip()
            if current and os.path.isdir(current):
                try:
                    chooser.set_current_folder(current)
                except Exception:
                    pass
            response = chooser.run()
            if response == Gtk.ResponseType.OK:
                selected = chooser.get_filename()
                if selected:
                    dir_entry.set_text(selected)
            chooser.destroy()

        browse_btn.connect("clicked", _on_browse_clicked)
        dir_row.pack_start(dir_entry, True, True, 0)
        dir_row.pack_end(browse_btn, False, False, 0)
        grid.attach(dir_label, 0, 1, 1, 1)
        grid.attach(dir_row, 1, 1, 1, 1)

        dialog.show_all()
        resp = dialog.run()
        if resp != Gtk.ResponseType.OK:
            dialog.destroy()
            return False

        selected_name = name_entry.get_text().strip()
        selected_dir = os.path.abspath(dir_entry.get_text().strip())
        dialog.destroy()

        if not selected_name:
            self._show_error_dialog("Agent Setup", "Project name is required.")
            return False
        if not selected_dir:
            self._show_error_dialog(
                "Agent Setup", "Project directory is required.")
            return False
        if not os.path.isdir(selected_dir):
            try:
                os.makedirs(selected_dir, exist_ok=True)
            except Exception as e:
                self._show_error_dialog(
                    "Agent Setup",
                    f"Could not create project directory:\n{e}",
                )
                return False

        conversation.agent_config = {
            "project_name": selected_name,
            "project_dir": selected_dir,
        }
        self._save_conversations()
        refresh_project_map(selected_dir)

        # Update the Open Dir button visibility in the chat area
        if self.current_conversation and self.current_conversation.id == conversation.id:
            self.chat_area._update_open_dir_button()

        return True

    async def _run_compile_check(self, project_dir: str) -> tuple[bool, str]:
        """Run a Python compile check for the configured project directory."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                "-m",
                "compileall",
                "-q",
                project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            detail = (out + ("\n" if out and err else "") + err).strip()
            if not detail:
                detail = "No compiler output."
            return (proc.returncode == 0, detail[:3000])
        except Exception as e:
            return (False, f"Compile check failed to run: {e}")

    def _add_plan_followup_and_save(
        self,
        followup_text: str,
        conversation_id: str,
        updated_tasks: Optional[list[dict]] = None,
    ) -> bool:
        """Persist optional plan refinements and add follow-up clarification message."""
        if conversation_id not in self.conversations:
            return False
        conv = self.conversations[conversation_id]

        cleaned_tasks = self._normalize_task_list(updated_tasks)
        if cleaned_tasks:
            conv.ai_tasks = cleaned_tasks
            self.sidebar.set_ai_tasks(conversation_id, cleaned_tasks)

        if followup_text:
            ai_msg = Message(
                id=str(uuid.uuid4()),
                role=MessageRole.ASSISTANT,
                content=followup_text,
                tokens=count_text_tokens(followup_text, model=conv.model),
                meta={"tool_events": []},
            )
            conv.add_message(ai_msg)
            if self.current_conversation and self.current_conversation.id == conversation_id:
                self.current_conversation = conv
                self.chat_area.add_message(ai_msg)

        self._save_conversations()
        return False

    async def _phase1_intent_validation(
        self,
        conversation: Conversation,
        conversation_id: str,
        settings: ConversationSettings,
        user_text: str,
        task_text: str,
        global_context: str,
        iteration_num: int,
    ) -> dict:
        """Phase 1: Intent Validation - Agent answers critical questions before coding."""
        validation_prompt = (
            "You are an expert software engineer performing intent validation for a task. "
            "Critically analyze the task before proceeding to design or implementation. "
            "Your goal is to prevent errors, ensure alignment, and identify better approaches.\n\n"
            f"{global_context}"
            f"Current User Request: {user_text}\n"
            f"Task to Validate: {task_text}\n\n"
            "Answer the following questions in a JSON object:\n"
            "{\n"
            '  "aligns_goal": boolean, // Does this align with the main project goal (from constitution)?\n'
            '  "conflicts_prior_decisions": boolean, // Does it conflict with prior decisions (from decision log)?\n'
            '  "simpler_approach_possible": boolean, // Is there a simpler approach?\n'
            '  "simpler_approach_description": string, // If yes, describe it.\n'
            '  "potential_risks": string, // What could go wrong? Describe potential issues.\n'
            '  "proceed_with_task": boolean, // Based on validation, should we proceed with this task as is?\n'
            '  "reason_for_decision": string // Explain why you recommend proceeding or not.\n'
            "}\n"
            "Return ONLY the JSON object. Do not include any other text or markdown."
        )

        temp_conv = Conversation(
            id=conversation.id,
            title=conversation.title,
            messages=list(conversation.messages),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            model=conversation.model,
            total_tokens=conversation.total_tokens,
            chat_settings=conversation.chat_settings,
            ai_tasks=list(conversation.ai_tasks),
            chat_mode=conversation.chat_mode,
            agent_config=conversation.agent_config,
            active_context_files=conversation.active_context_files,
        )
        temp_conv.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=validation_prompt,
        ))

        validation_settings = replace(
            settings,
            token_saver=False,
            tools=None, # No tools during validation
            tool_choice=None,
            integrations=None,
            system_prompt=(
                "You are an expert intent validator. "
                "Respond with strict JSON only and no extra text."
            ),
        )
        try:
            raw_response = await self.api_client.chat_completion_with_tools(
                conversation=temp_conv,
                settings=validation_settings,
                tool_executor=None,
            )
            validation_result = json.loads(raw_response)
            if not isinstance(validation_result, dict):
                raise ValueError("AI returned invalid JSON for intent validation.")
            return {"ok": True, "result": validation_result}
        except Exception as e:
            logger.error("Error during intent validation: %s", e)
            return {"ok": False, "error": f"Intent validation failed: {e}"}

    async def _phase2_design_draft(
        self,
        conversation: Conversation,
        conversation_id: str,
        settings: ConversationSettings,
        user_text: str,
        task_text: str,
        global_context: str,
        iteration_num: int,
        validation_feedback: dict,
    ) -> dict:
        """Phase 2: Design Draft - Agent creates a design before writing code."""
        design_prompt = (
            "You are an expert software architect tasked with drafting a design for an upcoming task. "
            "Focus on the high-level approach, architectural impact, and file changes. "
            "DO NOT write any code in this phase. The goal is to plan thoroughly.\n\n"
            f"{global_context}"
            f"Current User Request: {user_text}\n"
            f"Task to Design: {task_text}\n"
            f"Intent Validation Feedback: {json.dumps(validation_feedback, indent=2)}\n\n"
            "Provide your design draft in a structured Markdown format, including:\n"
            "1.  **Architecture Sketch (High-level explanation):** How does this fit into the existing architecture?\n"
            "2.  **Dependency Impact:** What existing dependencies are affected, and what new ones are introduced?\n"
            "3.  **Files to Change/Create:** List specific files and briefly describe their role in the change.\n"
            "4.  **New Abstractions:** What new classes, functions, or patterns will be introduced?\n"
            "5.  **Plan of Action:** A step-by-step plan for implementation (this will be used by Phase 3).\n"
            "Do NOT include code blocks in this design draft. Focus on descriptions and structure."
        )

        temp_conv = Conversation(
            id=conversation.id,
            title=conversation.title,
            messages=list(conversation.messages),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            model=conversation.model,
            total_tokens=conversation.total_tokens,
            chat_settings=conversation.chat_settings,
            ai_tasks=list(conversation.ai_tasks),
            chat_mode=conversation.chat_mode,
            agent_config=conversation.agent_config,
            active_context_files=conversation.active_context_files,
        )
        temp_conv.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=design_prompt,
        ))

        design_settings = replace(
            settings,
            token_saver=False,
            tools=None, # No tools during design draft
            tool_choice=None,
            integrations=None,
            system_prompt=(
                "You are an expert software architect and designer. "
                "Provide a detailed design draft in structured Markdown. "
                "Do NOT write code or use tools in this phase."
            ),
        )
        try:
            raw_response = await self.api_client.chat_completion_with_tools(
                conversation=temp_conv,
                settings=design_settings,
                tool_executor=None,
            )
            return {"ok": True, "result": raw_response}
        except Exception as e:
            logger.error("Error during design draft generation: %s", e)
            return {"ok": False, "error": f"Design draft generation failed: {e}"}

    async def _phase4_post_implementation_critique(
        self,
        conversation: Conversation,
        conversation_id: str,
        settings: ConversationSettings,
        user_text: str,
        task_text: str,
        global_context: str,
        implementation_summary: str,
        iteration_num: int,
        compile_status: dict,
    ) -> dict:
        """Phase 4: Post-Implementation Critique - Agent critiques its work."""
        critique_prompt = (
            "You are a senior software engineer performing a critical review of a recent implementation. "
            "Your goal is to identify potential flaws, ensure code quality, and maintain architectural integrity. "
            "Be honest and thorough in your assessment.\n\n"
            f"{global_context}"
            f"Original User Request: {user_text}\n"
            f"Task Implemented: {task_text}\n"
            f"Implementation Summary (AI's own summary): {implementation_summary}\n"
            f"Compile Check Status: {json.dumps(compile_status, indent=2)}\n\n"
            "Answer the following questions in a JSON object:\n"
            "{\n"
            '  "introduced_coupling": boolean, // Did this introduce undesirable coupling?\n'
            '  "coupling_details": string, // If yes, describe where and why it\'s undesirable.\n'
            '  "complexity_increased": boolean, // Did complexity increase unnecessarily?\n'
            '  "complexity_details": string, // If yes, describe how and why it\'s unnecessary.\n'
            '  "violates_constitution": boolean, // Does this violate any principles from the project constitution?\n'
            '  "violation_details": string, // If yes, describe which principle and how it\'s violated.\n'
            '  "is_scalable": boolean, // Is this solution scalable?\n'
            '  "scalability_details": string, // If no, explain why not.\n'
            '  "senior_engineer_approval": boolean, // Would a senior engineer approve this design/implementation?\n'
            '  "approval_reason": string, // Explain why or why not.\n'
            '  "flaws_found": boolean, // Overall, were significant flaws found?\n'
            '  "new_tasks_needed": Array<string>, // If flaws found, list new tasks to address them. Each string is a task description.\n'
            '  "critique_summary": string // A concise summary of your critique.\n'
            "}\n"
            "Return ONLY the JSON object. Do not include any other text or markdown."
        )

        temp_conv = Conversation(
            id=conversation.id,
            title=conversation.title,
            messages=list(conversation.messages),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            model=conversation.model,
            total_tokens=conversation.total_tokens,
            chat_settings=conversation.chat_settings,
            ai_tasks=list(conversation.ai_tasks),
            chat_mode=conversation.chat_mode,
            agent_config=conversation.agent_config,
            active_context_files=conversation.active_context_files,
        )
        temp_conv.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=critique_prompt,
        ))

        critique_settings = replace(
            settings,
            token_saver=False,
            tools=None, # No tools during critique
            tool_choice=None,
            integrations=None,
            system_prompt=(
                "You are an expert and critical software reviewer. "
                "Respond with strict JSON only and no extra text."
            ),
        )
        try:
            raw_response = await self.api_client.chat_completion_with_tools(
                conversation=temp_conv,
                settings=critique_settings,
                tool_executor=None,
            )
            critique_result = json.loads(raw_response)
            if not isinstance(critique_result, dict):
                raise ValueError("AI returned invalid JSON for post-implementation critique.")
            return {"ok": True, "result": critique_result}
        except Exception as e:
            logger.error("Error during post-implementation critique: %s", e)
            return {"ok": False, "error": f"Post-implementation critique failed: {e}"}

    def _on_edit_message(self, message_id: str) -> None:
        """Handle request to edit a message."""
        if not self.current_conversation:
            return
        for message in self.current_conversation.messages:
            if message.id == message_id:
                self.chat_input.set_text(message.content)
                self.chat_input.focus()
                # Optionally, delete the original message or mark as edited
                break

    def _on_repush_message(self, message_id: str) -> None:
        """Handle request to re-push (re-send) a message). Clears subsequent messages."""
        if not self.current_conversation:
            return
        
        message_to_repush = None
        repush_index = -1
        for i, message in enumerate(self.current_conversation.messages):
            if message.id == message_id:
                message_to_repush = message
                repush_index = i
                break
        
        if message_to_repush and repush_index != -1:
            # Clear all messages from this one onwards (inclusive) for a true "reiterate from"
            # The prompt says "clear all messages after the selected one", so keep selected.
            self.current_conversation.messages = self.current_conversation.messages[:repush_index + 1]
            self._save_conversations()
            
            # Refresh chat area to reflect cleared messages
            self.chat_area.set_conversation(
                self.current_conversation,
                self._get_effective_settings(self.current_conversation).context_limit
            )
            
            # Now simulate sending the message content
            self.chat_input.set_text(message_to_repush.content)
            self._on_send_message(None) # Simulate send button click

    def _on_delete_message(self, message_id: str) -> None:
        """Handle request to delete a message."""
        if not self.current_conversation:
            return
        
        # Confirmation dialog before deleting
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Delete message?",
        )
        dialog.format_secondary_text("This message will be permanently deleted from the conversation history.")
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            original_message_count = len(self.current_conversation.messages)
            self.current_conversation.messages = [
                msg for msg in self.current_conversation.messages if msg.id != message_id
            ]
            if len(self.current_conversation.messages) < original_message_count:
                # Message was deleted, refresh UI
                self._save_conversations()
                self.chat_area.set_conversation(self.current_conversation, self._get_effective_settings(self.current_conversation).context_limit)

    def _select_tools_for_enabled_integrations(
        self, tools: list[dict], enabled_integrations: list[str]
    ) -> list[dict]:
        """Select tools that match enabled integrations only."""
        if not isinstance(tools, list):
            return []
        if not enabled_integrations:
            return []

        selected = []
        enabled_set = set(enabled_integrations)
        normalized_enabled = {
            self._sanitize_identifier(iid.replace("/", "_")).lower(): iid
            for iid in enabled_integrations
        }
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            integration_hint = (
                tool.get("integration_id")
                or tool.get("integration")
                or tool.get("mcp_server")
                or tool.get("server")
                or tool.get("x-integration-id")
            )
            if integration_hint and str(integration_hint) in enabled_set:
                selected.append(tool)
                continue

            # Heuristic fallback for configs that don't carry integration_id:
            # match function name prefixes against enabled integration ids.
            fn = tool.get("function") if tool.get(
                "type") == "function" else tool
            fn_name = ""
            if isinstance(fn, dict):
                fn_name = str(fn.get("name", "")).lower()
            for normalized_key in normalized_enabled.keys():
                if fn_name.startswith(normalized_key + "_"):
                    selected.append(tool)
                    break

        return selected

    def _build_tools_from_enabled_mcp(
            self, enabled_tools: list[dict]) -> list[dict]:
        """Build minimal function tool definitions from enabled MCP metadata."""
        tool_defs = []
        for tool in enabled_tools:
            integration_id = tool.get("id") or "mcp/tool"
            integration_name = self._sanitize_identifier(
                integration_id.replace("/", "_"))
            calls = tool.get("calls") or []
            if not calls:
                calls = ["run"]
            for call in calls:
                call_name = self._sanitize_identifier(str(call))
                fn_name = self._sanitize_identifier(
                    f"{integration_name}_{call_name}")
                tool_defs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "description": f"MCP call '{call}' for integration '{integration_id}'.",
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": True,
                            },
                        },
                    }
                )
        return tool_defs

    def _dedupe_tool_definitions(self, tools: list[dict]) -> list[dict]:
        """Dedupe tool definitions by function name while preserving order."""
        deduped = []
        seen = set()
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function") if tool.get(
                "type") == "function" else tool
            if not isinstance(fn, dict):
                continue
            name = str(fn.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(tool)
        return deduped

    def _sanitize_identifier(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", value)
        return cleaned[:64] if cleaned else "tool"

    async def _execute_tool_call(
        self,
        tool_name: str,
        args: dict,
        mcp_tool_map: Optional[dict[str, dict]] = None,
        server_configs: Optional[dict[str, dict]] = None,
    ) -> tuple[str, dict]: # Modified return type
        """Safely execute supported tool calls and return serialized result text and tool event."""
        tool_event = {
            "name": tool_name,
            "args": args,
            "status": "error", # Default to error
            "result": {},
            "details": {"type": "tool_error", "message": "Unknown error"}
        }

        try:
            handlers = {
                "list_files": self._tool_list_files,
                "read_file": self._tool_read_file,
                "search_text": self._tool_search_text,
                "run_command": self._tool_run_command,
                "builtin_read_file": self._tool_builtin_read_file,
                "summarize_file_for_index": self._tool_summarize_file_for_index,
                "load_files_into_context": self._tool_load_files_into_context,
                "add_decision_log_entry": self._tool_add_decision_log_entry,
                "perform_milestone_review": self._tool_perform_milestone_review,
                "builtin_write_file": self._tool_builtin_write_file,
                "builtin_edit_file": self._tool_builtin_edit_file,
                "builtin_delete_file": self._tool_builtin_delete_file,
            }
            handler = handlers.get(tool_name)
            if handler is not None:
                result = await handler(args or {})
                tool_event["result"] = result
                tool_event["status"] = "success" if result.get("ok") else "error"
                tool_event["details"] = result.get("details", tool_event["details"])
                return json.dumps(result, ensure_ascii=False), tool_event

            # If this tool belongs to an MCP endpoint, call tools/call on that endpoint.
            if mcp_tool_map and tool_name in mcp_tool_map and isinstance(server_configs, dict):
                meta = mcp_tool_map[tool_name]
                integration_id = str(meta.get("integration_id", "")).strip()
                raw_tool_name = str(meta.get("mcp_tool_name", "")).strip() or tool_name
                server = server_configs.get(integration_id, {})
                cfg = server.get("config") if isinstance(server, dict) else None
                if isinstance(cfg, dict):
                    result = await self.mcp_discovery.call_tool(
                        integration_id=integration_id,
                        tool_name=raw_tool_name,
                        arguments=args or {},
                        cfg=cfg,
                    )
                    tool_event["result"] = result
                    tool_event["status"] = "success" if result.get("ok") else "error"
                    tool_event["details"] = result.get("details", tool_event["details"])
                    return json.dumps(result, ensure_ascii=False), tool_event
            
            # If no handler found or MCP call fails
            error_msg = f"Unsupported tool: {tool_name}"
            tool_event["result"] = {"ok": False, "error": error_msg}
            tool_event["details"] = {"type": "tool_error", "message": error_msg}
            return json.dumps(tool_event["result"], ensure_ascii=False), tool_event

        except Exception as e:
            error_msg = f"Tool execution failed: {e}"
            tool_event["result"] = {"ok": False, "error": error_msg}
            tool_event["details"] = {"type": "tool_error", "message": error_msg, "exception": str(e)}
            return json.dumps(tool_event["result"], ensure_ascii=False), tool_event

    async def _update_project_index_tool(
        self,
        file_path: str,
        purpose: str,
        public_api: Optional[str] = None,
        dependencies: Optional[list[str]] = None,
        key_responsibilities: Optional[list[str]] = None,
        known_issues: Optional[list[str]] = None,
    ) -> str:
        """
        Tool: Updates a summary entry in the dynamic project index (PROJECT_INDEX.json)
        for a specific file. This index helps the AI understand the project structure
        and file responsibilities without reading raw content.

        Args:
            file_path: The workspace-relative path to the file being summarized.
            purpose: A brief description of the file's purpose.
            public_api: (Optional) Description of the main functions/classes exposed by the file.
            dependencies: (Optional) List of other files or modules this file significantly depends on.
            key_responsibilities: (Optional) List of key tasks or features this file is responsible for.
            known_issues: (Optional) List of any known bugs, limitations, or areas for improvement.
        
        Returns:
            A JSON string indicating success or failure.
        """
        project_index_data = self._load_project_index()
        
        # Ensure file_path is relative to workspace_root
        abs_file_path = os.path.join(self.workspace_root, file_path)
        relative_file_path = os.path.relpath(abs_file_path, self.workspace_root)

        project_index_data[relative_file_path] = {
            "purpose": purpose,
            "public_api": public_api,
            "dependencies": dependencies or [],
            "key_responsibilities": key_responsibilities or [],
            "known_issues": known_issues or [],
        }
        handler = handlers.get(tool_name)
        if handler is not None:
            result = await handler(args or {})
            return json.dumps(result, ensure_ascii=False)

        # If this tool belongs to an MCP endpoint, call tools/call on that
        # endpoint.
        if mcp_tool_map and tool_name in mcp_tool_map and isinstance(
                server_configs, dict):
            meta = mcp_tool_map[tool_name]
            integration_id = str(meta.get("integration_id", "")).strip()
            raw_tool_name = str(
                meta.get(
                    "mcp_tool_name",
                    "")).strip() or tool_name
            server = server_configs.get(integration_id, {})
            cfg = server.get("config") if isinstance(server, dict) else None
            if isinstance(cfg, dict):
                result = await self.mcp_discovery.call_tool(
                    integration_id=integration_id,
                    tool_name=raw_tool_name,
                    arguments=args or {},
                    cfg=cfg,
                )
                return json.dumps(result, ensure_ascii=False)

    async def _update_project_constitution_tool(self, new_content: str) -> str:
        """
        Tool: Updates the project constitution file (PROJECT_CONSTITUTION.md).
        This file serves as a foundational memory layer for the agent mode,
        defining the project's core purpose, technologies, principles, etc.
        Only use this tool when explicitly instructed to modify the project's
        constitution as part of an "architecture change" task.

        Args:
            new_content: The full new content to write to PROJECT_CONSTITUTION.md.
        
        Returns:
            A JSON string indicating success or failure.
        """
        constitution_path = os.path.join(self.workspace_root, "PROJECT_CONSTITUTION.md")
        try:
            # Using the imported write_file utility
            await write_file(constitution_path, new_content.encode('utf-8'))
            logger.info("Successfully updated PROJECT_CONSTITUTION.md")
            return json.dumps({"status": "success", "message": "PROJECT_CONSTITUTION.md updated successfully."})
        except Exception as e:
            logger.error("Error updating PROJECT_CONSTITUTION.md: %s", e)
            return json.dumps({"status": "error", "message": f"Failed to update PROJECT_CONSTITUTION.md: {e}"})

    def _builtin_filesystem_tools(self) -> list[dict]:
        """Tool definitions for built-in local filesystem integration."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "update_project_constitution",
                    "description": (
                        "Updates the project constitution file (PROJECT_CONSTITUTION.md) with the provided content. "
                        "This file serves as a foundational memory layer for the agent mode. Use this tool only for explicit architecture change tasks."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_content": {
                                "type": "string",
                                "description": "The full new content to write to PROJECT_CONSTITUTION.md."
                            },
                        },
                        "required": ["new_content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_project_index",
                    "description": (
                        "Updates a summary entry in the dynamic project index (PROJECT_INDEX.json) for a specific file. "
                        "This index helps the AI understand the project structure and file responsibilities. "
                        "Use this tool to summarize a file's purpose, public API, dependencies, key responsibilities, and known issues."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Workspace-relative path to the file being summarized."},
                            "purpose": {"type": "string", "description": "A brief description of the file's purpose."},
                            "public_api": {"type": "string", "description": "(Optional) Description of the main functions/classes exposed by the file."},
                            "dependencies": {"type": "array", "items": {"type": "string"}, "description": "(Optional) List of other files or modules the file significantly depends on."},
                            "key_responsibilities": {"type": "array", "items": {"type": "string"}, "description": "(Optional) List of key tasks or features this file is responsible for."},
                            "known_issues": {"type": "array", "items": {"type": "string"}, "description": "(Optional) List of any known bugs, limitations, or areas for improvement."},
                        },
                        "required": ["file_path", "purpose"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summarize_file_for_index",
                    "description": (
                        "Reads a file and sends its content to the AI for summarization based on project index criteria "
                        "(purpose, public API, dependencies, key responsibilities, known issues). "
                        "The AI's summary is then used to update PROJECT_INDEX.json. "
                        "This tool allows the AI to dynamically update its understanding of project files."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "The workspace-relative path to the file to summarize."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "load_files_into_context",
                    "description": (
                        "Loads specified files into the AI's active working context for deep retrieval. "
                        "The content of these files will be automatically appended to the agent's instructions for subsequent tasks. "
                        "If an empty list is provided, the active context will be cleared."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "paths": {"type": "array", "items": {"type": "string"}, "description": "A list of workspace-relative file paths to load. If empty, clears the active context."},
                        },
                        "required": ["paths"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_decision_log_entry",
                    "description": (
                        "Adds a new entry to the architectural decision log (DECISION_LOG.md). "
                        "This provides long-term memory of architectural choices, their justifications, and impacts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "decision_summary": {"type": "string", "description": "A concise summary of the decision made."},
                            "reasoning": {"type": "string", "description": "The justification or rationale behind the decision."},
                            "impact": {"type": "string", "description": "The expected or observed consequences/impact of the decision."},
                            "related_files": {"type": "array", "items": {"type": "string"}, "description": "(Optional) A list of files or components affected by this decision."},
                            "status": {"type": "string", "description": "(Optional) The current status of the decision (e.g., implemented, pending, reconsidered). Defaults to 'implemented'."},
                        },
                        "required": ["decision_summary", "reasoning", "impact"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "perform_milestone_review",
                    "description": (
                        "Triggers a milestone-level review of the project's memory layers (Constitution, Dynamic Project Index, Decision Log) by the AI. "
                        "The AI will assess their consistency and up-to-dateness and suggest new tasks if updates are needed."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "review_focus": {"type": "string", "description": "(Optional) A specific area to focus the AI's review on. Defaults to 'general consistency and up-to-dateness'."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_read_file",
                    "description": "Read a UTF-8 text file inside the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative file path."},
                            "max_chars": {"type": "integer", "description": "Optional max chars to read."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_write_file",
                    "description": "Write/overwrite a UTF-8 text file inside the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative file path."},
                            "content": {"type": "string", "description": "Full file content to write."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_edit_file",
                    "description": "Replace one text segment with another in a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative file path."},
                            "find": {"type": "string", "description": "Exact text to find."},
                            "replace": {"type": "string", "description": "Replacement text."},
                            "replace_all": {"type": "boolean", "description": "Replace all occurrences."},
                        },
                        "required": ["path", "find", "replace"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "builtin_delete_file",
                    "description": "Delete a file in the workspace (requires double user confirmation).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Workspace-relative file path."},
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    def _build_mcp_tool_map(self, tools: list[dict]) -> dict[str, dict]:
        """Build lookup map from function tool name to MCP metadata."""
        out = {}
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            fn = tool.get("function")
            if not isinstance(fn, dict):
                continue
            fn_name = str(fn.get("name", "")).strip()
            if not fn_name:
                continue
            integration_id = tool.get(
                "integration_id") or tool.get("x-integration-id")
            raw_name = tool.get("x-mcp-tool-name")
            if integration_id:
                out[fn_name] = {
                    "integration_id": str(integration_id),
                    "mcp_tool_name": str(raw_name) if raw_name is not None else fn_name,
                }
        return out

    async def _tool_list_files(self, args: dict) -> dict:
        rel_path = str(args.get("path", "."))
        max_results = int(args.get("max_results", 200))
        max_results = max(1, min(max_results, 2000))
        target = self._safe_path(rel_path)
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "Invalid directory path. Must be within the workspace."}
        names = sorted(os.listdir(target))[:max_results]
        return {
            "ok": True,
            "path": rel_path,
            "entries": names,
            "count": len(names),
            "details": {
                "type": "file_listing",
                "path": rel_path,
                "entries": names,
            }
        }

    async def _tool_read_file(self, args: dict) -> dict:
        rel_path = str(args.get("path", "")).strip()
        max_chars = int(args.get("max_chars", 12000))
        max_chars = max(256, min(max_chars, 50000))
        target = self._safe_path(rel_path)
        if not rel_path or not target or not os.path.isfile(target):
            return {"ok": False, "error": "Invalid file path. Must be within the workspace."}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars + 1)
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
            return {
                "ok": True,
                "path": rel_path,
                "content": content,
                "truncated": truncated,
                "max_chars": max_chars,
                "details": {
                    "type": "file_read",
                    "path": rel_path,
                    "content_preview": content[:200] # first 200 chars for preview
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to read file: {e}"}

    async def _tool_search_text(self, args: dict) -> dict:
        pattern = str(args.get("pattern", "")).strip()
        rel_path = str(args.get("path", "."))
        max_results = int(args.get("max_results", 100))
        max_results = max(1, min(max_results, 500))
        target = self._safe_path(rel_path)
        if not pattern:
            return {"ok": False, "error": "Missing 'pattern'"}
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "Invalid search path. Must be within the workspace."}

        cmd = ["rg", "-n", "--max-count", str(max_results), pattern, target]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            text = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            lines = text.splitlines() if text else []
            return {
                "ok": proc.returncode in (0, 1),
                "matches": lines[:max_results],
                "count": len(lines[:max_results]),
                "stderr": err,
                "details": {
                    "type": "text_search",
                    "pattern": pattern,
                    "path": rel_path,
                    "matches": lines[:max_results],
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Search failed: {e}"}

    async def _tool_run_command(self, args: dict) -> dict:
        """Run allowlisted commands without shell expansion."""
        allowed = {"ls", "pwd", "cat", "echo", "rg"}
        raw = args.get("command")
        if isinstance(raw, list):
            cmd = [str(x) for x in raw if str(x).strip()]
        else:
            cmd = shlex.split(str(raw or ""))
        if not cmd:
            return {"ok": False, "error": "Missing command"}
        if cmd[0] not in allowed:
            return {"ok": False, "error": f"Command not allowed: {cmd[0]}", "allowed": sorted(
                list(allowed))}

        timeout_s = float(args.get("timeout_sec", 10))
        timeout_s = max(1.0, min(timeout_s, 20.0))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.workspace_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "details": {
                    "type": "command_execution",
                    "command": " ".join(cmd),
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "returncode": proc.returncode,
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Command failed: {e}"}

    async def _tool_builtin_read_file(self, args: dict) -> dict:
        """Built-in filesystem read file tool."""
        return await self._tool_read_file(args)

    async def _tool_summarize_file_for_index(self, args: dict) -> dict:
        """
        Handles the 'summarize_file_for_index' tool call. Reads a file's content,
        sends it to the LM Studio AI for summarization based on project index
        criteria, and then updates the PROJECT_INDEX.json.
        """
        file_path = args.get("path")
        if not file_path:
            return {"ok": False, "error": "Missing 'path' argument for summarize_file_for_index."}

        # 1. Read the file content
        read_result = await self._tool_builtin_read_file({"path": file_path})
        if not read_result.get("ok"):
            return {"ok": False, "error": f"Failed to read file for summarization: {read_result.get('error')}"}
        
        content = read_result.get("content", "")
        if not content:
            return {"ok": False, "error": f"File {file_path} is empty, cannot summarize."}

        # 2. Prepare a temporary conversation for AI summarization
        temp_conv = Conversation(
            id=str(uuid.uuid4()), # Use a new UUID for temp conv
            title=f"Summarize {file_path}",
            model=self.current_conversation.model if self.current_conversation else "default",
        )
        temp_conv.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=f"Summarize the following file content for a project index. Provide a JSON object with 'purpose', 'public_api', 'dependencies' (list of strings), 'key_responsibilities' (list of strings), and 'known_issues' (list of strings). If a field is not applicable or cannot be determined, omit it or set it to null.\n\nFile: {file_path}\nContent:\n```\n{content}\n```\n\nReturn ONLY a JSON object. Do not include any other text or markdown."
        ))

        settings = self._get_effective_settings(temp_conv)
        # Ensure token saver is off and context limit is sufficient for summarization
        settings.token_saver = False
        settings.max_tokens = min(settings.max_tokens, 2048) # Cap summary response
        settings.system_prompt = (
            "You are an expert software engineer assistant tasked with summarizing code files "
            "for a project index. Your output MUST be a JSON object with the keys: 'purpose', "
            "'public_api', 'dependencies' (list of strings), 'key_responsibilities' (list of strings), "
            "'known_issues' (list of strings). Omit fields that are not applicable or cannot be determined. "
            "Do NOT include any other text, markdown, or commentary."
        )

        try:
            # Call LM Studio API for summarization
            # We use a fresh session as this might be called from a background thread
            summarized_json_str = await self.api_client.chat_completion_with_tools(
                conversation=temp_conv,
                settings=settings,
                tool_executor=None, # No tools for the summarization call itself
            )
            
            # 3. Parse the AI's JSON response
            summarized_data = json.loads(summarized_json_str)
            if not isinstance(summarized_data, dict):
                raise ValueError("AI response was not a valid JSON object.")

            # 4. Update the project index using the dedicated tool
            update_result_json = await self._update_project_index_tool(
                file_path=file_path,
                purpose=summarized_data.get("purpose", ""),
                public_api=summarized_data.get("public_api"),
                dependencies=summarized_data.get("dependencies"),
                key_responsibilities=summarized_data.get("key_responsibilities"),
                known_issues=summarized_data.get("known_issues"),
            )
            update_result = json.loads(update_result_json) # Deserialize the result from the tool call
            if not update_result.get("ok"):
                return {"ok": False, "error": f"Failed to update project index after summarization: {update_result.get('error')}"}

            return {"ok": True, "message": f"Successfully summarized and updated index for {file_path}."}

        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"AI returned invalid JSON for summarization: {e}. Raw: {summarized_json_str}"}
        except Exception as e:
            logger.error("Error during file summarization: %s", e)
            return {"ok": False, "error": f"An error occurred during summarization: {e}"}

    async def _tool_load_files_into_context(self, args: dict) -> dict:
        """
        Tool: Loads specified files into the AI's active working context for deep retrieval.
        The content of these files will be automatically appended to the agent's instructions
        for subsequent tasks, allowing the AI to work with focused, relevant context.

        Args:
            args: A dictionary expected to contain a 'paths' key, which is a list of
                  workspace-relative file paths to load. If 'paths' is empty,
                  it will clear the active context.
        
        Returns:
            A JSON string indicating success or failure, and listing loaded/cleared files.
        """
        paths_to_load = args.get("paths", [])
        if not isinstance(paths_to_load, list):
            return {"ok": False, "error": "Argument 'paths' must be a list of file paths."}

        if not self.current_conversation:
            return {"ok": False, "error": "No active conversation to load files into context."}

        loaded_files = {}
        errors = []

        if not paths_to_load:
            # Clear active context if no paths are provided
            self.current_conversation.active_context_files = {}
            self._save_conversations() # Persist the change
            logger.info("Active context files cleared for conversation %s", self.current_conversation.id)
            return {"ok": True, "message": "Active context files cleared."}

        for rel_path in paths_to_load:
            # Use _tool_builtin_read_file to get content safely
            read_result = await self._tool_builtin_read_file({"path": rel_path})
            if read_result.get("ok"):
                loaded_files[rel_path] = read_result.get("content", "")
            else:
                errors.append(f"Failed to load '{rel_path}': {read_result.get('error')}")
        
        # Update the conversation's active context files
        self.current_conversation.active_context_files = loaded_files
        self._save_conversations() # Persist the change

        if errors:
            logger.warning("Errors while loading files into context for conversation %s: %s", self.current_conversation.id, errors)
            return {"ok": False, "error": "Some files failed to load: " + "; ".join(errors), "loaded_files": list(loaded_files.keys())}
        
        logger.info("Loaded %d files into active context for conversation %s", len(loaded_files), self.current_conversation.id)
        return {"ok": True, "message": f"Successfully loaded {len(loaded_files)} files into active context.", "loaded_files": list(loaded_files.keys())}
    
    async def _tool_add_decision_log_entry(
        self,
        decision_summary: str,
        reasoning: str,
        impact: str,
        related_files: Optional[list[str]] = None,
        status: str = "implemented",
    ) -> dict:
        """
        Tool: Adds a new entry to the architectural decision log (DECISION_LOG.md).
        This provides long-term memory of architectural choices, their justifications,
        and impacts.

        Args:
            decision_summary: A concise summary of the decision made.
            reasoning: The justification or rationale behind the decision.
            impact: The expected or observed consequences/impact of the decision.
            related_files: (Optional) A list of files or components affected by this decision.
            status: (Optional) The current status of the decision (e.g., implemented, pending, reconsidered).

        Returns:
            A JSON string indicating success or failure.
        """
        log_path = os.path.join(self.workspace_root, "DECISION_LOG.md")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry_content = f"""
## Decision: {decision_summary}
- **Date:** {timestamp}
- **Reasoning:** {reasoning}
- **Impact:** {impact}
- **Status:** {status}
"""
        if related_files:
            entry_content += f"- **Related Files:** {', '.join(related_files)}\n"
        entry_content += "\n---\n" # Separator

        try:
            await asyncio.to_thread(append_file, log_path, entry_content)
            logger.info("Successfully added entry to DECISION_LOG.md")
            return {"ok": True, "message": "Decision log entry added successfully."}
        except Exception as e:
            logger.error("Error adding entry to DECISION_LOG.md: %s", e)
            return {"ok": False, "error": f"Failed to add decision log entry: {e}"}


    async def _tool_builtin_write_file(self, args: dict) -> dict:
        """Built-in filesystem write/overwrite tool."""
        rel_path = str(args.get("path", "")).strip()
        content = str(args.get("content", ""))
        target = self._safe_path(rel_path)
        if not rel_path or not target:
            return {"ok": False, "error": "Invalid file path"}
        try:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "ok": True,
                "path": rel_path,
                "bytes_written": len(content.encode("utf-8")),
                "details": {
                    "type": "file_write",
                    "path": rel_path,
                    "bytes_written": len(content.encode("utf-8")),
                    "content_preview": content[:200]
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to write file: {e}"}

    async def _tool_builtin_edit_file(self, args: dict) -> dict:
        """Built-in filesystem find/replace edit tool."""
        rel_path = str(args.get("path", "")).strip()
        find_text = str(args.get("find", ""))
        replace_text = str(args.get("replace", ""))
        replace_all = bool(args.get("replace_all", False))
        target = self._safe_path(rel_path)
        if not rel_path or not target or not os.path.isfile(target):
            return {"ok": False, "error": "Invalid file path"}
        if find_text == "":
            return {"ok": False, "error": "'find' must not be empty"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            count = content.count(find_text)
            if count == 0:
                return {"ok": False, "error": "Text to replace was not found"}
            if replace_all:
                updated = content.replace(find_text, replace_text)
                replaced = count
            else:
                updated = content.replace(find_text, replace_text, 1)
                replaced = 1
            with open(target, "w", encoding="utf-8") as f:
                f.write(updated_content)

            diff = list(difflib.unified_diff(
                original_content.splitlines(keepends=True),
                updated_content.splitlines(keepends=True),
                fromfile=rel_path + " (original)",
                tofile=rel_path + " (modified)",
                lineterm=""
            ))
            
            return {
                "ok": True,
                "path": rel_path,
                "replacements": replaced,
                "details": {
                    "type": "file_edit",
                    "path": rel_path,
                    "diff": "".join(diff)
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to edit file: {e}"}

    async def _tool_builtin_delete_file(self, args: dict) -> dict:
        """Built-in filesystem delete file tool with mandatory double confirmation."""
        rel_path = str(args.get("path", "")).strip()
        target = self._safe_path(rel_path)
        if not rel_path or not target or not os.path.isfile(target):
            return {"ok": False, "error": "Invalid file path"}
        allowed = await asyncio.to_thread(self._confirm_delete_file_twice_blocking, rel_path)
        if not allowed:
            return {"ok": False, "error": "Deletion rejected by user"}
        try:
            os.remove(target)
            return {"ok": True, "path": rel_path, "deleted": True}
        except Exception as e:
            return {"ok": False, "error": f"Failed to delete file: {e}"}

    async def _tool_builtin_list_directory(self, args: dict) -> dict:
        """Built-in filesystem list directory tool."""
        rel_path = str(args.get("path", ".")).strip() or "."
        max_entries = int(args.get("max_entries", 200))
        max_entries = max(1, min(max_entries, 1000))
        show_hidden = bool(args.get("show_hidden", False))

        target = self._safe_path(rel_path)
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "Invalid directory path"}

        try:
            entries = []
            all_names = sorted(os.listdir(target))

            for name in all_names:
                # Skip hidden files if not requested
                if not show_hidden and name.startswith('.'):
                    continue

                if len(entries) >= max_entries:
                    break

                full_path = os.path.join(target, name)
                is_dir = os.path.isdir(full_path)

                entry = {
                    "name": name,
                    "type": "directory" if is_dir else "file",
                }

                # Add size for files
                if not is_dir:
                    try:
                        size = os.path.getsize(full_path)
                        entry["size"] = size
                        # Human readable size
                        if size < 1024:
                            entry["size_human"] = f"{size} B"
                        elif size < 1024 * 1024:
                            entry["size_human"] = f"{size / 1024:.1f} KB"
                        else:
                            entry["size_human"] = f"{size /
                                                     (1024 *
                                                      1024):.1f} MB"
                    except BaseException:
                        pass

                entries.append(entry)

            return {
                "ok": True,
                "path": rel_path,
                "deleted": True,
                "details": {
                    "type": "file_delete",
                    "path": rel_path,
                }
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to list directory: {e}"}

    async def _tool_builtin_search_files(self, args: dict) -> dict:
        """Built-in filesystem search for files/folders by name pattern."""
        import fnmatch

        pattern = str(args.get("pattern", "")).strip()
        rel_path = str(args.get("path", ".")).strip() or "."
        max_results = int(args.get("max_results", 100))
        max_results = max(1, min(max_results, 500))
        search_type = str(args.get("search_type", "both")).lower()

        if not pattern:
            return {"ok": False, "error": "Missing 'pattern' parameter"}

        if search_type not in ("files", "directories", "both"):
            search_type = "both"

        target = self._safe_path(rel_path)
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "Invalid search path"}

        try:
            matches = []

            # Walk the directory tree
            for root, dirs, files in os.walk(target):
                # Search in directories
                if search_type in ("directories", "both"):
                    for dirname in dirs:
                        if fnmatch.fnmatch(dirname, pattern):
                            rel_match = os.path.relpath(os.path.join(
                                root, dirname), self.workspace_root)
                            matches.append({
                                "path": rel_match,
                                "name": dirname,
                                "type": "directory",
                            })
                            if len(matches) >= max_results:
                                break

                # Search in files
                if search_type in ("files", "both"):
                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            full_path = os.path.join(root, filename)
                            rel_match = os.path.relpath(
                                full_path, self.workspace_root)
                            file_entry = {
                                "path": rel_match,
                                "name": filename,
                                "type": "file",
                            }
                            # Add file size
                            try:
                                size = os.path.getsize(full_path)
                                file_entry["size"] = size
                            except BaseException:
                                pass

                            matches.append(file_entry)
                            if len(matches) >= max_results:
                                break

                if len(matches) >= max_results:
                    break

            return {
                "ok": True,
                "pattern": pattern,
                "search_path": rel_path,
                "matches": matches,
                "count": len(matches),
                "search_type": search_type,
            }
        except Exception as e:
            return {"ok": False, "error": f"Search failed: {e}"}

    def _confirm_delete_file_twice_blocking(self, rel_path: str) -> bool:
        """Require two explicit user approvals before deleting a whole file."""
        first = self._confirm_delete_dialog_blocking(
            "Confirm File Deletion",
            f"The AI requested deleting file:\n{rel_path}\n\nContinue?",
        )
        if not first:
            return False
        second = self._confirm_delete_dialog_blocking(
            "Final Confirmation",
            f"This will permanently delete:\n{rel_path}\n\nDelete this file now?",
        )
        return second

    def _confirm_delete_dialog_blocking(self, title: str, body: str) -> bool:
        """Show one blocking yes/no dialog on GTK main thread."""
        done = threading.Event()
        result = {"ok": False}

        def _show() -> bool:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=title,
            )
            dialog.format_secondary_text(body)
            response = dialog.run()
            dialog.destroy()
            result["ok"] = response == Gtk.ResponseType.OK
            done.set()
            return False

        GLib.idle_add(_show)
        done.wait(timeout=300.0)
        return bool(result["ok"])

    def _safe_path(self, path_value: str) -> Optional[str]:
        """Resolve path within workspace root only."""
        candidate = os.path.abspath(
            os.path.join(
                self.workspace_root,
                path_value))
        root = self.workspace_root + os.sep
        if candidate == self.workspace_root or candidate.startswith(root):
            return candidate
        return None

    def _get_workspace_root(self) -> str:
        """Return the effective workspace root for the current context."""
        if self.current_conversation:
            if self.current_conversation.chat_mode == "agent":
                cfg = self.current_conversation.agent_config
                if isinstance(cfg, dict):
                    proj_dir = str(cfg.get("project_dir", "")).strip()
                    if proj_dir and os.path.isdir(proj_dir):
                        return os.path.abspath(proj_dir)
        return self.workspace_root

    def _default_model_name(self) -> str:
        """Return active loaded model id when known, otherwise fallback."""
        return self.loaded_model_id or "llama2-7b"

    def _reload_tools_bar(self) -> None:
        """Reload MCP servers from disk and rebuild tools bar widget."""
        enabled_before = set(
            self.tools_bar.get_enabled_tools()) if self.tools_bar else set()
        if self.tools_bar:
            self.tools_panel.remove(self.tools_bar)
        mcp_servers = load_mcp_servers()
        self.tools_bar = ToolsBar(
            mcp_servers,
            mcp_discovery=self.mcp_discovery,
            server_configs=load_mcp_server_configs(),
        )
        for integration_id in enabled_before:
            self.tools_bar.set_tool_enabled(integration_id, True)
        self.tools_panel.pack_start(self.tools_bar, True, True, 0)
        self.tools_panel.show_all()

    def _on_add_mcp_server_clicked(self, _button=None) -> None:
        """Prompt for MCP server details and save app-local config."""
        dialog = Gtk.Dialog(
            title="Add MCP Server",
            transient_for=self,
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

        def add_row(row: int, label_text: str, widget: Gtk.Widget) -> None:
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0.0)
            form.attach(label, 0, row, 1, 1)
            form.attach(widget, 1, row, 1, 1)

        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("e.g. playwright")
        add_row(0, "Name*", name_entry)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("e.g. http://127.0.0.1:3001/mcp")
        add_row(1, "URL", url_entry)

        command_entry = Gtk.Entry()
        command_entry.set_placeholder_text("e.g. npx")
        add_row(2, "Command", command_entry)

        args_entry = Gtk.Entry()
        args_entry.set_placeholder_text(
            "comma-separated, e.g. -y,@modelcontextprotocol/server-filesystem,/tmp")
        add_row(3, "Args", args_entry)

        env_view = Gtk.TextView()
        env_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        env_view.set_size_request(-1, 120)
        env_buf = env_view.get_buffer()
        env_buf.set_text("{}", -1)

        env_scroll = Gtk.ScrolledWindow()
        env_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC)
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
        args = [item.strip() for item in args_text.split(
            ",") if item.strip()] if args_text else []

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
                dialog.destroy()
                self._show_error_dialog("Invalid Env JSON", str(e))
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

        dialog.destroy()

        if not server_config:
            self._show_error_dialog(
                "Missing Server Details",
                "Provide at least URL or command details.",
            )
            return

        ok, msg = save_app_mcp_server(name, server_config)
        if not ok:
            self._show_error_dialog("Save Failed", msg)
            return

        self._show_info_dialog("MCP Server Saved", msg)
        self._reload_tools_bar()

    def _show_error_dialog(self, title: str, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _show_info_dialog(self, title: str, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts."""
        # Connect to key-press-event for GTK3
        self.connect("key-press-event", self._on_key_pressed)

    def _on_key_pressed(self, widget, event) -> bool:
        """Handle key press events.

        Args:
            widget: The widget that received the event
            event: The GdkEventKey

        Returns:
            True if the key was handled, False otherwise
        """
        # Check if Ctrl is pressed
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            # Ctrl+N: New chat
            if event.keyval == Gdk.KEY_n:
                self._on_new_chat(None)
                return True
            # Ctrl+Enter in input area
            if event.keyval == Gdk.KEY_Return:
                self._on_send_message(None)
                return True

        return False

    async def initialize_async(self) -> None:
        """Initialize async components.

        This is called by the application to set up the event loop.
        """
        await self.api_client.initialize()
        # Check connection
        is_connected = await self.api_client.check_connection()
        if is_connected:
            print("Connected to LM Studio")
            self.chat_input.update_connection_status(True, "Connected · Ready")
            loaded_model = await self.api_client.get_loaded_model_id()
            if loaded_model:
                self.loaded_model_id = loaded_model
                print(f"Loaded model: {loaded_model}")
                # Keep existing user-selected models; update placeholder
                # defaults only.
                for conv in self.conversations.values():
                    if conv.model == "llama2-7b":
                        conv.model = loaded_model
                if self.current_conversation:
                    self.chat_area.set_conversation(
                        self.current_conversation,
                        context_limit=self._get_effective_settings(
                            self.current_conversation).context_limit,
                    )
                self._save_conversations()
        else:
            print("Warning: Could not connect to LM Studio")
            self.chat_input.update_connection_status(False)

        # Start periodic connection status check
        GLib.timeout_add_seconds(5, self._check_connection_status_periodic)

    def _check_connection_status_periodic(self) -> bool:
        """Periodically check API connection status and update the UI.

        Returns:
            True to continue the timeout, False to stop it.
        """
        def check_and_update():
            """Async helper to check connection and update status."""
            async def do_check():
                try:
                    is_connected = await self.api_client.check_connection()
                    if is_connected:
                        self.chat_input.update_connection_status(
                            True, "Connected · Ready")
                    else:
                        self.chat_input.update_connection_status(
                            False, "Disconnected · LM Studio")
                except Exception as e:
                    print(f"Error checking connection: {e}")
                    self.chat_input.update_connection_status(
                        False, "Disconnected · LM Studio")

            # Run the async check in the event loop
            if self._loop:
                import asyncio
                task = asyncio.ensure_future(do_check(), loop=self._loop)

        check_and_update()
        return True  # Continue the timeout

    def _on_refresh_connection(self) -> None:
        """Handle refresh button click - immediately check connection status."""
        def check_and_update():
            """Async helper to check connection and update status."""
            async def do_check():
                try:
                    # Show checking message
                    GLib.idle_add(
                        self.chat_input.update_connection_status,
                        False,
                        "Checking connection...",
                    )

                    is_connected = await self.api_client.check_connection()
                    if is_connected:
                        GLib.idle_add(
                            self.chat_input.update_connection_status,
                            True,
                            "Connected · Ready",
                        )
                    else:
                        GLib.idle_add(
                            self.chat_input.update_connection_status,
                            False,
                            "Disconnected · LM Studio",
                        )
                except Exception as e:
                    print(f"Error checking connection: {e}")
                    GLib.idle_add(
                        self.chat_input.update_connection_status,
                        False,
                        "Disconnected · LM Studio",
                    )

            # Run the async check in a new thread
            import asyncio
            import threading

            def run_check():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(do_check())
                finally:
                    loop.close()

            threading.Thread(target=run_check, daemon=True).start()

        check_and_update()
