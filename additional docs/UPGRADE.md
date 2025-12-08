# NovaOS v0.9.0 Upgrade Guide

## Dual-Mode Architecture

NovaOS v0.9.0 introduces a **dual-mode architecture** that separates conversational Nova (Persona mode) from the full OS functionality (NovaOS mode).

### What Changed

| Before v0.9.0 | After v0.9.0 |
|---------------|--------------|
| All input goes through kernel | Input routed by mode |
| Commands always work | Commands only work after `#boot` |
| Single mode | Two modes: Persona / NovaOS |
| `kernel.handle_input()` is entry point | `handle_user_message()` is entry point |

### User Experience

**Default (Persona Mode):**
- Pure conversational AI
- Working memory still active (conversation continuity)
- Commands like `#status`, `#help` are just chat (not executed)
- Only `#boot` is recognized as a special command

**After `#boot` (NovaOS Mode):**
- Full kernel functionality
- All syscommands work
- Modules, quests, memory commands available
- `#shutdown` returns to Persona mode

---

## File Changes

### New Files (add these)

```
NovaOS/
├── core/                    # NEW FOLDER
│   ├── __init__.py
│   ├── nova_state.py        # Mode state tracking
│   └── mode_router.py       # Main entry point
└── kernel/
    └── kernel_response.py   # NEW: Structured response object
```

### Modified Files (replace these)

```
NovaOS/
├── main.py                  # Updated constructor
├── nova_api.py              # Uses mode router
├── ui/
│   └── nova_ui.py           # Uses mode router
├── web/
│   └── index.html           # Mode indicator UI
├── kernel/
│   ├── syscommands.py       # Added handle_shutdown
│   └── section_defs.py      # Added shutdown command
└── data/
    └── commands.json        # Added shutdown entry
```

---

## Step-by-Step Migration

### Step 1: Add New Files

1. Create the `core/` folder in your project root
2. Copy these files into `core/`:
   - `__init__.py`
   - `nova_state.py`
   - `mode_router.py`

3. Copy `kernel/kernel_response.py` to your `kernel/` folder

### Step 2: Update Kernel Files

1. **Replace** `kernel/syscommands.py` with the new version
   - Adds `handle_shutdown` handler
   - Returns `CommandResponse` objects (not dicts)

2. **Replace** `kernel/section_defs.py` with the new version
   - Adds `shutdown` command to core section

### Step 3: Update Entry Points

1. **Replace** `main.py`:
```python
# OLD
app = NovaApp(kernel=kernel, config=config)

# NEW
from persona.nova_persona import NovaPersona
persona = NovaPersona(llm_client)
app = NovaApp(kernel=kernel, persona=persona, config=config)
```

2. **Replace** `nova_api.py` with the new version

3. **Replace** `ui/nova_ui.py` with the new version

### Step 4: Update commands.json

Add this entry after "boot":

```json
"shutdown": {
  "handler": "handle_shutdown",
  "category": "core",
  "description": "Shutdown NovaOS and return to Persona mode"
}
```

### Step 5: Update Web UI (Optional)

Replace `web/index.html` with the new version that shows mode indicator.

---

## Testing the Migration

### Test Script

Run the included test script:

```bash
python test_dual_mode.py
```

Expected output:
```
✅ ALL TESTS PASSED!
```

### Manual Testing

1. **Start the app:**
   ```bash
   python main.py
   ```

2. **Verify Persona mode:**
   - Type: "Hello Nova"
   - Should get a conversational response
   - Type: "#status"
   - Should get chat response (NOT status output)

3. **Activate NovaOS:**
   - Type: "#boot"
   - Should see "[NovaOS activated]"
   - Window title should show "NovaOS Mode"

4. **Verify NovaOS mode:**
   - Type: "#status"
   - Should see actual status output
   - Type: "#help"
   - Should see help sections

5. **Return to Persona:**
   - Type: "#shutdown"
   - Should see "[NovaOS deactivated]"
   - Commands should stop working

---

## Rollback

If you need to rollback:

1. Restore your original `syscommands.py`, `section_defs.py`
2. Restore your original `main.py`, `nova_api.py`, `nova_ui.py`
3. Remove the `core/` folder
4. Remove `kernel/kernel_response.py`

The old code paths in `nova_kernel.py` are unchanged and will continue to work.

---

## Troubleshooting

### "AttributeError: 'dict' object has no attribute 'to_dict'"

**Cause:** `syscommands.py` is returning plain dicts instead of `CommandResponse` objects.

**Fix:** Make sure you replaced `syscommands.py` with the v0.9.0 version that uses `CommandResponse`.

### "ImportError: cannot import name 'handle_user_message' from 'core.mode_router'"

**Cause:** The `core/` folder is missing or not in the Python path.

**Fix:** 
1. Verify `core/` folder exists in project root
2. Verify `core/__init__.py` exists
3. Run from project root directory

### "TypeError: NovaApp.__init__() got unexpected keyword argument 'persona'"

**Cause:** Using old `nova_ui.py` with new `main.py`.

**Fix:** Replace `ui/nova_ui.py` with the v0.9.0 version.

### Commands not working after #boot

**Cause:** `commands.json` missing the shutdown entry, or kernel not recognizing commands.

**Fix:** 
1. Verify `shutdown` entry in `commands.json`
2. Verify `handle_shutdown` in `SYS_HANDLERS` dict

---

## Architecture Reference

```
┌─────────────────────────────────────────────────────────────┐
│                        User Input                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Mode Router (core/)                        │
│                                                              │
│   state.novaos_enabled?                                      │
│   ├── NO  → Persona Mode                                     │
│   │         ├── #boot? → Activate NovaOS                     │
│   │         └── else  → Persona chat (with WM)               │
│   │                                                          │
│   └── YES → NovaOS Mode                                      │
│             ├── #shutdown? → Deactivate NovaOS               │
│             └── else → Kernel routing                        │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          │                               │
          ▼                               ▼
┌─────────────────┐             ┌─────────────────┐
│   Persona       │             │   Kernel        │
│                 │             │                 │
│  generate_      │             │  handle_input() │
│  response()     │             │  - syscommands  │
│                 │             │  - NL router    │
│  (with WM       │             │  - persona      │
│   context)      │             │    fallback     │
└─────────────────┘             └─────────────────┘
          │                               │
          └───────────────┬───────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Working Memory                            │
│                    (shared layer)                            │
└─────────────────────────────────────────────────────────────┘
```

---

## Questions?

If you encounter issues not covered here, check:
1. The test script output for specific failures
2. Python traceback for import/attribute errors
3. The debug mode in the UI (checkbox) for response details
