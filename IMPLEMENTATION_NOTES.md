# Implementation Notes

Technical architecture and design decisions behind AutoAI Chat Client.

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│           GTK Application                   │
│  (Gtk.Application - main.py)                │
└────────────────────┬────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
    ┌────▼────────────┐  ┌──────▼──────────┐
    │  Main Window    │  │ LM Studio API   │
    │ (ui/main_window)│  │ (api/__init__)  │
    └────┬────────────┘  └─────────────────┘
         │                       │
    ┌────┴──────────────────────┴─────┐
    │                                 │
 ┌──▼───────┐ ┌──────────┐ ┌────────▼──┐
 │ Sidebar  │ │Chat Area │ │ Settings  │
 │Components│ │Components│ │ Panel     │
 └──────────┘ └──────────┘ └───────────┘
    │              │             │
    └──────┬───────┴─────────────┘
           │
    ┌──────▼──────────┐
    │  Data Models    │
    │ (models/)       │
    └─────────────────┘
```

---

## Component Breakdown

### 1. Entry Point: `main.py`

**Purpose**: Application initialization and event loop setup

**Key Classes**:
- `AutoAIApplication(Gtk.Application)`: Main app controller
  - Inherits from GTK Application
  - Handles activation signal
  - Creates main window
  - Sets up async event loop

**Initialization Flow**:
```
main()
  → AutoAIApplication.__init__()
  → app.run(sys.argv)
  → GTK main loop starts
  → _on_activate()
  → MainWindow created
  → asyncio event loop configured
  → Window presented
```

**Key Methods**:
- `_on_activate(app)`: Called when app started
  - Creates MainWindow (if not exists)
  - Presents window to user
  - Sets up async support

**Why This Design**:
- Clean separation between GTK and async code
- Single application instance (enforced by GTK)
- Proper lifecycle management

---

### 2. Main Window: `ui/main_window.py`

**Purpose**: Orchestrates all UI components and application logic

**Key Class**: `MainWindow(Gtk.ApplicationWindow)`

**Components Integrated**:
1. **Sidebar** (left)
   - Conversation list
   - New chat button
   - Search functionality

2. **Chat Area** (center)
   - Message display
   - Typing indicator
   - Auto-scroll to bottom

3. **Chat Input** (center bottom)
   - Text input with auto-expand
   - Send button with state management
   - Status indicator

4. **Settings Panel** (right, optional)
   - Model parameters (temperature, tokens, etc.)
   - System prompt editor
   - Connection stats

**Data Management**:
```python
self.conversations: dict[str, Conversation]  # All conversations
self.current_conversation: Conversation       # Active conversation
self.settings: ConversationSettings          # Active settings
self.api_client: LMStudioClient              # API connection
```

**Key Methods**:

- `_create_sample_conversations()`: Initialize demo data
  - Creates 2 sample conversations
  - Adds to sidebar
  - Loads first one

- `_load_conversation(id)`: Switch active conversation
  - Fetches from self.conversations
  - Updates sidebar highlight
  - Renders messages in chat area
  - Focuses input

- `_on_send_message(button)`: Message sending pipeline
  - Gets text from input
  - Creates Message object
  - Adds to conversation
  - Updates UI (optimistic)
  - Clears input
  - Shows typing indicator
  - Simulates/calls API
  - Adds AI response

- `_simulate_ai_response()`: Placeholder for API integration
  - Currently just adds sample response
  - Replace with real `api_client.chat_completion()` call

**Keyboard Shortcuts**:
- Ctrl+N: New conversation
- Ctrl+Enter: Send message (delegated to input widget)

**Async Support**:
```python
async def initialize_async(self):
    await self.api_client.initialize()
    is_connected = await self.api_client.check_connection()
```

Called after GTK window activated to set up async components.

---

### 3. Sidebar: `ui/components/sidebar.py`

**Purpose**: Conversation navigation and management

**Key Classes**:

- `ConversationItem(Gtk.Box)`: Single conversation in list
  - Displays title + timestamp
  - Click handler for selection
  - Active state highlighting
  - Methods: `set_active(bool)`

- `Sidebar(Gtk.Box)`: Container for all sidebar elements
  - App header with logo
  - Search bar (SearchEntry)
  - New Chat button (Primary style)
  - Scrollable conversation list
  - Footer with settings + status

**Data Structure**:
```python
self._conversations: dict[id, (item, conversation)]
self._current_active: tuple[id, item]  # Currently selected
self.on_conversation_selected: Callable  # Selection callback
```

**Key Methods**:
- `add_conversation(conv)`: Add to list
  - Creates ConversationItem widget
  - Adds gesture click handler
  - Stores in dict

- `remove_conversation(id)`: Remove from list
  - Finds and removes widget
  - Cleans up dict entry

- `set_active_conversation(id)`: Highlight selected
  - Removes old active class
  - Adds active class to new item
  - Visual: background + border

**Styling Hooks**:
- `.sidebar`: Container styling
- `.sidebar-item`: Conversation item
- `.sidebar-item.active`: Selected state
- `.subtitle`: Timestamp text

---

### 4. Chat Area: `ui/components/chat_area.py`

**Purpose**: Display conversation messages

**Key Class**: `ChatArea(Gtk.Box)`

Vertical layout with:
1. Header (title + model info)
2. Messages container (scrollable)
3. Auto-scroll to latest

**Key Methods**:

- `set_conversation(conv)`: Load conversation
  - Clears existing messages
  - Updates header
  - Iterates through conv.messages
  - Calls add_message() for each
  - Auto-scrolls to bottom

- `add_message(msg, animate=True)`: Add single message
  - Checks if new date (adds separator)
  - Creates MessageBubble widget
  - Appends to messages_box
  - Triggers auto-scroll

- `show_typing_indicator()`: Show "..." animation
  - Creates TypingIndicator widget
  - Appends to messages_box
  - Sets flag to track state

- `hide_typing_indicator()`: Remove animation
  - Removes typing indicator widget
  - Clears flag

- `_add_date_separator(date)`: Visual date divider
  - Creates box with: line | date | line
  - Centered text in gray

- `_scroll_to_bottom()`: Auto-scroll to latest
  - Gets scroll adjustment
  - Sets value to upper - page_size
  - Called via GLib.idle_add()

**Styling Hooks**:
- `.chat-area`: Main container
- `.chat-header`: Title section
- `.messages-container`: Message list
- `.date-separator`: Date dividers

---

### 5. Chat Input: `ui/components/chat_input.py`

**Purpose**: User message composition and sending

**Key Class**: `ChatInput(Gtk.Box)`

Layout:
1. Scrollable text view (auto-expanding)
2. Send button (right-aligned)
3. Status indicator (always visible)

**Key Methods**:

- `get_text()`: Return input content
  - Gets text from buffer
  - Returns as Python string

- `clear()`: Empty the input
  - Sets buffer text to ""
  - Triggers text-change handler
  - Height collapses to minimum

- `focus()`: Move cursor to input
  - Grabs text view focus
  - Ready for typing

- `connect_send(callback)`: Hook send button
  - Connects clicked signal
  - Callback invoked on click

**Auto-Expand Logic**:
- Text view in ScrolledWindow
- set_propagate_natural_height(True)
- set_max_content_height(120)
- Height grows as text added
- Stops at 120px with scrollbar

**Send Button State**:
- Disabled when empty (opacity 0.5)
- Enabled when text present
- Triggered by text-buffer changed signal
- Visual feedback: color change + shadow

**Styling Hooks**:
- `.input-container`: Main box
- `.input-wrapper`: Text + button row
- `.chat-input`: TextView styling
- `.send-button`: Button styling
- `.primary`: Button state
- `.status-text`: Status line

---

### 6. Message Bubble: `ui/components/message_bubble.py`

**Purpose**: Display individual messages

**Key Classes**:

- `MessageBubble(Gtk.Box)`: Single message widget
  - Displays message content
  - Shows timestamp (12-hour format)
  - Left/right alignment based on role
  - Fade-in animation on creation

- `TypingIndicator(Gtk.Box)`: Animated typing dots
  - Three dots, sequential animation
  - Driven by CSS @keyframes
  - Infinite loop, 1.4s duration

**MessageBubble Logic**:
```python
def __init__(self, message: Message):
    # Create outer container
    bubble = Gtk.Box(vertical)
    bubble.set_css_classes(["message-bubble", 
                           "user" or "assistant"])
    
    # Add text label
    text_label = Gtk.Label(message.content)
    text_label.set_selectable(True)  # Copy support
    bubble.append(text_label)
    
    # Add timestamp
    timestamp = Gtk.Label(timestamp_str)
    timestamp.set_css_classes(["message-timestamp"])
    bubble.append(timestamp)
    
    # Add fade-in animation class
    self.add_css_class("fade-in")
```

**Styling**:
- User: `#1E3A5F` bg, right-aligned, 4px right corner
- AI: `#2A1F4D` bg, left-aligned, 3px purple left border, 4px left corner
- Both: 70% max width, box-shadow

---

### 7. Settings Panel: `ui/components/settings_panel.py`

**Purpose**: Model configuration and system prompt editing

**Key Class**: `SettingsPanel(Gtk.Box)`

**Tabs**:
1. **Model Settings**
   - Temperature: Scale 0.0-2.0, default 0.7
   - Max Tokens: Spinner, default 2048
   - Top P: Scale 0.0-1.0, default 0.95
   - Repetition Penalty: Scale 0.0-2.0, default 1.0

2. **System Prompt**
   - Large textarea for custom system prompt
   - Reset to default button
   - Save button

3. **Stats & Info**
   - Connection status (read-only)
   - Model information (read-only)
   - Session token usage (read-only)

**Key Methods**:

- `_show_settings_tab()`: Render settings controls
  - Creates scales and spinners
  - Binds to self for state

- `_show_prompt_tab()`: Render prompt editor
  - Text view with default content
  - Reset/Save buttons

- `_show_stats_tab()`: Render info display
  - Labels with connection info
  - Stats display

- `get_settings()`: Retrieve current values
  - Returns ConversationSettings object
  - Reads slider/spinner values

**Tab Switching**:
```python
self.settings_tab.connect("clicked", self._switch_tabs_settings)
self.prompt_tab.connect("clicked", self._switch_tabs_prompt)
self.stats_tab.connect("clicked", self._switch_tabs_stats)

# Toggle active tab CSS class
self.settings_tab.add_css_class("active")
self.prompt_tab.remove_css_class("active")
```

**Styling Hooks**:
- `.settings-panel`: Main container
- `.settings-tab-bar`: Tab buttons row
- `.settings-tab`: Individual tab button
- `.settings-tab.active`: Selected tab state
- `.section-title`: Group labels

---

## Data Models: `models/message.py`

**Key Classes**:

**MessageRole** (Enum):
```python
USER = "user"          # Human message
ASSISTANT = "assistant"  # AI response
SYSTEM = "system"      # System prompt
```

**Message** (Dataclass):
```python
id: str                         # Unique identifier
role: MessageRole              # Sender role
content: str                   # Message text
timestamp: datetime            # When sent
tokens: int                    # Token count estimate
```

Used for:
- Display in chat area
- Context window for API
- Token counting

**Conversation** (Dataclass):
```python
id: str                        # Unique ID
title: str                     # Display name
messages: list[Message]        # Full history
created_at: datetime           # Creation time
updated_at: datetime           # Last activity
model: str                     # Model used
total_tokens: int              # Cumulative token count
```

Methods:
- `add_message(msg)`: Add to history + update time
- `get_last_message()`: Fetch most recent
- `get_context_window()`: Convert to API format

**ConversationSettings** (Dataclass):
```python
temperature: float       # 0.0-2.0 (default 0.7)
max_tokens: int         # Default 2048
top_p: float           # 0.0-1.0 (default 0.95)
repetition_penalty: float # Default 1.0
system_prompt: str     # Default prompt text
```

Methods:
- `to_dict()`: Convert to API parameters

---

## API Client: `api/__init__.py`

**Key Class**: `LMStudioClient`

**Initialization**:
```python
client = LMStudioClient("http://localhost:1234/v1")
await client.initialize()  # Creates aiohttp session
```

**Key Methods**:

- `async check_connection()`: Test API availability
  - Makes GET request to /v1/models
  - Returns True/False
  - Updates internal _is_connected flag

- `async get_available_models()`: List models
  - Calls /v1/models endpoint
  - Extracts model.id from response
  - Returns list of names

- `async chat_completion(conv, settings)`: Stream response
  - Takes conversation + settings
  - Builds context from conv.get_context_window()
  - Adds system prompt
  - POSTs to /v1/chat/completions
  - Streams response (Server-Sent Events)
  - Yields text chunks
  - Raises LMStudioError on failure

- `async count_tokens(text)`: Estimate token count
  - Approximation: length / 4
  - No tokenizer endpoint in LM Studio
  - Rough but functional

**Error Handling**:
- `LMStudioError`: Base exception
- `ConnectionError`: Cannot reach API
- `asyncio.TimeoutError`: Request timeout

**Protocol Details**:
- Endpoint: OpenAI-compatible v1 API
- Streaming: SSE format with "data: " prefix
- Messages: Standard OpenAI format
- Settings: Passed as top-level keys

---

## Styling: `ui/styles.css`

**Structure**:
1. CSS custom properties (colors, sizes)
2. Global element styles
3. Component-specific classes
4. Animations (@keyframes)
5. Responsive media queries

**Key Styling Techniques**:

**CSS Custom Properties**:
```css
:root {
  --accent-primary: #00D9FF;
  --bg-primary: #0F0F0F;
  --text-primary: #FFFFFF;
  /* ... */
}

button.primary {
  color: var(--accent-primary);
}
```

**Transitions**:
```css
button {
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}

entry:focus {
  border-color: var(--accent-primary);
  /* Smooth 200ms color change */
}
```

**Animations**:
```css
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.fade-in {
  animation: fadeIn 300ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
```

**Media Queries**:
```css
@media (max-width: 1024px) {
  .settings-panel { display: none; }
}

@media (max-width: 768px) {
  .message-bubble { max-width: 85%; }
}
```

**Important Classes**:
- `.sidebar`: Left panel styling
- `.chat-area`: Message area
- `.input-container`: Input box styling
- `.message-bubble.user/assistant`: Message appearance
- `.primary/.secondary`: Button variants
- `.fade-in`: Message animation
- `.typing-indicator`: Animated dots

---

## Constants: `constants.py`

**Organization**:

1. **Colors** (6 groups)
   - Base palette (dark blacks/grays)
   - Accents (cyan, purple, green, etc.)
   - Text hierarchy (primary/secondary/tertiary)
   - Message colors (user/AI backgrounds)

2. **Typography**
   - Font family variables
   - Font size constants
   - Weight names

3. **Spacing**
   - XS-XL spacing values (4-24px)
   - Used consistently throughout

4. **Sizes**
   - Layout dimensions (sidebar 200px, etc.)
   - Component heights/widths
   - Border radius values

5. **Animations**
   - Duration constants (fast/normal/slow: 150/200/300ms)
   - Easing function strings (cubic-bezier)

6. **API**
   - Endpoint default
   - Route paths
   - Timeout values

7. **Defaults**
   - Temperature, tokens, top-p
   - System prompt

**Usage Pattern**:
```python
import constants as C

# Access like:
button.set_size_request(C.BUTTON_HEIGHT, -1)
dialog.set_size_request(C.WINDOW_MIN_WIDTH, C.WINDOW_MIN_HEIGHT)
```

---

## Event Flow

### User Sends Message

```
1. User types in ChatInput textarea
   └─> text-buffer "changed" signal fires
       └─> _on_text_changed()
           └─> send_button.set_sensitive(has_text)

2. User clicks Send button OR presses Ctrl+Enter
   └─> send_button "clicked" signal fires
       └─> _on_send_message(button)
           ├─> get_text() from input
           ├─> Create Message object (role=USER)
           ├─> conversation.add_message(msg)
           ├─> chat_area.add_message(msg)  [Animated fade-in]
           ├─> chat_input.clear()  [Collapses height]
           ├─> chat_input.focus()
           ├─> chat_area.show_typing_indicator()
           └─> GLib.timeout_add(800, _simulate_ai_response)

3. Typing indicator displays animated dots
   └─> CSS @keyframes animation (1.4s loop)

4. AI response simulated or fetched from API
   └─> Create Message object (role=ASSISTANT)
       ├─> conversation.add_message(msg)
       ├─> chat_area.add_message(msg)  [Animated]
       ├─> chat_area.hide_typing_indicator()
       └─> Auto-scroll to bottom
```

### Conversation Selection

```
1. User clicks conversation in sidebar
   └─> ConversationItem gesture handler fires
       └─> on_conversation_selected callback
           └─> _on_conversation_selected(conv)
               ├─> sidebar.set_active_conversation(conv.id)
               └─> _load_conversation(conv.id)
                   ├─> fetch from self.conversations
                   ├─> chat_area.set_conversation(conv)
                   │   ├─> Clear existing widgets
                   │   ├─> Update header
                   │   ├─> add_message() for each in conv.messages
                   │   └─> _scroll_to_bottom()
                   └─> chat_input.focus()
```

### Settings Panel Toggle

```
1. User clicks settings icon (in header)
   └─> Toggle settings panel visibility
       ├─> If hidden: Slide in from right (300ms)
       │   └─> Panel.add_css_class("panel-slide")
       └─> If shown: Slide out to right (300ms)
           └─> Panel.remove_css_class("panel-slide")

2. User interacts with settings
   └─> Slider/spinner value changes
       └─> Internal state updated
       └─> No immediate API call (save required in future)

3. User closes settings
   └─> Click X button or press Esc
       └─> Panel slides out
       └─> Chat area expands
```

---

## Performance Considerations

### GPU Acceleration
- CSS animations use `will-change: opacity, transform`
- GPU renders all transitions
- No janky main-thread blocking

### Memory Management
- Conversations stored in dict for O(1) lookup
- Message widgets created on-demand (no pre-rendering)
- Unused widgets removed after conversation switch
- No memory leaks from event handlers (properly disconnected)

### Rendering Optimization
- ScrolledWindow clips content (doesn't render off-screen)
- Flex layouts recompute only on size change
- CSS values cached by GTK
- Minimal forced redraws

### Async Operations
- LM Studio API calls don't block UI
- Event loop integration via asyncio + GLib
- Timeout for API requests (60 seconds)
- Connection check async

---

## Design Decisions & Rationale

### Why GTK4?
- Native appearance on Linux
- Hardware-accelerated rendering
- Modern CSS-based theming
- Python bindings (PyGObject) mature and stable
- Active development and community

### Why Three-Panel Layout?
- Sidebar for navigation (common UX pattern)
- Center for primary content (focus area)
- Settings on right (optional, doesn't clutter)
- Responsive: panels collapse/reorder on smaller screens

### Why Separated Components?
- Maintainability: Each widget has single responsibility
- Reusability: Components can be extracted to other projects
- Testability: UI logic isolated from GTK
- Scalability: Easy to add new components

### Why Async for API?
- Non-blocking API calls preserve UI responsiveness
- Streaming responses update UI incrementally
- Event loop integration via GLib
- Futures-based API (standard Python pattern)

### Why CSS for Animations?
- GPU accelerated (vs. imperative GObject animations)
- Smooth 60fps guaranteed
- Declarative and readable
- Easy to adjust timing/easing

### Why Fake Sample Data?
- App works without LM Studio running
- Allows testing UI before API integration
- Reduces dependencies for development
- Visual verification of animations

---

## Extension Points

### Adding New Components

**1. Create new widget class**:
```python
class MyComponent(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_css_classes(["my-component"])
        # Create child widgets
```

**2. Add CSS styling**:
```css
.my-component {
  background-color: var(--bg-secondary);
  padding: 16px;
}
```

**3. Integrate into main window**:
```python
# In MainWindow.__init__
self.my_component = MyComponent()
main_box.append(self.my_component)
```

**4. Connect signals**:
```python
self.my_component.connect("custom-signal", self._on_custom_event)
```

### Adding New API Endpoints

**1. Add method to LMStudioClient**:
```python
async def new_endpoint(self, param):
    async with self.session.get(...) as resp:
        return await resp.json()
```

**2. Call from main window**:
```python
result = await self.api_client.new_endpoint(param)
```

### Adding New Settings

**1. Add field to ConversationSettings**:
```python
@dataclass
class ConversationSettings:
    new_param: float = 0.5
```

**2. Add UI control in SettingsPanel**:
```python
self.new_param_scale = Gtk.Scale(...)
self.new_param_scale.set_value(C.DEFAULT_NEW_PARAM)
```

**3. Update retrieval**:
```python
def get_settings(self):
    return ConversationSettings(
        # ...
        new_param=self.new_param_scale.get_value(),
    )
```

---

This architecture supports both rapid development and long-term maintainability.
