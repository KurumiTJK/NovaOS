# NovaOS v0.7.16 — Enhanced Custom Commands Integration Guide

## Overview

This update adds rich metadata and behavior control to custom commands:

| Feature | Description | Default |
|---------|-------------|---------|
| `intensive` | Use gpt-5.1 instead of gpt-4.1-mini | `false` |
| `output_style` | Format: natural, bullets, numbered, short, verbose, json | `natural` |
| `examples` | Few-shot examples for the LLM | `[]` |
| `strict` | Disable improvisation/commentary | `false` |
| `persona_mode` | Tone: nova, neutral, professional | `nova` |

## Files to Add

Copy these new files to your `kernel/` directory:

```
kernel/
├── custom_command_v2.py        # Core logic + schema
├── custom_command_handlers.py  # Updated handlers
```

## Integration Steps

### Step 1: Update `syscommands.py`

At the top of `syscommands.py`, add the import:

```python
# v0.7.16: Enhanced custom commands
from .custom_command_handlers import get_v2_handlers
```

Then at the bottom, where `SYS_HANDLERS` is defined, add:

```python
# v0.7.16: Replace custom command handlers with enhanced versions
SYS_HANDLERS.update(get_v2_handlers())
```

### Step 2: Update `nova_registry.py`

Replace the existing `_normalize_custom_command` function with the v0.7.16 version.

**Option A: Import directly**

```python
# At the top of nova_registry.py
from .custom_command_v2 import normalize_custom_command_v2

# Replace the existing function
_normalize_custom_command = normalize_custom_command_v2
```

**Option B: Use the patch function**

In your kernel initialization (e.g., `nova_kernel.py`):

```python
from kernel.custom_command_handlers import patch_normalizer
patch_normalizer()
```

### Step 3: Verify `llm_client.py` has `complete_system()`

The enhanced custom commands use `complete_system()` for proper routing/logging.
Ensure your `llm_client.py` has this method (included in the v0.6.6 version).

## Usage Examples

### Basic Command (gpt-4.1-mini)

```bash
#command-add name=greet kind=prompt prompt_template="Say hello to {{full_input}}"
```

### Intensive Command (gpt-5.1)

```bash
#command-add name=deep-analyze kind=prompt \
    prompt_template="Analyze this in depth: {{full_input}}" \
    intensive=true
```

### Styled Command (bullet output)

```bash
#command-add name=summarize kind=prompt \
    prompt_template="Summarize the following: {{full_input}}" \
    output_style=bullets
```

### Strict Command (no improvisation)

```bash
#command-add name=translate kind=prompt \
    prompt_template="Translate to Korean: {{full_input}}" \
    strict=true \
    output_style=short
```

### Full Example (all options)

```bash
#command-add name=daily-reflect kind=prompt \
    prompt_template="Reflect on: {{full_input}}" \
    intensive=true \
    output_style=bullets \
    strict=true \
    persona_mode=professional
```

## Expected Logging

When you run a custom command, you should see:

```
# Mini model (default)
[ModelRouter] command=greet model=gpt-4.1-mini reason=default
[LLM] system command=greet model=gpt-4.1-mini

# Intensive model
[ModelRouter] command=deep-analyze model=gpt-5.1 reason=think_mode
[LLM] system command=deep-analyze model=gpt-5.1
```

## Inspecting Commands

Use `#command-inspect` to see all v0.7.16 fields:

```bash
#command-inspect name=daily-reflect
```

Output:
```
═══ Command: #daily-reflect ═══

Name: daily-reflect
Kind: prompt
Enabled: True

─── Model Settings ───
Model Tier: thinking (gpt-5.1)
Intensive: True

─── Output Settings ───
Output Style: bullets
Strict Mode: True
Persona Mode: professional

─── Prompt Template ───
  Reflect on: {{full_input}}
```

## Listing Commands

Use `#command-list` to see enhanced metadata:

```bash
#command-list
```

Output:
```
═══ Commands ═══

─── Custom Commands ───
  daily-reflect [prompt, enabled, 🧠, style:bullets, strict]
  greet [prompt, enabled, ⚡]
  summarize [prompt, enabled, ⚡, style:bullets]

Legend: ⚡=mini model, 🧠=thinking model
```

## Backwards Compatibility

- All existing custom commands continue to work unchanged
- Commands without new fields get sensible defaults:
  - `intensive: false` → uses gpt-4.1-mini
  - `output_style: "natural"` → conversational tone
  - `strict: false` → normal LLM behavior
  - `persona_mode: "nova"` → warm, helpful tone

## Schema Reference

```json
{
  "name": "daily-reflect",
  "kind": "prompt",
  "prompt_template": "Reflect on: {{full_input}}",
  "description": "Daily reflection command",
  "enabled": true,
  
  "intensive": true,
  "model_tier": "thinking",
  "output_style": "bullets",
  "examples": [
    {"input": "I had a tough day", "output": "• Take a moment to breathe..."}
  ],
  "strict": true,
  "persona_mode": "professional"
}
```

## Troubleshooting

### Command not using correct model

1. Check `#command-inspect name=<cmd>` to see `intensive` value
2. Verify logging shows expected model
3. Ensure `complete_system()` is being called (not `complete()`)

### Output style not applied

1. Check `output_style` in `#command-inspect`
2. LLM may occasionally deviate; add `strict=true` for stricter adherence

### Examples not working

1. Examples must be valid JSON: `[{"input": "...", "output": "..."}]`
2. Check `#command-inspect` to see if examples are stored correctly
