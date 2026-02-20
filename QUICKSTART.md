# Quick Start Guide

Get AutoAI Chat Client running in 5 minutes.

## 1. Install Dependencies

### Linux (Ubuntu/Debian)
```bash
sudo apt-get install libgtk-4-dev libgobject-introspection-dev libcairo2-dev
pip install -r requirements.txt
```

### Linux (Fedora/RHEL)
```bash
sudo dnf install gtk4-devel gobject-introspection-devel cairo-devel
pip install -r requirements.txt
```

### macOS
```bash
brew install gtk4 gobject-introspection
pip install -r requirements.txt
```

### Windows
GTK4 support is limited on Windows. Consider using WSL:
```bash
# In WSL Ubuntu terminal
sudo apt-get install libgtk-4-dev libgobject-introspection-dev
pip install -r requirements.txt
```

## 2. Run the Application

```bash
python main.py
```

## 3. Test the UI

The app starts with two sample conversations:

1. **Python Async Patterns** - Shows message display
2. **GTK4 UI Design** - Shows multi-message conversations

Click on any conversation to load it. Try:
- Typing a message and clicking Send (or Ctrl+Enter)
- Creating a new conversation (click "+ New Chat")
- Searching conversations (type in search bar)
- Adjusting settings (click settings icon - not visually apparent yet)

## 4. Connect to LM Studio (Optional)

If you have LM Studio running:

1. Start LM Studio locally on `http://localhost:1234`
2. Load a model (e.g., Llama 2)
3. Real chat responses will stream into the app

Current version shows simulated responses. Full integration coming soon.

## 5. Customize Colors

Edit `constants.py`:

```python
# Change primary accent
COLOR_ACCENT_PRIMARY = "#00D9FF"    # Cyan
COLOR_ACCENT_PRIMARY = "#00FF00"    # Green
COLOR_ACCENT_PRIMARY = "#FF00FF"    # Magenta

# Change theme tone
COLOR_BG_PRIMARY = "#0F0F0F"        # Darker
COLOR_BG_PRIMARY = "#1A1A1A"        # Lighter
```

Restart the app to see changes.

## 6. Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | New conversation |
| `Ctrl+Enter` | Send message |
| `Esc` | Close settings panel |

## 7. File Structure

```
AutoAIAgent/
├── main.py           ← Start here
├── constants.py      ← Customize colors/sizes
├── ui/styles.css     ← Styling
├── ui/main_window.py ← Main window logic
└── ui/components/    ← UI widgets
```

## 8. Next Steps

### Want to customize further?

**Colors** → Edit [constants.py](constants.py)

**Layout** → Edit [ui/main_window.py](ui/main_window.py)

**Styling** → Edit [ui/styles.css](ui/styles.css)

**Components** → Edit [ui/components/](ui/components/)

### Want to add features?

1. **New sidebar features** → Edit [ui/components/sidebar.py](ui/components/sidebar.py)
2. **New input features** → Edit [ui/components/chat_input.py](ui/components/chat_input.py)
3. **New message types** → Edit [ui/components/message_bubble.py](ui/components/message_bubble.py)
4. **New API methods** → Edit [api/__init__.py](api/__init__.py)

### Want to integrate real API?

In [ui/main_window.py](ui/main_window.py), find `_simulate_ai_response()` and replace with:

```python
async def _get_real_ai_response(self) -> None:
    """Get real response from LM Studio."""
    if not self.current_conversation:
        return
    
    try:
        # Stream response
        full_response = ""
        async for chunk in self.api_client.chat_completion(
            self.current_conversation,
            self.settings
        ):
            full_response += chunk
            # Update UI with partial response
            # (Advanced: requires async/await integration)
        
        # Add complete message
        ai_msg = Message(
            id=str(uuid.uuid4()),
            role=MessageRole.ASSISTANT,
            content=full_response,
        )
        self.current_conversation.add_message(ai_msg)
        self.chat_area.add_message(ai_msg)
        
    except Exception as e:
        print(f"Error getting response: {e}")
    finally:
        self.chat_area.hide_typing_indicator()
```

## 9. Troubleshooting

### "ModuleNotFoundError: No module named 'gi'"
```bash
pip install PyGObject
```

### "Cannot initialize GTK4"
Ensure GTK4 is installed:
```bash
# Ubuntu/Debian
sudo apt-get install libgtk-4-dev

# Fedora
sudo dnf install gtk4-devel

# macOS
brew install gtk4
```

### "Application doesn't start"
```bash
# Run with debug output
python -u main.py

# Check Python version (need 3.10+)
python --version
```

### "Styling looks weird"
CSS file not loading. Try:
```bash
# From project root
python main.py
```

### "No window appears"
```bash
# Check if running on Wayland (different behavior)
echo $XDG_SESSION_TYPE

# Try forcing X11
GDK_BACKEND=x11 python main.py
```

## 10. Dark Mode / Light Mode

Current version is dark theme only. Dark mode toggle planned. To help:
- Check [DESIGN.md](DESIGN.md) for light mode color mappings
- Update [ui/styles.css](ui/styles.css) with light variant colors
- Add theme switcher in settings panel

## 11. Performance Tips

- **Smooth scrolling**: Inherent to GTK4 (hardware accelerated)
- **Animation performance**: All using CSS (GPU accelerated)
- **Memory usage**: Conversation pruning not yet implemented
- **Startup time**: ~2-3 seconds (GTK4 overhead)

## 12. Have Questions?

- See [README.md](README.md) for full documentation
- See [DESIGN.md](DESIGN.md) for detailed design specs
- Check code comments in individual files
- Review GTK4 documentation: https://docs.gtk.org/gtk4/

---

**Ready to build premium desktop AI apps!** 🚀

Next: Check out [DESIGN.md](DESIGN.md) for the complete visual specification.
