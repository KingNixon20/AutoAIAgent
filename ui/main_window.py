"""
Main application window orchestrating all UI components.
"""
import uuid
import asyncio
import gi
from datetime import datetime
from typing import Optional

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk

from models import Message, MessageRole, Conversation, ConversationSettings
from api import LMStudioClient
from ui.components import (
    ChatArea,
    ChatInput,
    Sidebar,
    SettingsPanel,
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
        self.sidebar.on_conversation_selected = self._on_conversation_selected

        # Center: Chat area - constrain width for improved readability
        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        center_box.set_homogeneous(False)
        center_box.set_size_request(800, -1)  # Preferred max width for chat panel

        self.chat_area = ChatArea()
        center_box.pack_start(self.chat_area, True, True, 0)

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

        main_box.pack_start(paned, True, True, 0)
        main_box.pack_end(self.settings_panel, False, False, 0)

        self.add(main_box)
        self.show_all()
        
        # Initialize conversations
        self._create_sample_conversations()
        
        # Setup keyboard shortcuts
        self._setup_shortcuts()

    def _create_sample_conversations(self) -> None:
        """Create sample conversations for testing."""
        # Sample conversation
        conv2 = Conversation(
            id=str(uuid.uuid4()),
            title="GTK UI Design",
            model="llama2-7b"
        )
        conv2.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content="What are the best practices for GTK4 UI design?"
        ))
        conv2.add_message(Message(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content="GTK4 emphasizes modern design principles. Key practices include:\n\n- Use CSS for styling and theming\n- Leverage hardware acceleration\n- Design responsive layouts\n- Follow GNOME design guidelines\n- Use reactive programming patterns"
        ))
        self.conversations[conv2.id] = conv2
        self.sidebar.add_conversation(conv2)
        
        # Load sample conversation
        self._load_conversation(conv2.id)

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
        
        # Add user message
        user_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.USER,
            content=text,
            tokens=asyncio.run(self.api_client.count_tokens(text))
        )
        self.current_conversation.add_message(user_msg)
        self.chat_area.add_message(user_msg)
        
        # Clear input
        self.chat_input.clear()
        
        # Show typing indicator
        self.chat_area.show_typing_indicator()
        
        # Simulate AI response (in real app, connect to API)
        GLib.timeout_add(800, self._simulate_ai_response)

    def _simulate_ai_response(self) -> bool:
        """Simulate AI response (placeholder for API integration).
        
        Returns:
            False to stop timeout.
        """
        if not self.current_conversation:
            return False
        
        self.chat_area.hide_typing_indicator()
        
        # Create a sample response
        responses = [
            "That's a great question! Let me think about that...",
            "I understand. Here's what I think about that topic.",
            "Interesting point. In my experience, the key considerations are:",
            "I can help with that. Let me break it down for you.",
        ]
        
        import random
        ai_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content=random.choice(responses),
            tokens=50
        )
        self.current_conversation.add_message(ai_msg)
        self.chat_area.add_message(ai_msg)
        
        return False

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
