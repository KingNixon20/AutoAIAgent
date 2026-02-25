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
    
    format_type: None (normal), "bold", "italic", "code", "code_block", 
                 "h1", "h2", "h3", "list_item", "blockquote"
    """
    segments = []
    lines = text.split('\n')
    
    in_code_block = False
    current_code_block_content = []

    for line_num, line in enumerate(lines):
        # Handle code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                segments.append(("\n".join(current_code_block_content), "code_block"))
                current_code_block_content = []
                in_code_block = False
            else:
                in_code_block = True
            # Add a newline for block separation
            if line_num < len(lines) - 1 or segments and segments[-1][1] != "code_block":
                 segments.append(("\n", None))
            continue
        
        if in_code_block:
            current_code_block_content.append(line)
            continue

        # Handle block-level elements (headings, blockquotes, list items)
        # These should start a new line and consume the whole line
        if line.startswith("# "):
            segments.append((line[2:], "h1"))
            segments.append(("\n", None))
            continue
        if line.startswith("## "):
            segments.append((line[3:], "h2"))
            segments.append(("\n", None))
            continue
        if line.startswith("### "):
            segments.append((line[4:], "h3"))
            segments.append(("\n", None))
            continue
        if line.startswith("> "):
            segments.append((line[2:], "blockquote"))
            segments.append(("\n", None))
            continue
        if line.startswith("* ") or line.startswith("- "):
            segments.append(("\u2022 " + line[2:], "list_item"))
            segments.append(("\n", None))
            continue

        # Process inline elements for normal lines
        i = 0
        line_segments = []
        while i < len(line):
            # Inline code (`...`) - handle before bold/italic to prevent issues with `**` inside code
            if line[i] == '`' and (i == 0 or line[i-1] != '\\'): # Ensure it's not an escaped backtick
                end = -1
                for j in range(i + 1, len(line)):
                    if line[j] == '`' and (j == 0 or line[j-1] != '\\'):
                        end = j
                        break
                if end != -1:
                    line_segments.append((line[i+1:end], "code"))
                    i = end + 1
                    continue
            
            # Bold (**text** or __text__)
            if line[i:i+2] == "**":
                end = line.find("**", i + 2)
                if end != -1:
                    line_segments.append((line[i+2:end], "bold"))
                    i = end + 2
                    continue
            if line[i:i+2] == "__":
                end = line.find("__", i + 2)
                if end != -1:
                    line_segments.append((line[i+2:end], "bold"))
                    i = end + 2
                    continue
            
            # Italic (*text* or _text_)
            if line[i] == "*" and (i == 0 or line[i-1] != '\\'):
                end = -1
                for j in range(i + 1, len(line)):
                    if line[j] == '*' and (j == 0 or line[j-1] != '\\'):
                        if line[j-1:j+1] != "**": # Avoid matching **
                            end = j
                            break
                if end != -1:
                    line_segments.append((line[i+1:end], "italic"))
                    i = end + 1
                    continue
            if line[i] == "_" and (i == 0 or line[i-1] != '\\'):
                end = -1
                for j in range(i + 1, len(line)):
                    if line[j] == '_' and (j == 0 or line[j-1] != '\\'):
                        if line[j-1:j+1] != "__": # Avoid matching __
                            end = j
                            break
                if end != -1:
                    line_segments.append((line[i+1:end], "italic"))
                    i = end + 1
                    continue
            
            # Normal text - find next special char
            next_inline_token_pos = len(line)
            for delim in ("`", "**", "__", "*", "_"):
                idx = line.find(delim, i)
                if idx != -1:
                    next_inline_token_pos = min(next_inline_token_pos, idx)
            
            if next_inline_token_pos > i:
                line_segments.append((line[i:next_inline_token_pos], None))
                i = next_inline_token_pos
            else:
                line_segments.append((line[i], None))
                i += 1
        
        segments.extend(line_segments)
        # Add newline after each line unless it's the last line and empty or already handled by block elements
        if line_num < len(lines) - 1 or line: # Only add newline if not last line OR last line is not empty
            segments.append(("\n", None))

    # Add any remaining code block content if the file ended unexpectedly
    if in_code_block and current_code_block_content:
        segments.append(("\n".join(current_code_block_content), "code_block"))
    
    return segments


def _create_text_tags(table: Gtk.TextTagTable) -> dict[str, Gtk.TextTag]:
    """Create and register text tags for markdown formatting."""
    tags = {}
    
    # Bold
    tag = Gtk.TextTag(name="bold")
    table.add(tag)
    tags["bold"] = tag
    
    # Italic
    tag = Gtk.TextTag(name="italic")
    table.add(tag)
    tags["italic"] = tag
    
    # Inline code
    tag = Gtk.TextTag(name="code")
    table.add(tag)
    tags["code"] = tag
    
    # Code block
    tag = Gtk.TextTag(name="code_block")
    table.add(tag)
    tags["code_block"] = tag

    # Headings
    tag = Gtk.TextTag(name="h1")
    table.add(tag)
    tags["h1"] = tag

    tag = Gtk.TextTag(name="h2")
    table.add(tag)
    tags["h2"] = tag

    tag = Gtk.TextTag(name="h3")
    table.add(tag)
    tags["h3"] = tag

    # Blockquote
    tag = Gtk.TextTag(name="blockquote")
    table.add(tag)
    tags["blockquote"] = tag

    # List item
    tag = Gtk.TextTag(name="list_item")
    table.add(tag)
    tags["list_item"] = tag
    
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
        if not text and fmt is None: # Skip empty normal text segments
            continue
        
        # Insert text and apply tag
        if fmt:
            buffer.insert_with_tags_by_name(it, text, fmt)
        else:
            buffer.insert(it, text)
    
    view = ClampedTextView(buffer=buffer, max_width=max_width)
    view.get_style_context().add_class('markdown-view')
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
    # Allow flexible width up to max_width, not a hard requirement
    # Use -1 for width to let parent container control width, but max_width for clamping
    view.set_size_request(-1, -1)
    view.set_hexpand(True)
    view.set_halign(Gtk.Align.FILL)
    # Transparent background - inherits from parent bubble
    view.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 0))
    view.override_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(1, 1, 1, 1))
    
    return view
