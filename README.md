
# AutoAIAgent Client

[![Python](https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: GNU GPL v3](https://img.shields.io/badge/License-GNU_GPL_v3-blue)](https://www.gnu.org/licenses/gpl-3.0)
[![GTK3](https://img.shields.io/badge/GTK-3.24+-orange?logo=gnome&logoColor=white)](https://www.gtk.org/)
[![GitHub stars](https://img.shields.io/github/stars/kingnixon20/AutoAIAgent?style=social)](https://github.com/kingnixon20/autoaiagent)

**Fast · Native · Private**  
A lightweight desktop chat client for local and remote LLMs with a clean, native GTK interface on Linux.

<br>

## What is AutoAIAgent?

AutoAIAgent is a **privacy-first**, modular desktop application for interacting with language models and running autonomous coding agents — both local (Ollama, LM Studio, …) and remote OpenAI-compatible endpoints.

It offers a responsive native GTK UI, real-time streaming, persistent history, token/context awareness, and powerful extensibility via the **Model Context Protocol (MCP)** for tool calling.

Ideal for:

- Offline / private coding assistance  
- Research with local models  
- Tool-augmented AI workflows  
- Custom automation without browser overhead  
- self-critiquing, autonomous python coding agent, with a layered context management system

<br>

## 🚀 Key Features

- Native GTK interface (custom themable, smooth & responsive)  
- Token-by-token **streaming** responses  
- First-class support for **Ollama**, **LM Studio**, OpenAI-style APIs  
- Persistent SQLite-backed conversation history  
- Built-in **MCP** tool discovery and execution  
- Real-time token counting & context length indicators  
- Per-conversation system prompts  
- Markdown + code syntax highlighting in chat  
- Low memory footprint (~20–40 MB idle)

<br>

## 📥 Installation

### Prerequisites

- Python **3.8** or newer  
- GTK **3** libraries (`libgtk-3-0` on Debian/Ubuntu, `gtk3` on Fedora, etc.)  
- `pip` and `git`

### Quick Start

```bash
# Clone
git clone https://github.com/kingnixon20/AutoAIAgent.git
cd AutoAIAgent

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

On first launch go to **Settings → Models** and add your endpoint (e.g. `http://localhost:11434` for Ollama).

<br>

## 🔧 MCP Tool Integration

AutoAIAgent supports the **Model Context Protocol** (MCP) — enabling models to discover and call external tools dynamically.

Common capabilities:

- 🌐 Web search / browsing  
- 📂 Local file read/write  
- 🛠️ Shell execution (with user confirmation)  
- 🧮 Code interpreter / calculator  
- 🔌 Custom API connectors  

Tools are auto-detected at runtime — no core changes required.

<br>

## 📖 More Documentation

Detailed guides and Documentation:

- [QUICKSTART.md](./QUICKSTART.md) — setup & first chat  
- [INDEX.md](./INDEX.md) — architecture overview  

<br>

## ⚖️ License

GNU3 License — see the [LICENSE](./LICENSE) file.

<br>

## 🤝 Contributing

Contributions welcome!  

1. Fork the repo  
2. Create your feature branch (`git checkout -b feature/cool-tool`)  
3. Commit (`git commit -m 'Add cool tool support'`)  
4. Push (`git push origin feature/cool-tool`)  
5. Open a Pull Request  

Bug reports, feature ideas, and documentation improvements are all appreciated.

<br>

Made with focus on local AI & privacy  
Last updated February 2026
