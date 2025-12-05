# kernel/custom_command_v2.py
"""
v0.7.16 — Enhanced Custom Command System

This module provides rich metadata and behavior for custom commands:

┌─────────────────────────────────────────────────────────────────────────────┐
│ CUSTOM COMMAND SCHEMA (v0.7.16)                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ {                                                                           │
│   "name": "daily-reflect",           // Required: command name              │
│   "kind": "prompt",                  // Required: "prompt" or "macro"       │
│   "prompt_template": "...",          // Required for prompt commands        │
│   "description": "...",              // Optional: help text                 │
│   "enabled": true,                   // Optional: default true              │
│                                                                             │
│   // ─────────────────────────────────────────────────────────────────────  │
│   // v0.7.16 ENHANCED FIELDS                                                │
│   // ─────────────────────────────────────────────────────────────────────  │
│                                                                             │
│   "intensive": false,                // Model selection: false=mini, true=5.1│
│   "model_tier": "mini",              // Alternative: "mini" | "thinking"    │
│                                                                             │
│   "output_style": "natural",         // "natural" | "bullets" | "short" |   │
│                                      // "verbose" | "json" | "numbered"     │
│                                                                             │
│   "examples": [                      // Optional few-shot examples          │
│     {"input": "...", "output": "..."},                                      │
│     {"input": "...", "output": "..."}                                       │
│   ],                                                                        │
│                                                                             │
│   "strict": false,                   // If true: no improvisation           │
│   "persona_mode": "nova"             // "nova" | "neutral" | "professional" │
│ }                                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

USAGE:

    # Create command with enhanced options:
    #command-add name=daily-reflect kind=prompt \\
        prompt_template="Reflect on today and summarize key insights." \\
        intensive=true \\
        output_style=bullets \\
        strict=true

    # Run command:
    #daily-reflect

    # The system will:
    # 1. Use gpt-5.1 (because intensive=true)
    # 2. Format output as bullets
    # 3. Not add extra commentary (strict=true)
    # 4. Log: [ModelRouter] command=daily-reflect model=gpt-5.1

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .command_types import CommandResponse
from .formatting import OutputFormatter as F


# =============================================================================
# CONSTANTS
# =============================================================================

# Valid output styles
OUTPUT_STYLES = {
    "natural",      # Default Nova conversational style
    "bullets",      # Bullet point list
    "numbered",     # Numbered list
    "short",        # Brief, concise (1-2 sentences)
    "verbose",      # Detailed, thorough explanation
    "json",         # Structured JSON output
}

# Valid persona modes
PERSONA_MODES = {
    "nova",         # Warm, helpful Nova personality
    "neutral",      # Professional, no personality
    "professional", # Formal, business-like
}

# Default values for enhanced fields
DEFAULTS = {
    "intensive": False,
    "model_tier": "mini",
    "output_style": "natural",
    "examples": [],
    "strict": False,
    "persona_mode": "nova",
}


# =============================================================================
# NORMALIZATION
# =============================================================================

def normalize_custom_command_v2(name: str, meta: dict | None) -> dict:
    """
    Normalize a custom command with v0.7.16 enhanced fields.
    
    This extends the existing normalization to add:
    - intensive / model_tier
    - output_style
    - examples
    - strict
    - persona_mode
    
    Backwards compatible: commands without these fields get defaults.
    """
    meta = dict(meta or {})
    meta.setdefault("name", name)

    # ─────────────────────────────────────────────────────────────────────
    # Existing fields (preserve v0.5.2 behavior)
    # ─────────────────────────────────────────────────────────────────────
    
    kind = meta.get("kind") or "prompt"
    if kind not in ("prompt", "macro"):
        kind = "prompt"
    meta["kind"] = kind

    if "enabled" not in meta:
        meta["enabled"] = True

    if kind == "prompt":
        meta.setdefault("handler", "handle_prompt_command")
        meta.setdefault("prompt_template", "{{full_input}}")
        if not isinstance(meta.get("input_mapping"), dict):
            meta["input_mapping"] = {"full_input": "full_input"}

    elif kind == "macro":
        meta.setdefault("handler", "handle_macro")
        steps = meta.get("steps")
        if not isinstance(steps, list):
            meta["steps"] = []

    # ─────────────────────────────────────────────────────────────────────
    # v0.7.16 Enhanced fields
    # ─────────────────────────────────────────────────────────────────────
    
    # Model selection: intensive flag or model_tier
    # intensive=true → use gpt-5.1 (thinking tier)
    # intensive=false or not set → use gpt-4.1-mini (mini tier)
    if "intensive" not in meta:
        # Check for model_tier alternative
        tier = meta.get("model_tier", "mini")
        meta["intensive"] = (tier == "thinking")
    else:
        # Normalize intensive to boolean
        intensive = meta["intensive"]
        if isinstance(intensive, str):
            meta["intensive"] = intensive.lower() in ("true", "yes", "1", "thinking")
        else:
            meta["intensive"] = bool(intensive)
    
    # Ensure model_tier is consistent with intensive
    meta["model_tier"] = "thinking" if meta["intensive"] else "mini"
    
    # Output style
    style = meta.get("output_style", "natural")
    if style not in OUTPUT_STYLES:
        style = "natural"
    meta["output_style"] = style
    
    # Examples (few-shot)
    examples = meta.get("examples")
    if not isinstance(examples, list):
        meta["examples"] = []
    else:
        # Validate each example has input/output
        valid_examples = []
        for ex in examples:
            if isinstance(ex, dict) and "input" in ex and "output" in ex:
                valid_examples.append({
                    "input": str(ex["input"]),
                    "output": str(ex["output"]),
                })
        meta["examples"] = valid_examples
    
    # Strict mode
    strict = meta.get("strict", False)
    if isinstance(strict, str):
        meta["strict"] = strict.lower() in ("true", "yes", "1")
    else:
        meta["strict"] = bool(strict)
    
    # Persona mode
    persona = meta.get("persona_mode", "nova")
    if persona not in PERSONA_MODES:
        persona = "nova"
    meta["persona_mode"] = persona

    return meta


# =============================================================================
# PROMPT BUILDER
# =============================================================================

def build_system_prompt(cmd_config: dict) -> str:
    """
    Build the system prompt for a custom command based on its configuration.
    
    Incorporates:
    - Base prompt template context
    - Output style instructions
    - Strict mode constraints
    - Persona mode adjustments
    - Few-shot examples
    """
    parts = []
    
    # ─────────────────────────────────────────────────────────────────────
    # Base context
    # ─────────────────────────────────────────────────────────────────────
    
    persona_mode = cmd_config.get("persona_mode", "nova")
    
    if persona_mode == "nova":
        parts.append("You are Nova, a warm and helpful AI assistant in NovaOS.")
    elif persona_mode == "neutral":
        parts.append("You are a helpful AI assistant. Respond in a neutral, professional tone.")
    elif persona_mode == "professional":
        parts.append("You are a professional AI assistant. Respond formally and precisely.")
    
    parts.append(f"You are executing the custom command: #{cmd_config.get('name', 'unknown')}")
    
    # ─────────────────────────────────────────────────────────────────────
    # Output style instructions
    # ─────────────────────────────────────────────────────────────────────
    
    style = cmd_config.get("output_style", "natural")
    
    style_instructions = {
        "natural": "Respond naturally in a conversational tone.",
        "bullets": "Format your response as bullet points. Use • or - for each point.",
        "numbered": "Format your response as a numbered list (1., 2., 3., etc.).",
        "short": "Keep your response brief and concise (1-2 sentences maximum).",
        "verbose": "Provide a detailed, thorough response with full explanations.",
        "json": "Respond ONLY with valid JSON. No additional text or explanation.",
    }
    
    if style in style_instructions:
        parts.append(style_instructions[style])
    
    # ─────────────────────────────────────────────────────────────────────
    # Strict mode constraints
    # ─────────────────────────────────────────────────────────────────────
    
    if cmd_config.get("strict", False):
        parts.append(
            "IMPORTANT: Follow instructions exactly. "
            "Do not add extra commentary, explanations, or creative additions. "
            "Do not improvise or deviate from what is asked."
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Few-shot examples
    # ─────────────────────────────────────────────────────────────────────
    
    examples = cmd_config.get("examples", [])
    if examples:
        parts.append("\nHere are examples of how to respond:")
        for i, ex in enumerate(examples, 1):
            parts.append(f"\nExample {i}:")
            parts.append(f"Input: {ex['input']}")
            parts.append(f"Output: {ex['output']}")
        parts.append("\nNow respond to the user's input following these patterns.")
    
    return "\n".join(parts)


def render_user_prompt(cmd_config: dict, args: dict) -> str:
    """
    Render the user prompt from the command's template and arguments.
    
    Supports {{variable}} placeholders that are replaced with values from args.
    """
    template = cmd_config.get("prompt_template", "{{full_input}}")
    input_map = cmd_config.get("input_mapping", {"full_input": "full_input"})
    
    # Extract values from args
    rendered_vars = {}
    for var, source in input_map.items():
        if source == "full_input":
            rendered_vars[var] = args.get("full_input", "")
        elif source in args:
            rendered_vars[var] = args[source]
        else:
            rendered_vars[var] = ""
    
    # Render template
    prompt = template
    for var, val in rendered_vars.items():
        placeholder = "{{" + var + "}}"
        prompt = prompt.replace(placeholder, str(val))
    
    return prompt


# =============================================================================
# COMMAND EXECUTION
# =============================================================================

def execute_custom_prompt_command(
    kernel: Any,
    cmd_name: str,
    cmd_config: dict,
    args: dict,
    session_id: str,
) -> CommandResponse:
    """
    Execute an enhanced custom prompt command.
    
    This function:
    1. Builds the system prompt with style/strict/persona/examples
    2. Renders the user prompt from the template
    3. Calls complete_system() with the appropriate model tier
    4. Returns a formatted CommandResponse
    
    The complete_system() call triggers:
    - ModelRouter routing + logging
    - Correct model selection (mini or thinking)
    - Standard LLM logging
    """
    # Build prompts
    system_prompt = build_system_prompt(cmd_config)
    user_prompt = render_user_prompt(cmd_config, args)
    
    if not user_prompt.strip():
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"No input provided for #{cmd_name}",
            error_code="MISSING_INPUT",
            error_message="No input provided",
        )
    
    # Determine model tier
    intensive = cmd_config.get("intensive", False)
    
    # Execute LLM call via complete_system()
    # This triggers ModelRouter + logging automatically
    result = kernel.llm_client.complete_system(
        system=system_prompt,
        user=user_prompt,
        command=cmd_name,
        session_id=session_id,
        think_mode=intensive,  # intensive=True → gpt-5.1
    )
    
    output_text = result.get("text", "").strip()
    model_used = result.get("model", "unknown")
    
    # Format response
    summary = F.header(cmd_name.replace("-", " ").title()) + output_text
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data={
            "result": output_text,
            "model": model_used,
            "intensive": intensive,
            "output_style": cmd_config.get("output_style", "natural"),
        },
        type=cmd_name,
    )


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def format_command_for_list(name: str, cmd_config: dict) -> str:
    """
    Format a custom command for display in command-list.
    Shows enhanced metadata.
    """
    status = "enabled" if cmd_config.get("enabled", True) else "disabled"
    kind = cmd_config.get("kind", "prompt")
    tier = "🧠" if cmd_config.get("intensive") else "⚡"  # 🧠=thinking, ⚡=mini
    style = cmd_config.get("output_style", "natural")
    
    # Build tag string
    tags = [f"{kind}", f"{status}", f"{tier}"]
    if style != "natural":
        tags.append(f"style:{style}")
    if cmd_config.get("strict"):
        tags.append("strict")
    if cmd_config.get("examples"):
        tags.append(f"{len(cmd_config['examples'])} examples")
    
    return f"{name} [{', '.join(tags)}]"


def format_command_for_inspect(cmd_config: dict) -> str:
    """
    Format a custom command for detailed inspection.
    Shows all enhanced metadata clearly.
    """
    lines = []
    
    # Basic info
    lines.append(F.key_value("Name", cmd_config.get("name", "?")))
    lines.append(F.key_value("Kind", cmd_config.get("kind", "prompt")))
    lines.append(F.key_value("Enabled", cmd_config.get("enabled", True)))
    
    # v0.7.16 Enhanced fields
    lines.append("")
    lines.append(F.subheader("Model Settings"))
    intensive = cmd_config.get("intensive", False)
    tier = "thinking (gpt-5.1)" if intensive else "mini (gpt-4.1-mini)"
    lines.append(F.key_value("Model Tier", tier))
    lines.append(F.key_value("Intensive", intensive))
    
    lines.append("")
    lines.append(F.subheader("Output Settings"))
    lines.append(F.key_value("Output Style", cmd_config.get("output_style", "natural")))
    lines.append(F.key_value("Strict Mode", cmd_config.get("strict", False)))
    lines.append(F.key_value("Persona Mode", cmd_config.get("persona_mode", "nova")))
    
    # Examples
    examples = cmd_config.get("examples", [])
    if examples:
        lines.append("")
        lines.append(F.subheader(f"Examples ({len(examples)})"))
        for i, ex in enumerate(examples, 1):
            lines.append(f"  {i}. Input: {ex.get('input', '')[:50]}...")
            lines.append(f"     Output: {ex.get('output', '')[:50]}...")
    
    # Prompt template
    template = cmd_config.get("prompt_template", "")
    if template:
        lines.append("")
        lines.append(F.subheader("Prompt Template"))
        # Truncate if too long
        if len(template) > 200:
            lines.append(f"  {template[:200]}...")
        else:
            lines.append(f"  {template}")
    
    return "\n".join(lines)


# =============================================================================
# DOCUMENTATION
# =============================================================================

"""
┌─────────────────────────────────────────────────────────────────────────────┐
│ QUICK REFERENCE: Creating Enhanced Custom Commands                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ BASIC COMMAND (uses gpt-4.1-mini, natural style):                           │
│                                                                             │
│   #command-add name=greet kind=prompt prompt_template="Say hello to {{name}}"│
│                                                                             │
│ INTENSIVE COMMAND (uses gpt-5.1):                                           │
│                                                                             │
│   #command-add name=deep-analyze kind=prompt \\                              │
│       prompt_template="Analyze this deeply: {{full_input}}" \\               │
│       intensive=true                                                        │
│                                                                             │
│ STYLED COMMAND (bullet output):                                             │
│                                                                             │
│   #command-add name=summarize kind=prompt \\                                 │
│       prompt_template="Summarize: {{full_input}}" \\                         │
│       output_style=bullets                                                  │
│                                                                             │
│ STRICT COMMAND (no improvisation):                                          │
│                                                                             │
│   #command-add name=translate kind=prompt \\                                 │
│       prompt_template="Translate to Korean: {{full_input}}" \\               │
│       strict=true                                                           │
│                                                                             │
│ FULL EXAMPLE (all options):                                                 │
│                                                                             │
│   #command-add name=daily-reflect kind=prompt \\                             │
│       prompt_template="Reflect on: {{full_input}}" \\                        │
│       intensive=true \\                                                      │
│       output_style=bullets \\                                                │
│       strict=true \\                                                         │
│       persona_mode=professional                                             │
│                                                                             │
│ MODEL SELECTION:                                                            │
│   intensive=false (default) → gpt-4.1-mini (fast, ~300ms)                   │
│   intensive=true            → gpt-5.1 (deep reasoning, ~1-2s)               │
│                                                                             │
│ OUTPUT STYLES:                                                              │
│   natural   → conversational (default)                                      │
│   bullets   → bullet point list                                             │
│   numbered  → numbered list                                                 │
│   short     → 1-2 sentences                                                 │
│   verbose   → detailed explanation                                          │
│   json      → structured JSON only                                          │
│                                                                             │
│ PERSONA MODES:                                                              │
│   nova         → warm, helpful (default)                                    │
│   neutral      → professional, no personality                               │
│   professional → formal, business-like                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""
