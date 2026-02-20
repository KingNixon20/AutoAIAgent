"""
Main application window orchestrating all UI components.
"""
import logging
import threading
import uuid
import asyncio
from dataclasses import replace
from typing import Optional
import re
import os
import json
import shlex
from token_counter import count_text_tokens

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk

from models import Message, MessageRole, Conversation, ConversationSettings
from api import LMStudioClient
from storage import (
    load_conversations,
    load_tools,
    load_mcp_servers,
    load_mcp_server_configs,
    save_app_mcp_server,
    save_conversations,
)
from mcp_discovery import MCPToolDiscovery

logger = logging.getLogger(__name__)
from ui.components import (
    ChatArea,
    ChatInput,
    Sidebar,
    SettingsWindow,
    ToolsBar,
)
import constants as C


class MainWindow(Gtk.ApplicationWindow):
    """Main application window with three-panel layout."""

    def __init__(self, app: Gtk.Application):
        """Initialize the main window.
        
        Args:
            app: The Gtk.Application instance.
        """
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
        self._window_max_width = min(int(getattr(C, "WINDOW_MAX_WIDTH", 2560)), int(screen_width))
        self._window_max_height = min(int(getattr(C, "WINDOW_MAX_HEIGHT", 1440)), int(screen_height))
        self._window_min_width = min(int(C.WINDOW_MIN_WIDTH), self._window_max_width)
        self._window_min_height = min(int(C.WINDOW_MIN_HEIGHT), self._window_max_height)
        start_w = int(getattr(C, "WINDOW_START_WIDTH", 0) or 0)
        start_h = int(getattr(C, "WINDOW_START_HEIGHT", 0) or 0)
        if start_w > 0:
            self._window_min_width = min(self._window_min_width, start_w)
        if start_h > 0:
            self._window_min_height = min(self._window_min_height, start_h)

        # Default window size: use a fraction of the screen (responsive)
        try:
            ratio = float(getattr(C, "WINDOW_DEFAULT_RATIO", 0.5))
            default_width = int(min(max(int(screen_width * ratio), self._window_min_width), self._window_max_width))
            default_height = int(min(max(int(screen_height * ratio), self._window_min_height), self._window_max_height))
        except Exception:
            default_width = min(int(C.WINDOW_DEFAULT_WIDTH), self._window_max_width)
            default_height = min(int(C.WINDOW_DEFAULT_HEIGHT), self._window_max_height)
        # Optional fixed startup dimensions (still clamped by screen and min/max).
        if start_w > 0:
            default_width = min(max(start_w, self._window_min_width), self._window_max_width)
        if start_h > 0:
            default_height = min(max(start_h, self._window_min_height), self._window_max_height)
        # Keep startup size comfortable even on very large monitors — allow
        # larger initial heights so content fits, but clamp to overall max.
        startup_cap_w = max(self._window_min_width, min(int(screen_width * 0.8), int(self._window_max_width)))
        startup_cap_h = max(self._window_min_height, min(int(screen_height * 0.85), int(self._window_max_height)))
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
        css_provider.load_from_path("/home/kingnixon/Documents/Python Projects/AutoAIAgent/ui/styles.css")
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

        self.chat_area = ChatArea()
        self.chat_area.on_chat_settings_changed = self._on_chat_settings_changed
        center_box.pack_start(self.chat_area, True, True, 0)

        # Input area
        self.chat_input = ChatInput()
        self.chat_input.set_api_client(self.api_client)
        self.chat_input.connect_send(self._on_send_message)
        self.chat_input.connect_mode_changed(self._on_chat_mode_changed)
        center_box.pack_end(self.chat_input, False, False, 0)

        # Right tools panel (resizable)
        self.tools_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tools_panel.get_style_context().add_class("tools-side-panel")

        tools_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tools_header.get_style_context().add_class("tools-side-header")
        tools_header.set_margin_start(12)
        tools_header.set_margin_end(12)
        tools_header.set_margin_top(12)
        tools_header.set_margin_bottom(10)
        tools_title = Gtk.Label()
        tools_title.set_halign(Gtk.Align.START)
        tools_title.set_xalign(0.0)
        tools_title.set_markup("<span weight='600' size='11000'>MCP Tools</span>")
        tools_header.pack_start(tools_title, True, True, 0)
        add_tool_btn = Gtk.Button(label="Add")
        add_tool_btn.set_tooltip_text("Add app-local MCP server")
        add_tool_btn.connect("clicked", self._on_add_mcp_server_clicked)
        tools_header.pack_end(add_tool_btn, False, False, 0)
        self.tools_panel.pack_start(tools_header, False, False, 0)
        self.tools_panel.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

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
            # Start slightly wider so more conversation titles/content are visible.
            desired = max(250, min(390, base_sidebar + 28))
            desired = min(desired, max(220, int(default_width * 0.3)))
            self._initial_pane_position = desired
            paned.set_position(desired)
            # Right tools panel defaults to roughly sidebar width (+divider allowance).
            self._initial_tools_panel_width = max(220, min(360, desired + 8))
        except Exception:
            self._initial_pane_position = 240
            paned.set_position(260)
            self._initial_tools_panel_width = 248

        # Settings window - opens as full overlay tab with all controls visible
        self.settings_window = SettingsWindow()
        self.settings_window.close_btn.connect("clicked", lambda *_: self._hide_settings_overlay())
        self.settings_window.on_mcp_servers_changed = self._reload_tools_bar
        self.chat_area.set_global_settings_provider(self.settings_window.get_settings)

        main_box.pack_start(paned, True, True, 0)
        
        # Create overlay for settings window
        self.settings_overlay = Gtk.Overlay()
        self.settings_overlay.add(main_box)
        self.settings_overlay.add_overlay(self.settings_window)
        try:
            self.settings_overlay.set_overlay_pass_through(self.settings_window, False)
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
            target_tools_width = int(getattr(self, "_initial_tools_panel_width", 248))
            # Keep tools panel visible and avoid collapsing chat area.
            target_tools_width = max(200, min(target_tools_width, max(220, int(pane_width * 0.45))))
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

    

    def _on_configure_event(self, _widget, event) -> bool:
        """Clamp runtime resize requests to safe max bounds.

        We only enforce upper bounds here. Lower bounds are already handled by
        geometry hints, and forcing min-size from transient configure events can
        cause unwanted window snaps while interacting with popovers.
        """
        width = int(getattr(event, "width", 0) or 0)
        height = int(getattr(event, "height", 0) or 0)
        clamped_w = min(width, self._window_max_width)
        clamped_h = min(height, self._window_max_height)
        if (width > self._window_max_width) or (height > self._window_max_height):
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
            self.sidebar.set_ai_tasks(conversation_id, self.current_conversation.ai_tasks)
            self._suppress_mode_change = True
            self.chat_input.set_mode(getattr(self.current_conversation, "chat_mode", "ask"))
            self._suppress_mode_change = False
            settings = self._get_effective_settings(self.current_conversation)
            self.chat_area.set_conversation(self.current_conversation, context_limit=settings.context_limit)
            self.chat_input.focus()

    def _on_chat_settings_changed(self, conversation: Conversation, payload: dict) -> None:
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
            self._request_agent_stop(self.current_conversation.id, "Mode switched away from Agent.")
        self.current_conversation.chat_mode = mode
        self._save_conversations()

    def _on_sidebar_tasks_changed(self, conversation_id: str, tasks: list[dict]) -> None:
        """Persist AI task changes coming from sidebar AI Tasks tab."""
        if conversation_id not in self.conversations:
            return
        cleaned = self._normalize_task_list(tasks)
        self.conversations[conversation_id].ai_tasks = cleaned
        self._save_conversations()

    def _get_effective_settings(self, conversation: Conversation) -> ConversationSettings:
        """Merge per-chat overrides on top of global settings."""
        global_settings = self.settings_window.get_settings()
        chat_settings = conversation.chat_settings if isinstance(conversation.chat_settings, dict) else None
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

    def _show_context_limit_warning(self, current_tokens: int, limit: int) -> None:
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
            f"The conversation context ({current_tokens:,} tokens) exceeds your limit ({limit:,} tokens). "
            f"The API will use a sliding window to keep the most recent messages. "
            f"You can adjust the context limit in Settings → Model."
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

    def _on_send_message(self, button) -> None:
        """Handle message sending.
        
        Args:
            button: The send button.
        """
        if not self.current_conversation:
            return
        
        text = self.chat_input.get_text().strip()
        if not text:
            return
        mode = self.chat_input.get_mode()
        if mode == "agent":
            if not self._ensure_agent_config(self.current_conversation):
                return
        conv_id = self.current_conversation.id
        if self._is_agent_running(conv_id):
            self._request_agent_stop(
                conv_id,
                "User submitted a new message. Current agent run will stop after the active step.",
            )
        if getattr(self.current_conversation, "chat_mode", "ask") != mode:
            self.current_conversation.chat_mode = mode
            self._save_conversations()
        
        logger.info("User: %s", text)
        logger.info("Mode: %s", mode)
        
        # Add user message
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
        
        # Clear input
        self.chat_input.clear()
        
        # Check context limit before proceeding
        settings = self._get_effective_settings(self.current_conversation)
        context_tokens = self.current_conversation.estimate_context_tokens(
            model=self.current_conversation.model
        )
        if (not settings.token_saver) and context_tokens > settings.context_limit:
            self._show_context_limit_warning(context_tokens, settings.context_limit)
            # Show typing indicator anyway since user message is added
            self.chat_area.show_typing_indicator()
        else:
            # Show typing indicator
            self.chat_area.show_typing_indicator()
        
        # Capture conversation for this request - ensures full context is sent
        # even if user switches conversations before response arrives
        conv = self.current_conversation
        conv_id = conv.id
        if mode == "agent" and self._is_agent_running(conv_id):
            self.chat_area.hide_typing_indicator()
            return
        threading.Thread(
            target=self._fetch_ai_response,
            args=(text, conv, conv_id, settings, mode),
            daemon=True,
        ).start()

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
        if mode == "agent":
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
                return
            self._set_agent_running(conversation_id, True)
            self._clear_agent_stop_request(conversation_id)
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        self._run_agent_mode_sequence(
                            conversation=conversation,
                            conversation_id=conversation_id,
                            settings=settings,
                            user_text=user_text,
                        )
                    )
                finally:
                    loop.close()
            except Exception as e:
                logger.warning("Agent mode run failed: %s", e)
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
            return

        response_text = None
        tool_events = []
        followup_message = ""
        followup_tasks: list[dict] = []
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            planned_tasks = []
            try:
                response_text, tool_events, planned_tasks = loop.run_until_complete(
                    self._get_api_response(conversation, settings, mode=mode)
                )
                if mode == "plan" and response_text:
                    followup_message, followup_tasks = loop.run_until_complete(
                        self._plan_mode_review_for_missing_info(
                            conversation=conversation,
                            settings=settings,
                            plan_response=response_text,
                            planned_tasks=planned_tasks,
                        )
                    )
            finally:
                loop.close()
        except Exception as e:
            logger.warning("API request failed, using fallback: %s", e)
            planned_tasks = []
            followup_message = ""
            followup_tasks = []
        
        if response_text is None:
            import random
            responses = [
                "That's a great question! Let me think about that...",
                "I understand. Here's what I think about that topic.",
                "Interesting point. In my experience, the key considerations are:",
                "I can help with that. Let me break it down for you.",
            ]
            response_text = random.choice(responses)
        
        logger.info("Assistant: %s", response_text)
        
        # Update UI on main thread - pass conv id so we add to correct conversation
        GLib.idle_add(
            self._add_assistant_message_and_save,
            response_text,
            conversation_id,
            tool_events,
            planned_tasks,
            priority=GLib.PRIORITY_DEFAULT,
        )
        if followup_message or followup_tasks:
            GLib.idle_add(
                self._add_plan_followup_and_save,
                followup_message,
                conversation_id,
                followup_tasks,
                priority=GLib.PRIORITY_DEFAULT,
            )

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
                tasks=conversation.ai_tasks if isinstance(conversation.ai_tasks, list) else [],
            ),
        )
        configured_tools, configured_tool_choice = load_tools()
        enabled_tool_metadata = self.tools_bar.get_enabled_tool_metadata()
        enabled_mcp = [tool["id"] for tool in enabled_tool_metadata]
        builtin_enabled = "mcp/builtin_filesystem" in enabled_mcp
        enabled_mcp_external = [iid for iid in enabled_mcp if iid != "mcp/builtin_filesystem"]
        selected_tools: list[dict] = []
        tool_choice = None

        # Discover full MCP tool definitions (name/description/input schema) from enabled endpoints.
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
                self._select_tools_for_enabled_integrations(configured_tools, enabled_mcp_external)
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
                # This allows the API to reference the integration even if full discovery failed
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
            logger.info("Sending %d tools to API with tool_choice='%s'", len(selected_tools), tool_choice)
            for tool in selected_tools:
                if isinstance(tool, dict):
                    fn = tool.get("function") or {}
                    name = fn.get("name", "?")
                    desc = fn.get("description", "")
                    logger.info("  • %s: %s", name, desc)

        if enabled_mcp_external:
            current_settings = replace(current_settings, integrations=enabled_mcp_external)
        mcp_tool_map = self._build_mcp_tool_map(selected_tools)
        tool_events: list[dict] = []
        response_text = await self.api_client.chat_completion_with_tools(
            conversation=conversation,
            settings=current_settings,
            tool_executor=lambda name, args: self._execute_tool_call_with_approval(
                name,
                args,
                settings=current_settings,
                mcp_tool_map=mcp_tool_map,
                server_configs=server_configs,
            ),
            on_tool_event=lambda ev: tool_events.append(ev),
        )
        planned_tasks = []
        if mode == "plan" and response_text:
            planned_tasks = self._extract_tasks_from_plan_response(response_text)
        return (response_text, tool_events, planned_tasks)

    async def _execute_tool_call_with_approval(
        self,
        tool_name: str,
        args: dict,
        settings: ConversationSettings,
        mcp_tool_map: Optional[dict[str, dict]] = None,
        server_configs: Optional[dict[str, dict]] = None,
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
                return json.dumps(
                    {
                        "ok": False,
                        "error": "Tool execution rejected by user.",
                        "tool": tool_name,
                    },
                    ensure_ascii=False,
                )
        return await self._execute_tool_call(
            tool_name,
            args,
            mcp_tool_map=mcp_tool_map,
            server_configs=server_configs,
        )

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
        project_dir = str(cfg.get("project_dir", self.workspace_root)).strip() or self.workspace_root
        GLib.idle_add(
            self._add_agent_progress_message,
            conversation_id,
            f"Starting implementation for {project_name} in {project_dir}.",
            priority=GLib.PRIORITY_DEFAULT,
        )

        for ordinal, task_index in enumerate(pending_indices, start=1):
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
                f"Task {ordinal}/{len(pending_indices)} in progress: {task_text}",
                priority=GLib.PRIORITY_DEFAULT,
            )

            agent_instruction = (
                f"Project name: {project_name}\n"
                f"Project directory: {project_dir}\n"
                f"User request context: {user_text}\n"
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
            )
            temp_conv.add_message(
                Message(
                    id=str(uuid.uuid4()),
                    role=MessageRole.USER,
                    content=agent_instruction,
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
            GLib.idle_add(
                self._add_assistant_message_and_save,
                response_text or f"[Agent] Task {ordinal} completed with no summary.",
                conversation_id,
                tool_events,
                None,
                priority=GLib.PRIORITY_DEFAULT,
            )
            if tool_events:
                GLib.idle_add(
                    self._add_agent_progress_message,
                    conversation_id,
                    self._format_agent_tool_output(ordinal, tool_events),
                    priority=GLib.PRIORITY_DEFAULT,
                )

            compile_ok, compile_detail = await self._run_compile_check(project_dir)
            if compile_ok:
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
                    "Compile check passed.\n"
                    f"Task {ordinal}/{len(pending_indices)} compiler output:\n"
                    f"```text\n{compile_detail}\n```",
                    priority=GLib.PRIORITY_DEFAULT,
                )
                continue

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
            return

        GLib.idle_add(
            self._add_agent_progress_message,
            conversation_id,
            "All pending tasks completed.",
            priority=GLib.PRIORITY_DEFAULT,
        )

    def _format_agent_tool_output(self, task_num: int, tool_events: list[dict]) -> str:
        """Build readable per-task tool execution output for chat."""
        lines = [f"Task {task_num} tool output:"]
        for ev in tool_events or []:
            if not isinstance(ev, dict):
                continue
            name = str(ev.get("name", "tool"))
            result = ev.get("result")
            preview = self._compact_tool_result_for_chat(result)
            lines.append(f"- {name}: {preview}")
        body = "\n".join(lines)
        return f"{body}"

    def _compact_tool_result_for_chat(self, result: object) -> str:
        """Compact one-line rendering of tool result."""
        if isinstance(result, dict):
            if result.get("ok") is False and result.get("error"):
                return str(result.get("error"))[:260]
            for key in ("stdout", "content", "message", "result"):
                val = result.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip().replace("\n", " ")[:260]
            return str(result)[:260]
        return str(result)[:260]

    def _add_agent_progress_message(self, conversation_id: str, text: str) -> bool:
        """Add a progress message for agent workflow."""
        return self._add_assistant_message_and_save(
            f"[Agent] {text}",
            conversation_id,
            tool_events=[],
            planned_tasks=None,
        )

    def _set_task_status_and_save(self, conversation_id: str, task_index: int, status: str) -> bool:
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

    def _hide_typing_indicator_for_conversation(self, conversation_id: str) -> bool:
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

    def _build_mode_system_prompt(self, mode: str, base_prompt: str, tasks: list[dict]) -> str:
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
            task_context = "\n".join(task_lines) if task_lines else "(no saved tasks)"
            return (
                f"{base}\n\n"
                "You are in AGENT mode.\n"
                "Act as an implementation agent, not a planner.\n"
                "Execute tasks sequentially, one step at a time, and prefer concrete actions.\n"
                "Use available tools whenever they help you inspect files, edit code, run checks, or verify results.\n"
                "When you use a tool, interpret the result and continue toward task completion.\n"
                "Do not ask for unnecessary confirmation; proceed unless blocked by missing required information.\n"
                "After each task, provide a concise progress update and what changed.\n"
                "Saved tasks:\n"
                f"{task_context}\n"
                "Reference the current task you are executing."
            )
        return base

    def _extract_tasks_from_plan_response(self, response_text: str) -> list[dict]:
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
                    prefix = f"Step {step_no}: " if isinstance(step_no, int) else "Step: "
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
                    tasks.append({"text": task_text, "done": False, "status": "uncompleted"})
                if tasks:
                    return tasks[:24]

        block_match = re.search(r"<ai_tasks>(.*?)</ai_tasks>", text, flags=re.IGNORECASE | re.DOTALL)
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
                    tasks.append({"text": task_text, "done": False, "status": "uncompleted"})
                continue
            # Numbered/bulleted fallback
            m2 = re.match(r"^(?:\d+[.)]|[-*])\s+(.+)$", line)
            if m2:
                task_text = m2.group(1).strip()
                key = task_text.lower()
                if task_text and key not in seen:
                    seen.add(key)
                    tasks.append({"text": task_text, "done": False, "status": "uncompleted"})

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

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
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

            # Build temporary conversation context including the generated plan.
            temp_conv = Conversation(
                id=conversation.id,
                title=conversation.title,
                messages=list(conversation.messages),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                model=conversation.model,
                total_tokens=conversation.total_tokens,
                chat_settings=conversation.chat_settings,
                ai_tasks=list(conversation.ai_tasks) if isinstance(conversation.ai_tasks, list) else [],
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
            mark = "x" if status == "completed" else ("~" if status == "in_progress" else " ")
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
        assistant_message = str(payload.get("assistant_message", "") or "").strip()
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
                status = "completed" if bool(task.get("done", False)) else "uncompleted"
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
        cfg = conversation.agent_config if isinstance(conversation.agent_config, dict) else {}
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
        info.set_markup("<span size='9500'>Configure this conversation for Agent mode.</span>")
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
            self._show_error_dialog("Agent Setup", "Project directory is required.")
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
            fn = tool.get("function") if tool.get("type") == "function" else tool
            fn_name = ""
            if isinstance(fn, dict):
                fn_name = str(fn.get("name", "")).lower()
            for normalized_key in normalized_enabled.keys():
                if fn_name.startswith(normalized_key + "_"):
                    selected.append(tool)
                    break

        return selected

    def _build_tools_from_enabled_mcp(self, enabled_tools: list[dict]) -> list[dict]:
        """Build minimal function tool definitions from enabled MCP metadata."""
        tool_defs = []
        for tool in enabled_tools:
            integration_id = tool.get("id") or "mcp/tool"
            integration_name = self._sanitize_identifier(integration_id.replace("/", "_"))
            calls = tool.get("calls") or []
            if not calls:
                calls = ["run"]
            for call in calls:
                call_name = self._sanitize_identifier(str(call))
                fn_name = self._sanitize_identifier(f"{integration_name}_{call_name}")
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
            fn = tool.get("function") if tool.get("type") == "function" else tool
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
    ) -> str:
        """Safely execute supported tool calls and return serialized result text."""
        handlers = {
            "list_files": self._tool_list_files,
            "read_file": self._tool_read_file,
            "search_text": self._tool_search_text,
            "run_command": self._tool_run_command,
            "builtin_read_file": self._tool_builtin_read_file,
            "builtin_write_file": self._tool_builtin_write_file,
            "builtin_edit_file": self._tool_builtin_edit_file,
            "builtin_delete_file": self._tool_builtin_delete_file,
        }
        handler = handlers.get(tool_name)
        if handler is not None:
            result = await handler(args or {})
            return json.dumps(result, ensure_ascii=False)

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
                return json.dumps(result, ensure_ascii=False)

        return json.dumps(
            {
                "ok": False,
                "error": f"Unsupported tool: {tool_name}",
                "supported_tools": sorted(list(handlers.keys())),
            },
            ensure_ascii=False,
        )

    def _builtin_filesystem_tools(self) -> list[dict]:
        """Tool definitions for built-in local filesystem integration."""
        return [
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
            integration_id = tool.get("integration_id") or tool.get("x-integration-id")
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
            return {"ok": False, "error": "Invalid directory path"}
        names = sorted(os.listdir(target))[:max_results]
        return {"ok": True, "path": rel_path, "entries": names, "count": len(names)}

    async def _tool_read_file(self, args: dict) -> dict:
        rel_path = str(args.get("path", "")).strip()
        max_chars = int(args.get("max_chars", 12000))
        max_chars = max(256, min(max_chars, 50000))
        target = self._safe_path(rel_path)
        if not rel_path or not target or not os.path.isfile(target):
            return {"ok": False, "error": "Invalid file path"}
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
            return {"ok": False, "error": "Invalid search path"}

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
            return {"ok": False, "error": f"Command not allowed: {cmd[0]}", "allowed": sorted(list(allowed))}

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
            }
        except Exception as e:
            return {"ok": False, "error": f"Command failed: {e}"}

    async def _tool_builtin_read_file(self, args: dict) -> dict:
        """Built-in filesystem read file tool."""
        return await self._tool_read_file(args)

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
            return {"ok": True, "path": rel_path, "bytes_written": len(content.encode("utf-8"))}
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
                f.write(updated)
            return {"ok": True, "path": rel_path, "replacements": replaced}
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
        candidate = os.path.abspath(os.path.join(self.workspace_root, path_value))
        root = self.workspace_root + os.sep
        if candidate == self.workspace_root or candidate.startswith(root):
            return candidate
        return None

    def _default_model_name(self) -> str:
        """Return active loaded model id when known, otherwise fallback."""
        return self.loaded_model_id or "llama2-7b"

    def _reload_tools_bar(self) -> None:
        """Reload MCP servers from disk and rebuild tools bar widget."""
        enabled_before = set(self.tools_bar.get_enabled_tools()) if self.tools_bar else set()
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
        args_entry.set_placeholder_text("comma-separated, e.g. -y,@modelcontextprotocol/server-filesystem,/tmp")
        add_row(3, "Args", args_entry)

        env_view = Gtk.TextView()
        env_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        env_view.set_size_request(-1, 120)
        env_buf = env_view.get_buffer()
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
                # Keep existing user-selected models; update placeholder defaults only.
                for conv in self.conversations.values():
                    if conv.model == "llama2-7b":
                        conv.model = loaded_model
                if self.current_conversation:
                    self.chat_area.set_conversation(
                        self.current_conversation,
                        context_limit=self._get_effective_settings(self.current_conversation).context_limit,
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
                        self.chat_input.update_connection_status(True, "Connected · Ready")
                    else:
                        self.chat_input.update_connection_status(False, "Disconnected · LM Studio")
                except Exception as e:
                    print(f"Error checking connection: {e}")
                    self.chat_input.update_connection_status(False, "Disconnected · LM Studio")
            
            # Run the async check in the event loop
            if self._loop:
                import asyncio
                task = asyncio.ensure_future(do_check(), loop=self._loop)
        
        check_and_update()
        return True  # Continue the timeout
