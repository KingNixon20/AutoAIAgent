# 📚 AutoAI Chat Client - Complete Documentation Index

## Quick Navigation

### 🚀 Getting Started
- **[QUICKSTART.md](QUICKSTART.md)** - 5-minute setup guide (start here!)
- **[README.md](README.md)** - Full feature overview and documentation (primary documentation)

---

## 📁 Project Contents

### Core Application Files
```
main.py                      Entry point - start here
constants.py                 Design constants & configuration
requirements.txt             Python dependencies
```

### User Interface (ui/)
```
ui/
├── styles.css              Complete GTK3 stylesheet
├── main_window.py          Main window & orchestration
└── components/
    ├── message_bubble.py   Message display widget
    ├── chat_input.py       Text input with send button
    ├── chat_area.py        Message list container
    ├── sidebar.py          Conversation navigation
    └── settings_panel.py   Settings & configuration
```

### Data Models (models/)
```
models/
└── message.py              Message, Conversation, Settings dataclasses
```

### API Client (api/)
```
api/
└── __init__.py             LM Studio API client (async/streaming)
```

### Documentation
```
README.md                    Main documentation (read first)
QUICKSTART.md               Quick start guide (minimal setup)
INDEX.md                    This file
```