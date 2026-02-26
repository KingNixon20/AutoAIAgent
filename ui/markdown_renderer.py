"""
Markdown-to-GTK rendering for AI response formatting.
Supports full markdown (via mistune) and collapsible thinking sections.
"""
import re
import json
import gi
import mistune
from typing import Optional, Tuple, List

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango, GLib


class ClampedTextView(Gtk.TextView):
    """TextView that caps preferred width to avoid oversized Wayland surfaces."""

    def __init__(self, max_width: int = 360, **kwargs):
        super().__init__(**kwargs)
        self._max_width = max(120, int(max_width))

    def do_get_preferred_width(self):
        minimum, natural = Gtk.TextView.do_get_preferred_width(self)
        cap = self._max_width
        return (min(minimum, cap), min(natural, cap))

    def do_get_preferred_width_for_height(self, height):
        minimum, natural = Gtk.TextView.do_get_preferred_width_for_height(self, height)
        cap = self._max_width
        return (min(minimum, cap), min(natural, cap))


def split_thinking_and_response(content: str) -> Tuple[str, str]:
    """Split model output into reasoning/thinking and final response text.

    Handles variants commonly seen in model output:
    - <think>...</think>
    - <thinking>...</thinking>
    - <reasoning>...</reasoning>
    - <analysis>...</analysis>
    - tags with attributes and different letter case
    - HTML-escaped tags (&lt;think&gt;...&lt;/think&gt;)
    - unclosed opening reasoning tags (treat rest as thinking)
    """
    if not content:
        return ("", "")

    text = (
        content.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )

    tag_names = r"think|thinking|reasoning|analysis"
    block_pattern = re.compile(
        rf"<(?P<tag>{tag_names})(?:\s[^>]*)?>(?P<body>.*?)</(?P=tag)\s*>",
        re.IGNORECASE | re.DOTALL,
    )

    thinking_parts: List[str] = []

    def _collect_and_strip(match: re.Match) -> str:
        body = (match.group("body") or "").strip()
        if body:
            thinking_parts.append(body)
        return ""

    response = block_pattern.sub(_collect_and_strip, text)

    # Handle unclosed thinking tag variants, e.g. "<think>...<no close>"
    unclosed_pattern = re.compile(
        rf"<(?P<tag>{tag_names})(?:\s[^>]*)?>",
        re.IGNORECASE,
    )
    unclosed = unclosed_pattern.search(response)
    if unclosed:
        tail = response[unclosed.end():].strip()
        if tail:
            thinking_parts.append(tail)
        response = response[:unclosed.start()].strip()
    else:
        response = response.strip()

    thinking = "\n\n".join(part for part in thinking_parts if part).strip()
    return (thinking, response)


def extract_ai_tasks_and_response(content: str) -> Tuple[List[dict], str]:
    """Extract <ai_tasks> (or <aitasks>) block and return (tasks, remaining_response)."""
    if not content:
        return ([], "")

    text = (
        content.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )

    block_pattern = re.compile(
        r"<(?P<tag>ai_tasks|aitasks)(?:\s[^>]*)?>(?P<body>.*?)</(?P=tag)\s*>",
        re.IGNORECASE | re.DOTALL,
    )

    task_blocks: List[str] = []

    def _collect_and_strip(match: re.Match) -> str:
        body = (match.group("body") or "").strip()
        if body:
            task_blocks.append(body)
        return ""

    response = block_pattern.sub(_collect_and_strip, text).strip()
    if not task_blocks:
        return ([], response)

    tasks: List[dict] = []
    seen = set()
    for block in task_blocks:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Markdown checkbox list: - [ ] task / - [x] task
            m = re.match(r"^[-*]\s*\[(?P<done>[ xX])\]\s+(?P<text>.+)$", line)
            if m:
                task_text = m.group("text").strip()
                key = task_text.lower()
                if task_text and key not in seen:
                    seen.add(key)
                    tasks.append(
                        {
                            "text": task_text,
                            "done": m.group("done").lower() == "x",
                        }
                    )
                continue
            # Fallback: numbered/bulleted line
            m2 = re.match(r"^(?:\d+[.)]|[-*])\s+(?P<text>.+)$", line)
            if m2:
                task_text = m2.group("text").strip()
                key = task_text.lower()
                if task_text and key not in seen:
                    seen.add(key)
                    tasks.append({"text": task_text, "done": False})

    return (tasks, response)


def _create_text_tags(table: Gtk.TextTagTable) -> dict[str, Gtk.TextTag]:
    """Create and register text tags for markdown formatting."""
    tags = {}

    # Bold
    tag = Gtk.TextTag(name="bold")
    tag.set_property("weight", Pango.Weight.BOLD)
    table.add(tag)
    tags["bold"] = tag

    # Italic
    tag = Gtk.TextTag(name="italic")
    tag.set_property("style", Pango.Style.ITALIC)
    table.add(tag)
    tags["italic"] = tag

    # Inline code
    tag = Gtk.TextTag(name="code")
    tag.set_property("font", "Monospace 10")
    tag.set_property("foreground", "#f8f8f2")
    tag.set_property("background", "#2d2d2d")
    tag.set_property("scale", 0.9)
    table.add(tag)
    tags["code"] = tag

    # Code block
    tag = Gtk.TextTag(name="code_block")
    tag.set_property("font", "Monospace 10")
    tag.set_property("foreground", "#d4d4d4")
    tag.set_property("background", "#1e1e1e")
    tag.set_property("scale", 0.9)
    tag.set_property("left-margin", 12)
    tag.set_property("right-margin", 12)
    tag.set_property("pixels-above-lines", 4)
    tag.set_property("pixels-below-lines", 4)
    table.add(tag)
    tags["code_block"] = tag

    # Headings
    for level, size in [(1, 1.8), (2, 1.5), (3, 1.3)]:
        name = f"h{level}"
        tag = Gtk.TextTag(name=name)
        tag.set_property("weight", Pango.Weight.BOLD)
        tag.set_property("scale", size)
        tag.set_property("pixels-above-lines", 8)
        tag.set_property("pixels-below-lines", 2)
        table.add(tag)
        tags[name] = tag

    # Blockquote
    tag = Gtk.TextTag(name="blockquote")
    tag.set_property("style", Pango.Style.ITALIC)
    tag.set_property("background", "#3a3a3a")
    tag.set_property("left-margin", 24)
    tag.set_property("right-margin", 12)
    tag.set_property("pixels-above-lines", 4)
    tag.set_property("pixels-below-lines", 4)
    table.add(tag)
    tags["blockquote"] = tag

    # List item (used with bullet prefix)
    tag = Gtk.TextTag(name="list_item")
    tag.set_property("left-margin", 24)
    tag.set_property("pixels-below-lines", 2)
    table.add(tag)
    tags["list_item"] = tag

    # Link
    tag = Gtk.TextTag(name="link")
    tag.set_property("foreground", "#1e90ff")
    tag.set_property("underline", Pango.Underline.SINGLE)
    tag.set_property("underline-rgba", Gdk.RGBA(0.12, 0.56, 1.0, 1.0))
    table.add(tag)
    tags["link"] = tag

    return tags


class GtkMarkdownRenderer(mistune.HTMLRenderer):
    """Custom mistune renderer that outputs directly to a GtkTextBuffer."""

    def __init__(self, buffer: Gtk.TextBuffer, tags: dict):
        super().__init__()
        self.buffer = buffer
        self.tags = tags
        self.iter = buffer.get_end_iter()
        self.list_level = 0
        self.in_blockquote = False

    def text(self, text):
        self.buffer.insert(self.iter, text)
        return text

    def emphasis(self, text):
        self.buffer.insert_with_tags_by_name(self.iter, text, "italic")
        return text

    def strong(self, text):
        self.buffer.insert_with_tags_by_name(self.iter, text, "bold")
        return text

    def link(self, link, text=None, title=None):
        # Insert the link text with the link tag
        display_text = text or link
        self.buffer.insert_with_tags_by_name(self.iter, display_text, "link")
        # Store the URL in a data attribute on the tag's range (for click handling)
        # We'll store it in a separate dict keyed by the start offset
        start_offset = self.iter.get_offset() - len(display_text)
        end_offset = self.iter.get_offset()
        self.buffer.set_data(f"link_{start_offset}_{end_offset}", link)
        return ""

    def codespan(self, text):
        self.buffer.insert_with_tags_by_name(self.iter, text, "code")
        return text

    def block_code(self, code, info=None):
        # Insert a copy button + code block
        # We'll create a custom widget: a Gtk.Box with a copy button and a TextView for the code.
        # But since we're inside a renderer that expects to write to a buffer, we'll instead
        # insert a placeholder marker and later replace it with the widget.
        # For simplicity, we'll just insert the code with the code_block tag.
        # If you want a copy button, you'll need to restructure the message container.
        # We'll leave that as a future enhancement; for now just use code_block tag.
        self.buffer.insert(self.iter, code)
        # Apply code_block tag to the whole block
        end_iter = self.buffer.get_end_iter()
        start_iter = self.buffer.get_iter_at_offset(self.iter.get_offset() - len(code))
        self.buffer.apply_tag(self.tags["code_block"], start_iter, end_iter)
        self.buffer.insert(self.iter, "\n")
        return ""

    def block_quote(self, text):
        self.in_blockquote = True
        self.buffer.insert(self.iter, text)
        # Apply blockquote tag to the whole block
        end_iter = self.buffer.get_end_iter()
        start_iter = self.buffer.get_iter_at_offset(self.iter.get_offset() - len(text))
        self.buffer.apply_tag(self.tags["blockquote"], start_iter, end_iter)
        self.in_blockquote = False
        return ""

    def heading(self, text, level):
        level = min(level, 3)  # Only h1-h3 supported
        tag_name = f"h{level}"
        self.buffer.insert_with_tags_by_name(self.iter, text + "\n", tag_name)
        return text

    def list(self, text, ordered, level, start=None):
        # The list marker is handled by list_item
        self.buffer.insert(self.iter, text)
        return text

    def list_item(self, text, level):
        # Prepend bullet/number marker
        marker = "• " if level == 1 else "  • "
        self.buffer.insert_with_tags_by_name(self.iter, marker + text, "list_item")
        self.buffer.insert(self.iter, "\n")
        return ""

    def thematic_break(self):
        self.buffer.insert(self.iter, "—\n")
        return ""

    def linebreak(self):
        self.buffer.insert(self.iter, "\n")
        return ""

    def softbreak(self):
        self.buffer.insert(self.iter, " ")
        return ""


def build_formatted_text_view(content: str, max_width: int = 360) -> Gtk.Widget:
    """Build a widget with markdown formatting applied.

    If content contains a <think> section, returns a Gtk.Box with an expander
    for thinking and a TextView for the response. Otherwise returns a single
    TextView with the whole content.

    Args:
        content: Raw message content (may contain markdown and thinking tags).
        max_width: Maximum width for text wrapping (clamped).

    Returns:
        Gtk.Widget (either Gtk.TextView or Gtk.Box) with formatted content.
    """
    # First extract thinking and response
    thinking, response = split_thinking_and_response(content)

    # Helper to render markdown into a TextView
    def render_to_textview(text: str) -> Gtk.TextView:
        buffer = Gtk.TextBuffer()
        tags = _create_text_tags(buffer.get_tag_table())

        if text.strip():
            # Use mistune to parse and render
            renderer = GtkMarkdownRenderer(buffer, tags)
            markdown = mistune.create_markdown(renderer=renderer)
            markdown(text)

        view = ClampedTextView(buffer=buffer, max_width=max_width)
        view.get_style_context().add_class('markdown-view')
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(4)
        view.set_right_margin(4)
        view.set_top_margin(4)
        view.set_bottom_margin(4)
        view.set_pixels_above_lines(2)
        view.set_pixels_below_lines(2)
        view.set_hexpand(True)
        view.set_halign(Gtk.Align.FILL)
        # Transparent background - inherits from parent bubble
        view.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 0))
        view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))

        # Connect link clicks
        view.connect("event", _on_text_view_event, buffer)
        return view

    # Build the final widget
    if thinking and response:
        # Create container
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Thinking expander
        expander = Gtk.Expander(label="💭 Reasoning (click to expand)")
        expander.set_use_markup(True)
        expander.set_expanded(False)  # Collapsed by default

        thinking_view = render_to_textview(thinking)
        thinking_view.set_size_request(max_width, -1)
        expander.add(thinking_view)

        box.pack_start(expander, False, False, 0)

        # Response view
        response_view = render_to_textview(response)
        box.pack_start(response_view, True, True, 0)

        box.show_all()
        return box
    else:
        # Only response or only thinking (rare)
        return render_to_textview(content)


def _on_text_view_event(view: Gtk.TextView, event: Gdk.Event, buffer: Gtk.TextBuffer) -> bool:
    """Handle button clicks on the TextView to open links."""
    if event.type != Gdk.EventType.BUTTON_RELEASE or event.button != 1:
        return False

    # Get coordinates and resolve to text position
    x, y = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
    iter_pos = view.get_iter_at_location(x, y)
    if not iter_pos:
        return False

    # Check if the position has the link tag
    tags_at_cursor = iter_pos.get_tags()
    for tag in tags_at_cursor:
        if tag.get_property("name") == "link":
            # Find the whole range of the link tag
            start = iter_pos.copy()
            end = iter_pos.copy()
            start.backward_to_tag_toggle(tag)
            end.forward_to_tag_toggle(tag)
            # Ensure we have the full range
            if not start.starts_tag(tag):
                start.forward_to_tag_toggle(tag)
            if not end.ends_tag(tag):
                end.backward_to_tag_toggle(tag)
            url = buffer.get_text(start, end, False).strip()
            if url:
                Gtk.show_uri_on_window(None, url, Gdk.CURRENT_TIME)
                return True
    return False