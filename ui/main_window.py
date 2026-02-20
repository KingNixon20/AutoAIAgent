"""
Main application window orchestrating all UI components.
"""
import logging
import threading
import uuid
import asyncio
from dataclasses import replace
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk

from models import Message, MessageRole, Conversation, ConversationSettings
from api import LMStudioClient
from storage import load_conversations, load_tools, load_mcp_servers, save_conversations

logger = logging.getLogger(__name__)
from ui.components import (
    ChatArea,
    ChatInput,
    Sidebar,
    SettingsPanel,
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
        self.set_default_size(C.WINDOW_DEFAULT_WIDTH, C.WINDOW_DEFAULT_HEIGHT)
        self.set_size_request(C.WINDOW_MIN_WIDTH, C.WINDOW_MIN_HEIGHT)
        
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
        
        # Data
        self.conversations = {}
        self.current_conversation: Optional[Conversation] = None
        self.settings = ConversationSettings()
        
        # Create layout: a resizable split between sidebar and chat center
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        main_box.set_homogeneous(False)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.new_chat_button.connect("clicked", self._on_new_chat)
        self.sidebar.settings_btn.connect("clicked", self._on_toggle_settings)
        self.sidebar.on_conversation_selected = self._on_conversation_selected
        self.sidebar.on_conversation_delete = self._on_delete_conversation

        # Center: Chat area - constrain width for improved readability
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center_box.set_homogeneous(False)
        center_box.set_size_request(800, -1)  # Preferred max width for chat panel

        self.chat_area = ChatArea()
        center_box.pack_start(self.chat_area, True, True, 0)

        # Tools bar (MCP tools above input)
        mcp_servers = load_mcp_servers()
        self.tools_bar = ToolsBar(mcp_servers)
        center_box.pack_end(self.tools_bar, False, False, 0)

        # Input area
        self.chat_input = ChatInput()
        self.chat_input.connect_send(self._on_send_message)
        center_box.pack_end(self.chat_input, False, False, 0)

        # Use a paned splitter so the user can resize sidebar <-> chat area
        paned = Gtk.HPaned()
        paned.add1(self.sidebar)
        paned.add2(center_box)
        paned.set_position(260)

        # Settings panel (collapsible right side)
        self.settings_panel = SettingsPanel()
        self.settings_panel.set_no_show_all(True)
        self.settings_panel.close_btn.connect("clicked", lambda *_: self.settings_panel.set_visible(False))

        main_box.pack_start(paned, True, True, 0)
        main_box.pack_end(self.settings_panel, False, False, 0)

        self.add(main_box)
        self.show_all()
        
        # Initialize conversations - load saved or create sample
        self._load_or_create_conversations()
        
        # Setup keyboard shortcuts
        self._setup_shortcuts()

    def _load_or_create_conversations(self) -> None:
        """Load saved conversations from disk, or create a sample if none exist."""
        saved = load_conversations()
        if saved:
            for conv in saved:
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
                model="llama2-7b"
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
            self.chat_area.set_conversation(self.current_conversation)
            self.chat_input.focus()

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

    def _on_toggle_settings(self, button) -> None:
        """Toggle settings panel visibility."""
        visible = self.settings_panel.get_visible()
        self.settings_panel.set_visible(not visible)
        if not visible:
            self.settings_panel.show_all()

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
            model="llama2-7b"
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
        
        logger.info("User: %s", text)
        
        # Add user message
        user_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=text,
            tokens=asyncio.run(self.api_client.count_tokens(text))
        )
        self.current_conversation.add_message(user_msg)
        self.chat_area.add_message(user_msg)
        self._save_conversations()
        
        # Clear input
        self.chat_input.clear()
        
        # Show typing indicator
        self.chat_area.show_typing_indicator()
        
        # Capture conversation for this request - ensures full context is sent
        # even if user switches conversations before response arrives
        conv = self.current_conversation
        conv_id = conv.id
        threading.Thread(
            target=self._fetch_ai_response,
            args=(text, conv, conv_id),
            daemon=True,
        ).start()

    def _fetch_ai_response(
        self, user_text: str, conversation: Conversation, conversation_id: str
    ) -> None:
        """Fetch AI response from API (runs in background thread).
        
        Uses the captured conversation so full context (all prior messages)
        is always sent to the API for memory.
        """
        response_text = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                response_text = loop.run_until_complete(
                    self._get_api_response(conversation)
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning("API request failed, using fallback: %s", e)
        
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
            priority=GLib.PRIORITY_DEFAULT,
        )

    async def _get_api_response(self, conversation: Conversation) -> Optional[str]:
        """Call LM Studio API with full conversation context for memory."""
        if not conversation or not self.api_client.is_connected:
            return None
        settings = self.settings
        tools, tool_choice = load_tools()
        if tools is not None:
            settings = replace(
                settings, tools=tools, tool_choice=tool_choice
            )
        enabled_mcp = self.tools_bar.get_enabled_tools()
        if enabled_mcp:
            settings = replace(settings, integrations=enabled_mcp)
        chunks = []
        async for chunk in self.api_client.chat_completion(
            conversation, settings
        ):
            chunks.append(chunk)
        return "".join(chunks) if chunks else None

    def _add_assistant_message_and_save(
        self, response_text: str, conversation_id: str
    ) -> bool:
        """Add assistant message to UI and save (runs on main thread)."""
        if conversation_id not in self.conversations:
            return False
        conv = self.conversations[conversation_id]
        self.chat_area.hide_typing_indicator()
        ai_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content=response_text,
            tokens=50
        )
        conv.add_message(ai_msg)
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.current_conversation = conv
            self.chat_area.add_message(ai_msg)
        self._save_conversations()
        return False  # Don't reschedule idle

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
                self.chat_input._on_send_message(None)
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
        else:
            print("Warning: Could not connect to LM Studio")
