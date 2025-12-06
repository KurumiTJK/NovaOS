# NovaOS

**A Life RPG Operating System for Personal Growth**

NovaOS is an AI-powered personal operating system that gamifies life management through quests, XP, skill domains, and intelligent assistance. Think of it as your personal RPG companion that helps you learn, grow, and stay organized.

---

## ✨ Features

### 🎮 Quest Engine
- **Gamified Learning**: Complete quests to earn XP and level up
- **Multi-step Questlines**: Break down goals into manageable steps
- **Skill Domains**: Track progress across different life areas
- **Streaks & Rewards**: Stay motivated with completion streaks and unlockable titles

### 📥 Inbox System (GTD-style)
- **Quick Capture**: Instantly capture thoughts, ideas, and tasks
- **Smart Processing**: Convert inbox items to quests or reminders
- **Priority Tagging**: Organize by urgency and importance

### 🧠 Intelligent Assistant
- **Natural Language**: Talk to Nova naturally, no commands required
- **Strategist Mode**: Get personalized recommendations (read-only, never auto-executes)
- **Story/Utility Modes**: Choose your preferred interaction style

### ⏰ Time Rhythm
- **Daily Presence**: Time-aware greetings and suggestions
- **Weekly Reviews**: Structured reflection and planning
- **Focus Tracking**: Know when you're in your productive hours

### 🗺️ Dynamic Modules
- **Create Your World**: Define custom skill domains/regions
- **No Defaults**: Your life, your categories
- **XP Tracking**: Progress per domain

### 💾 Memory Systems
- **Working Memory**: Context-aware conversations
- **Long-term Storage**: Semantic, procedural, and episodic memory
- **Identity Profile**: Track your growth over time

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10 or higher
- OpenAI API key

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/NovaOS.git
cd NovaOS

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Running NovaOS

**Desktop UI (Tkinter)**
```bash
python main.py
```

**Web API Server**
```bash
python nova_api.py
# Opens at http://localhost:5000
```

---

## 📁 Project Structure

```
NovaOS/
├── backend/
│   ├── llm_client.py        # OpenAI API wrapper
│   └── model_router.py      # Model tier selection
├── data/
│   ├── commands.json        # Command registry
│   ├── inbox.json           # Inbox items
│   ├── modules.json         # User-defined domains
│   ├── player_profile.json  # XP, level, titles
│   ├── quests.json          # Quest definitions
│   ├── quest_progress.json  # Quest completion state
│   ├── reminders.json       # Time-based reminders
│   └── rhythm.json          # Time rhythm state
├── kernel/
│   ├── nova_kernel.py       # Core kernel
│   ├── quest_engine.py      # Quest system
│   ├── quest_handlers.py    # Quest commands
│   ├── inbox_manager.py     # Inbox storage
│   ├── inbox_handlers.py    # Inbox commands
│   ├── player_profile.py    # XP/level system
│   ├── module_manager.py    # Domain management
│   ├── strategist.py        # AI recommendations
│   ├── time_rhythm.py       # Time awareness
│   ├── assistant_mode.py    # Story/utility modes
│   ├── syscommands.py       # All system commands
│   ├── section_defs.py      # Help sections
│   └── ...
├── persona/
│   └── nova_persona.py      # Nova's personality
├── system/
│   ├── config.py            # Configuration
│   └── nova_registry.py     # Command registry
├── ui/
│   └── nova_ui.py           # Desktop interface
├── web/
│   ├── index.html           # Web interface
│   └── nova-avatar.png      # Nova's avatar
├── main.py                  # Desktop entry point
├── nova_api.py              # Web API entry point
├── requirements.txt         # Python dependencies
└── README.md
```

---

## 🎯 Command Reference

NovaOS uses 14 sections to organize commands. Type `#help` for an overview or `#help <section>` for details.

### Core Sections

| Section | Description | Key Commands |
|---------|-------------|--------------|
| **core** | OS control center | `#boot`, `#status`, `#help` |
| **inbox** | Quick capture | `#capture`, `#inbox`, `#inbox-to-quest` |
| **workflow** | Quest Engine | `#quest`, `#next`, `#quest-log` |
| **modules** | Skill domains | `#modules`, `#module-create` |
| **identity** | Player profile | `#identity-show` |
| **timerhythm** | Time awareness | `#presence`, `#align` |
| **reminders** | Time-based pins | `#remind-add`, `#remind-list` |
| **interpretation** | AI strategist | `#analyze`, `#route`, `#insight` |
| **system** | Configuration | `#mode`, `#assistant-mode` |
| **memory** | Knowledge store | `#store`, `#recall` |

### Quick Examples

```bash
# Capture an idea
#capture Learn about JWT security

# Start a quest
#quest

# Advance to next step
#next

# Check your progress
#quest-log

# Get recommendations
#analyze

# Set story mode for full RPG experience
#assistant-mode story
```

---

## 🎮 Assistant Modes

### Story Mode
Full RPG experience with celebratory messages, XP fanfare, and immersive framing.

```
🎉 **Quest Complete: JWT Mastery**
═══════════════════════════════
🎊 **LEVEL UP!** You are now level 5! 🎊
Total XP earned: **150**
```

### Utility Mode
Clean, minimal output for productivity-focused sessions.

```
Quest complete: JWT Mastery
Level up: 5
XP: 150
```

---

## 🔌 API Reference

### POST /nova
Send a message to Nova.

**Request:**
```json
{
  "text": "What should I work on today?",
  "session_id": "my-session"
}
```

**Response:**
```json
{
  "ok": true,
  "content": {
    "summary": "Based on your current quests and energy level..."
  }
}
```

---

## 🛠️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-your-key-here
```

### Config Options

Edit `data/config.json`:

```json
{
  "env": "dev",
  "debug": false
}
```

---

## 🏗️ Architecture

NovaOS follows a modular kernel architecture:

```
┌─────────────────────────────────────────────────┐
│                    UI Layer                      │
│         (nova_ui.py / index.html)               │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│                 Nova Kernel                      │
│    (nova_kernel.py + syscommand_router.py)      │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│               Command Handlers                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │  Quest   │ │  Inbox   │ │ Strate-  │  ...   │
│  │ Handlers │ │ Handlers │ │   gist   │        │
│  └──────────┘ └──────────┘ └──────────┘        │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│                 Data Layer                       │
│        (JSON files in data/ directory)          │
└─────────────────────────────────────────────────┘
```

---

## 📊 Version History

| Version | Highlights |
|---------|------------|
| **v0.8.1** | Section-based help system, cleanup |
| **v0.8.0** | Life RPG architecture: Quest Engine, Player Profile, Modules, Inbox, Strategist, TimeRhythm |
| **v0.7.x** | Working Memory, Behavior Layer |
| **v0.6.x** | Section navigation, custom commands |
| **v0.5.x** | Memory systems, identity profile |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- OpenAI for the GPT API
- The GTD methodology for inbox/capture inspiration
- RPG game design for gamification concepts

---

<p align="center">
  <img src="web/nova-avatar.png" alt="Nova" width="100" />
  <br>
  <em>Nova — Your AI companion for life's quests</em>
</p>