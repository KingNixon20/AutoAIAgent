"""
Markdown-to-GTK rendering for AI response formatting.
Supports: **bold**, *italic*, `inline code`, ```code blocks```.
Also parses thinking (<think>...</think>) vs response for ChatGPT/DeepSeek-style display.
"""
import re
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango


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


def split_thinking_and_response(content: str) -> tuple[str, str]:
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

    thinking_parts: list[str] = []

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


def extract_ai_tasks_and_response(content: str) -> tuple[list[dict], str]:
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

    task_blocks: list[str] = []

    def _collect_and_strip(match: re.Match) -> str:
        body = (match.group("body") or "").strip()
        if body:
            task_blocks.append(body)
        return ""

    response = block_pattern.sub(_collect_and_strip, text).strip()
    if not task_blocks:
        return ([], response)

    tasks: list[dict] = []
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


def _parse_markdown_segments(text: str) -> list[tuple[str, str | None]]:
    """Parse markdown and return list of (content, format_type) segments.
    
    format_type: None (normal), "bold", "italic", "code", "code_block"
    """
    segments = []
    i = 0
    
    while i < len(text):
        # Code block (```...```)
        if text[i:i+3] == "```":
            end = text.find("```", i + 3)
            if end == -1:
                segments.append((text[i:], None))
                break
            code_content = text[i+3:end].strip()
            segments.append((code_content, "code_block"))
            i = end + 3
            continue
        
        # Inline code (`...`) - single backtick
        if text[i] == "`" and (i + 2 >= len(text) or text[i:i+3] != "```"):
            end = text.find("`", i + 1)
            if end != -1:
                segments.append((text[i+1:end], "code"))
                i = end + 1
                continue
        
        # Bold (**text** or __text__)
        if text[i:i+2] in ("**", "__"):
            delim = text[i:i+2]
            end = text.find(delim, i + 2)
            if end != -1:
                segments.append((text[i+2:end], "bold"))
                i = end + 2
                continue
        
        # Italic (*text* or _text_) - must not be ** or __
        if text[i] in "*_" and text[i:i+2] not in ("**", "__"):
            end = text.find(text[i], i + 1)
            if end != -1:
                segments.append((text[i+1:end], "italic"))
                i = end + 1
                continue
        
        # Normal text - find next special char
        next_pos = len(text)
        idx = text.find("```", i)
        if idx != -1:
            next_pos = min(next_pos, idx)
        idx = text.find("`", i)
        if idx != -1 and text[idx:idx+3] != "```":
            next_pos = min(next_pos, idx)
        for delim in ("**", "__"):
            idx = text.find(delim, i)
            if idx != -1:
                next_pos = min(next_pos, idx)
        for delim in ("*", "_"):
            idx = text.find(delim, i)
            if idx != -1 and idx < next_pos and text[idx:idx+2] not in ("**", "__"):
                next_pos = min(next_pos, idx)
        
        if next_pos > i:
            segments.append((text[i:next_pos], None))
            i = next_pos
        else:
            segments.append((text[i], None))
            i += 1
    
    return segments


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
    tag.set_property("font", "Monospace 12")
    tag.set_property("background", "#2a2a2a")
    tag.set_property("foreground", "#e0e0e0")
    table.add(tag)
    tags["code"] = tag
    
    # Code block
    tag = Gtk.TextTag(name="code_block")
    tag.set_property("font", "Monospace 12")
    tag.set_property("background", "#1e1e1e")
    tag.set_property("foreground", "#d4d4d4")
    tag.set_property("indent", 8)
    tag.set_property("left-margin", 12)
    tag.set_property("right-margin", 12)
    table.add(tag)
    tags["code_block"] = tag
    
    return tags


def build_formatted_text_view(content: str, max_width: int = 360) -> Gtk.TextView:
    """Build a Gtk.TextView with markdown formatting applied.
    
    Args:
        content: Raw message content (may contain markdown).
        
    Returns:
        Configured Gtk.TextView with formatted content.
    """
    buffer = Gtk.TextBuffer()
    tags = _create_text_tags(buffer.get_tag_table())
    
    segments = _parse_markdown_segments(content)
    it = buffer.get_start_iter()
    
    for text, fmt in segments:
        if not text:
            continue
        if fmt == "code_block":
            buffer.insert(it, "\n")
            buffer.insert_with_tags_by_name(it, text, "code_block")
            buffer.insert(it, "\n")
        elif fmt:
            buffer.insert_with_tags_by_name(it, text, fmt)
        else:
            buffer.insert(it, text)
    
    view = ClampedTextView(buffer=buffer, max_width=max_width)
    view.set_editable(False)
    view.set_cursor_visible(False)
    # WORD_CHAR prevents extremely long unbroken tokens (URLs/JSON/base64)
    # from requesting absurd widths that can crash Wayland/GDK surfaces.
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(4)
    view.set_right_margin(4)
    view.set_top_margin(4)
    view.set_bottom_margin(4)
    view.set_pixels_above_lines(2)
    view.set_pixels_below_lines(2)
    # Enforce a practical max width so natural size cannot explode on Wayland.
    view.set_size_request(max_width, -1)
    view.set_hexpand(False)
    view.set_halign(Gtk.Align.FILL)
    # Transparent background - inherits from parent bubble
    view.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 0))
    view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
    
    return view
