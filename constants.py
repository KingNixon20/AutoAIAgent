"""
Color palette and design constants for AutoAIAgent UI.
"""

# Dark Base Palette
COLOR_BG_PRIMARY = "#0F0F0F"      # Deep black
COLOR_BG_SECONDARY = "#1A1A1A"    # Charcoal
COLOR_BG_TERTIARY = "#242424"     # Light charcoal
COLOR_SURFACE_OVERLAY = "#2D2D2D" # Semi-transparent overlay

# Accent Colors
COLOR_ACCENT_PRIMARY = "#00D9FF"   # Bright cyan/teal
COLOR_ACCENT_SECONDARY = "#7C5DFF" # Vibrant purple
COLOR_SUCCESS = "#00E676"          # Soft green
COLOR_WARNING = "#FFA726"          # Amber
COLOR_ERROR = "#FF5252"            # Red

# Text Colors
COLOR_TEXT_PRIMARY = "#FFFFFF"     # Pure white
COLOR_TEXT_SECONDARY = "#B0B0B0"   # Light gray
COLOR_TEXT_TERTIARY = "#757575"    # Medium gray
COLOR_BORDER = "#404040"           # Dark gray border

# Message Bubbles
COLOR_USER_MESSAGE_BG = "#1E3A5F"  # Deep blue
COLOR_AI_MESSAGE_BG = "#2A1F4D"    # Purple tint

# Typography
FONT_FAMILY_BODY = "Inter, sans-serif"
FONT_FAMILY_MONO = "JetBrains Mono, monospace"

FONT_SIZE_H1 = 18
FONT_SIZE_H2 = 16
FONT_SIZE_H3 = 14
FONT_SIZE_BODY = 13
FONT_SIZE_CAPTION = 11
FONT_SIZE_MONO = 12

# Spacing
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24

# Sizes
SIDEBAR_WIDTH = 240
SETTINGS_PANEL_WIDTH = 420
CHAT_MAX_WIDTH = 900  # Max width for message area

BUTTON_HEIGHT = 44
INPUT_HEIGHT = 48
INPUT_MAX_HEIGHT = 120

# Rounded corners
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_FULL = 24  # For message bubbles with one side sharp

# Animations (in milliseeconds)
ANIM_FAST = 150
ANIM_NORMAL = 200
ANIM_SLOW = 300

# Easing functions (cubic-bezier values)
EASING_SMOOTH = "0.4, 0, 0.2, 1"
EASING_BOUNCE = "0.34, 1.56, 0.64, 1"
EASING_IN_OUT = "0.4, 0.0, 0.2, 1.0"

# Z-indexes (not directly used in GTK but useful for layering concepts)
Z_BASE = 0
Z_OVERLAY = 100
Z_MODAL = 1000

# Layout dimensions
WINDOW_MIN_WIDTH = 600
WINDOW_MIN_HEIGHT = 420
WINDOW_DEFAULT_WIDTH = 960
WINDOW_DEFAULT_HEIGHT = 600
WINDOW_MAX_WIDTH = 2560
WINDOW_MAX_HEIGHT = 1440

# Default ratios for responsive layout
# Fraction of screen to use for default window size (0.0 - 1.0)
# Default window uses 45% of screen to avoid overly large startup windows
WINDOW_DEFAULT_RATIO = 0.45
# Fraction of screen width to allocate to the sidebar by default
DEFAULT_SIDEBAR_RATIO = 0.35
# Fraction of screen width to allocate to the tools panel by default
DEFAULT_TOOLS_PANEL_RATIO = 0.25

# Optional fixed startup window size (pixels). If set, these override the
# responsive WINDOW_DEFAULT_RATIO behavior but are still clamped to min/max.
WINDOW_START_WIDTH = 1390
WINDOW_START_HEIGHT = 740

# Message bubble
MESSAGE_BUBBLE_PADDING = SPACING_MD
MESSAGE_BUBBLE_MAX_WIDTH_RATIO = 0.7

# Sidebar
SIDEBAR_SEARCH_HEIGHT = 50
SIDEBAR_NEW_CHAT_HEIGHT = 44
SIDEBAR_FOOTER_HEIGHT = 52
SIDEBAR_ITEM_HEIGHT = 48

# Chat area
CHAT_HEADER_HEIGHT = 56
CHAT_MESSAGE_SPACING = SPACING_MD
CHAT_AREA_PADDING = SPACING_XL

# Input area
INPUT_AREA_DEPTH = 120

# Typing indicator
TYPING_DOT_SIZE = 8
TYPING_DOT_COLORS = [COLOR_ACCENT_SECONDARY, COLOR_ACCENT_SECONDARY, COLOR_ACCENT_SECONDARY]
TYPING_ANIMATION_DURATION = 1400  # ms
TYPING_DOT_DELAY = 280  # ms between dots

# Context window - models have limits (e.g. 4K, 8K, 32K tokens)
CONTEXT_WINDOW_MAX = 8192
CONTEXT_TRIM_THRESHOLD = 0.85  # Trim when usage exceeds 85% of max
CHARS_PER_TOKEN_EST = 4  # Rough estimate for token counting

# API
API_ENDPOINT_DEFAULT = "http://localhost:1234/v1"
API_CHAT_COMPLETIONS = "/chat/completions"
API_MODELS = "/models"
API_TIMEOUT = 120
API_RECONNECT_INTERVAL = 5000  # ms

# Default settings
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TOP_P = 0.95
DEFAULT_REPETITION_PENALTY = 1.0
DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."
DEFAULT_CONTEXT_LIMIT = 4096  # Max tokens for conversation context
DEFAULT_TOKEN_SAVER = False
