# Nova Council — Multi-Model Orchestration for NovaOS

Nova Council is a multi-model orchestration system that integrates Gemini AI alongside GPT-5 to provide:
- **Cheap quest ideation** via Gemini Flash
- **High-powered research** via Gemini Pro
- **Command design pipeline** with full LIVE-MAX mode

## Non-Negotiable Rules

1. **Only GPT-5 speaks to the user** — Gemini never produces final user-facing output
2. **Gemini output is ephemeral** — Never stored to long-term memory
3. **Mode selection is explicit** — Flags override heuristics
4. **LIVE-MAX is mandatory for command design** — No budget guardrails
5. **Terminal-friendly output** — No stray markdown, preserve NovaOS style

## Modes

| Mode | Trigger | Pipeline |
|------|---------|----------|
| **SOLO** | Default, `@solo` | GPT-5 only |
| **QUEST** | Quest creation, `@explore` in quest flow | Gemini Flash → GPT-5 synthesis |
| **LIVE** | Research triggers, `@live`, `@explore` | Gemini Pro → GPT-5 final |
| **LIVE-MAX** | Command design, `@max` | Gemini Pro → GPT-5 Design → GPT-5 Verify |

## Explicit Flags

Add these flags to your message to force a specific mode (stripped before model calls):

- `@solo` — Force SOLO (GPT-5 only)
- `@explore` — Force QUEST (in quest flow) or LIVE (general)
- `@live` — Force LIVE mode
- `@max` — Force LIVE-MAX (only applies to command-intent queries)

## Heuristic Detection

If no flags are provided, mode is detected by content:

### Command-Intent → LIVE-MAX (mandatory)
- "create a command", "design a command", "add a command"
- "modify command", "refactor command", "implement command"
- Mentions: SYS_HANDLERS, handler, router, registry

### Quest-Intent → QUEST
- "create a quest", "quest-compose", "quest"
- "lesson plan", "steps for learning"
- `#quest-compose` command

### Live-Intent → LIVE
- "latest", "current", "today"
- "docs", "pricing", "status", "verify"

## Installation

### 1. Copy Files to NovaOS

```bash
# Copy the council and providers directories to your NovaOS root
cp -r council/ /path/to/nova-os/
cp -r providers/ /path/to/nova-os/
```

### 2. Install Dependencies

```bash
pip install google-generativeai --break-system-packages
```

### 3. Set Environment Variables

Add to your `.env` file:

```env
# Required
GEMINI_API_KEY=your-gemini-api-key-here

# Optional (defaults shown)
GEMINI_ENABLED=true
COUNCIL_CACHE_DIR=/tmp/nova-council-cache
```

### 4. Apply Patches

Apply the patches in the `patches/` directory to your existing NovaOS files:

- `patch_dashboard_handlers.py` → Modify `kernel/dashboard_handlers.py`
- `patch_mode_router.py` → Modify `core/mode_router.py`
- `patch_nova_api.py` → Modify `nova_api.py`

See each patch file for detailed instructions.

## Configuration

### Kill Switch

To disable Gemini entirely (silent fallback to SOLO):

```env
GEMINI_ENABLED=false
```

### Cache Settings

Quest ideation results are cached for 24 hours by default:

```env
COUNCIL_CACHE_DIR=/custom/cache/path
```

## Dashboard Display

The dashboard MODE section now shows:

```
MODE
  Persona: OFF | Council: OFF
```

After using Gemini:

```
MODE
  Persona: OFF | Council: QUEST
```

Or for command design:

```
MODE
  Persona: OFF | Council: LIVE-MAX
```

## API Endpoints

### GET /api/council/status

Returns council status and Gemini configuration:

```json
{
  "ok": true,
  "council_available": true,
  "session_id": "default",
  "state": {
    "mode": "QUEST",
    "used": true,
    "gemini_calls": 2,
    "cache_hits": 1,
    "errors": 0
  },
  "gemini": {
    "available": true,
    "sdk_installed": true,
    "enabled": true,
    "api_key_set": true
  }
}
```

### POST /api/council/reset

Reset council state:

```json
{"session_id": "abc123"}  // Reset specific session
{"all": true}             // Reset all sessions
```

## Acceptance Tests

### Test 1: Normal Chat → SOLO

```
User: Hello, how are you?
Expected: Council: OFF in dashboard, no Gemini calls
```

### Test 2: Quest Request → QUEST

```
User: Create a quest for learning Python basics
Expected:
- Gemini Flash called once
- GPT-5 outputs final quest
- Dashboard shows Council: QUEST
```

### Test 3: Research Request → LIVE

```
User: What's the latest pricing for AWS Lambda?
Expected:
- Gemini Pro called
- GPT-5 synthesizes final answer
- Dashboard shows Council: LIVE
```

### Test 4: Command Design → LIVE-MAX

```
User: Design a new #dashboard-view command that shows memory stats
Expected:
- Gemini Pro called (research)
- GPT-5 design pass (spec)
- GPT-5 verify pass (validation)
- Dashboard shows Council: LIVE-MAX
```

## Logging

All council operations are logged:

```
[CouncilRouter] mode=QUEST reason=heuristic_quest_intent
[GeminiClient] gemini_quest_ideate: model=gemini-1.5-flash
[GeminiClient] gemini_quest_ideate: SUCCESS
[CouncilValidate] quest_ideation: VALID (4 steps)
[CouncilCache] STORED hash=a1b2c3d4
[CouncilPipeline] QUEST - SUCCESS
[CouncilOrchestrator] mode=QUEST reason=heuristic_quest_intent
```

## Files Structure

```
nova-council/
├── council/
│   ├── __init__.py           # Package exports
│   ├── state.py              # Session state management
│   ├── router.py             # Mode detection and routing
│   ├── orchestrator.py       # Pipeline execution
│   ├── validate.py           # JSON schema validation
│   ├── dashboard_integration.py  # Dashboard helpers
│   └── mode_router_integration.py # mode_router.py integration
├── providers/
│   ├── __init__.py           # Package exports
│   └── gemini_client.py      # Gemini API client
├── patches/
│   ├── patch_dashboard_handlers.py
│   ├── patch_mode_router.py
│   └── patch_nova_api.py
└── README.md
```

## Troubleshooting

### Gemini Not Available

Check:
1. `GEMINI_API_KEY` is set in `.env`
2. `GEMINI_ENABLED` is not set to `false`
3. `google-generativeai` package is installed

### Cache Issues

Clear the cache directory:

```bash
rm -rf /tmp/nova-council-cache/*
```

### Mode Not Detected

If your message isn't triggering the expected mode:
1. Use explicit flags (`@quest`, `@live`, `@max`)
2. Check the logs for `[CouncilRouter]` entries
3. Verify heuristic patterns match your text

### Gemini Returns Invalid JSON

The system will fall back to SOLO mode if:
- Gemini returns empty response
- JSON schema validation fails
- Network/timeout errors

Check logs for `[CouncilValidate]` and `[GeminiClient]` errors.

## Version History

- **v1.0.0** — Initial implementation
  - Gemini Flash for quest ideation
  - Gemini Pro for live research
  - LIVE-MAX pipeline for command design
  - Dashboard indicator
  - 24h cache for QUEST mode

## License

Part of NovaOS. Internal use only.
