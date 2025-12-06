# NovaOS v0.8.0 — Quest Engine Integration Guide

## Overview

The Quest Engine replaces the legacy workflow system with a gamified learning experience featuring:
- **Quests** — Structured learning paths with multiple steps
- **XP & Skills** — Track progress across skill trees
- **Streaks** — Learning streak tracking
- **Boss Battles** — Challenge steps that test understanding

## New Commands

| Command | Description |
|---------|-------------|
| `#quest` | Open Quest Board, start/resume quests |
| `#next` | Advance to next step |
| `#pause` | Pause active quest |
| `#quest-log` | View progress, XP, skills, streaks |
| `#quest-reset` | Reset quest progress |
| `#quest-compose` | Create new quest |
| `#quest-delete` | Delete a quest |
| `#quest-list` | List all quests (admin) |
| `#quest-inspect` | Inspect quest details |
| `#quest-debug` | Debug output |

## Removed Commands

The following legacy workflow commands are **REMOVED**:
- `#flow`
- `#advance`
- `#halt`
- `#compose` (the workflow version)
- `#workflow-delete`
- `#workflow-list`
- `#workflow-inspect`

## Files to Add/Update

### NEW FILES (add to `kernel/`)

| File | Description |
|------|-------------|
| `quest_engine.py` | Core Quest Engine module |
| `quest_handlers.py` | Command handlers for all quest commands |

### FILES TO UPDATE

| File | Changes |
|------|---------|
| `nova_kernel.py` | Initialize QuestEngine instead of WorkflowEngine |
| `syscommands.py` | Import quest handlers, remove workflow handlers |
| `nl_router.py` | Remove workflow patterns, add quest suggestions |
| `commands.json` | Remove workflow commands, add quest commands |
| `section_defs.py` | Update WORKFLOW section to show quest commands |

---

## Step-by-Step Integration

### Step 1: Add New Files

Copy these files to `kernel/`:
- `quest_engine.py`
- `quest_handlers.py`

### Step 2: Update `nova_kernel.py`

Find this section:
```python
from kernel.time_rhythm import TimeRhythmEngine
from kernel.workflow_engine import WorkflowEngine
from kernel.reminders_manager import RemindersManager

self.time_rhythm_engine = TimeRhythmEngine()
self.workflow_engine = WorkflowEngine()
self.reminders = RemindersManager(self.config.data_dir)
```

Replace with:
```python
from kernel.time_rhythm import TimeRhythmEngine
from kernel.reminders_manager import RemindersManager

# v0.8.0: Quest Engine (replaces legacy WorkflowEngine)
try:
    from kernel.quest_engine import QuestEngine
    self.quest_engine = QuestEngine(self.config.data_dir)
except ImportError:
    from kernel.workflow_engine import WorkflowEngine
    self.quest_engine = None
    self.workflow_engine = WorkflowEngine()

self.time_rhythm_engine = TimeRhythmEngine()
if not hasattr(self, 'workflow_engine'):
    self.workflow_engine = None
self.reminders = RemindersManager(self.config.data_dir)
```

### Step 3: Update `syscommands.py`

**Add import at the top:**
```python
# v0.8.0: Quest Engine handlers
from .quest_handlers import get_quest_handlers
```

**Remove these from SYS_HANDLERS:**
```python
"handle_flow": handle_flow,
"handle_advance": handle_advance,
"handle_halt": handle_halt,
"handle_compose": handle_compose,
"handle_workflow_delete": handle_workflow_delete,
"handle_workflow_list": handle_workflow_list,
"handle_workflow_inspect": handle_workflow_inspect,
```

**Add after SYS_HANDLERS definition:**
```python
# v0.8.0: Quest Engine handlers
SYS_HANDLERS.update(get_quest_handlers())
```

### Step 4: Update `nl_router.py`

Replace your `nl_router.py` with the new version that:
- Removes `WORKFLOW_PATTERNS` (no auto-routing for quests)
- Adds `check_quest_suggestion()` function for suggestions only

### Step 5: Update `commands.json`

**Remove these entries:**
```json
"flow": {...},
"advance": {...},
"halt": {...},
"compose": {...},
"workflow-delete": {...},
"workflow-list": {...},
"workflow-inspect": {...}
```

**Add these entries:**
```json
"quest": {
  "handler": "handle_quest",
  "category": "workflow",
  "description": "Open the Quest Board to list, start, or resume a quest."
},
"next": {
  "handler": "handle_next",
  "category": "workflow",
  "description": "Submit your last answer and advance to the next step."
},
"pause": {
  "handler": "handle_pause",
  "category": "workflow",
  "description": "Pause the active quest and save your progress."
},
"quest-log": {
  "handler": "handle_quest_log",
  "category": "workflow",
  "description": "View your current quest, recent completions, XP, skills, and streak."
},
"quest-reset": {
  "handler": "handle_quest_reset",
  "category": "workflow",
  "description": "Reset a quest's progress to replay from the start."
},
"quest-compose": {
  "handler": "handle_quest_compose",
  "category": "workflow",
  "description": "Compose a new questline with LLM assistance."
},
"quest-delete": {
  "handler": "handle_quest_delete",
  "category": "workflow",
  "description": "Delete a questline and its saved progress."
},
"quest-list": {
  "handler": "handle_quest_list",
  "category": "workflow",
  "description": "List all quest definitions with IDs, categories, and difficulty."
},
"quest-inspect": {
  "handler": "handle_quest_inspect",
  "category": "workflow",
  "description": "Inspect a quest definition and all its steps."
},
"quest-debug": {
  "handler": "handle_quest_debug",
  "category": "workflow",
  "description": "Show raw quest engine state for debugging."
}
```

### Step 6: Update `section_defs.py`

Find the `"workflow"` entry in SECTION_DEFS and replace with:
```python
"workflow": {
    "title": "Quest Engine",
    "description": "Gamified learning quests with XP, skills, and progress tracking.",
    "commands": [
        "quest",
        "next",
        "pause",
        "quest-log",
        "quest-reset",
        "quest-compose",
        "quest-delete",
        "quest-list",
        "quest-inspect",
        "quest-debug"
    ]
},
```

---

## Testing

### Test 1: Quest Board
```
#quest
```
Should show the Quest Board with available quests.

### Test 2: Start a Quest
```
#quest 1
```
or
```
#quest id=jwt_intro
```
Should start the first quest and show Step 1.

### Test 3: Advance
```
#next
```
Should advance to the next step.

### Test 4: Pause
```
#pause
```
Should pause the quest and save progress.

### Test 5: Quest Log
```
#quest-log
```
Should show progress, XP, skills, and streaks.

### Test 6: Old Commands Removed
```
#flow
```
Should show "Unknown command" error.

---

## Data Files

The Quest Engine creates these files in your data directory:

| File | Description |
|------|-------------|
| `quests.json` | Quest definitions |
| `quest_progress.json` | Progress, XP, skills, streaks |
| `quest_active_run.json` | Current active quest state |

---

## Natural Language Routing

**IMPORTANT:** Quest commands are NEVER auto-executed from natural language.

If a user says "start my quest", the system will NOT auto-run `#quest`.
Instead, it will suggest: "To start a quest, run: `#quest`"

This is by design - quests require explicit user intent.

---

## Quest Structure

```json
{
  "id": "jwt_intro",
  "title": "JWT Fundamentals",
  "subtitle": "Understanding JSON Web Tokens",
  "description": "Learn the basics of JWT...",
  "category": "cyber",
  "skill_tree_path": "cyber.jwt.tier1",
  "difficulty": 2,
  "estimated_minutes": 20,
  "tags": ["learning", "security"],
  "steps": [
    {
      "id": "step_1",
      "type": "info",
      "title": "What is a JWT?",
      "prompt": "A JWT is...",
      "help_text": "..."
    },
    {
      "id": "step_2",
      "type": "recall",
      "title": "JWT Structure",
      "prompt": "What are the three parts of a JWT?",
      "difficulty": 1,
      "validation": {
        "mode": "keyword",
        "keywords": ["header", "payload", "signature"]
      }
    },
    {
      "id": "boss",
      "type": "boss",
      "title": "Security Challenge",
      "prompt": "Explain a JWT attack scenario...",
      "difficulty": 3,
      "passing_threshold": 0.7
    }
  ],
  "rewards": {
    "xp": 25,
    "shortcuts": ["jwt-decode"],
    "visual_unlock": "🔐"
  }
}
```

---

## Step Types

| Type | Description | XP Formula |
|------|-------------|------------|
| `info` | Information display | 0 |
| `recall` | Memory/knowledge check | difficulty |
| `reflect` | Reflection prompt | difficulty |
| `apply` | Practical application | difficulty |
| `transfer` | Apply to new context | difficulty |
| `action` | Do something external | difficulty |
| `mini_boss` | Challenge step | 2 * difficulty |
| `boss` | Final challenge | 5 * difficulty + rewards |

---

## XP & Skills

- Each non-info step grants XP based on difficulty
- Boss steps grant bonus XP + quest rewards
- XP accumulates in skill paths (e.g., `cyber.jwt.tier1`)
- Skill tiers unlock at: 0, 50, 150, 300, 500 XP

---

## Learning Streaks

- Quests tagged with "learning" contribute to streaks
- Complete at least one step per day to maintain streak
- Streak resets if you miss a day
