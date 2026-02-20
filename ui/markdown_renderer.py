"""
Markdown-to-GTK rendering for AI response formatting.
Supports: **bold**, *italic*, `inline code`, ```code blocks```.
Also parses thinking (<think>...</think>) vs response for ChatGPT/DeepSeek-style display.
"""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango


def split_thinking_and_response(content: str) -> tuple[str, str]:
    """Split content into thinking and response based on <think></think> tags.
    
    Models like DeepSeek and o1 output: <think>reasoning</think> actual response
    
    Returns:
        (thinking, response) - either may be empty.
    """
    think_open = "<think>"
    think_close = "</think>"
    if think_open not in content:
        return ("", content)
    start = content.find(think_open)
    if start == -1:
        return ("", content)
    start += len(think_open)
    end = content.find(think_close, start)
    if end == -1:
        # Unclosed tag - treat rest as thinking
        return (content[start:].strip(), "")
    thinking = content[start:end].strip()
    response = content[end + len(think_close):].strip()
    return (thinking, response)


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


def build_formatted_text_view(content: str) -> Gtk.TextView:
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
    
    view = Gtk.TextView(buffer=buffer)
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD)
    view.set_left_margin(4)
    view.set_right_margin(4)
    view.set_top_margin(4)
    view.set_bottom_margin(4)
    view.set_pixels_above_lines(2)
    view.set_pixels_below_lines(2)
    # Transparent background - inherits from parent bubble
    view.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 0))
    view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
    
    return view
