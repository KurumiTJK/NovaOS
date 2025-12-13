# kernel/routing/__init__.py
"""
NovaOS Routing Subpackage

Contains:
- nl_router: Natural language intent detection and routing
- syscommand_router: Syscommand dispatch to handlers
- section_defs: Section definitions (core, memory, modules, etc.)
- section_handlers: Section menu handlers

All symbols are re-exported for backward compatibility.
"""

from .nl_router import (
    IntentMatch,
    IntentPatterns,
    NaturalLanguageRouter,
    EXTRACTORS,
    QUEST_SUGGESTION_PATTERNS,
    route_natural_language,
    check_quest_suggestion,
    debug_nl_intent,
)

from .syscommand_router import (
    SyscommandRouter,
    SKIP_LLM_POSTPROCESS,
)

from .section_defs import (
    CommandInfo,
    Section,
    SECTION_DEFS,
    get_section_keys,
    get_section,
    get_section_commands,
    get_section_title,
    get_section_description,
    find_section_for_command,
    get_all_command_names,
)

from .section_handlers import (
    SectionMenuState,
    handle_help_sectioned,
    handle_section_menu,
    handle_section_menu_selection,
    clear_section_menu,
    get_active_section_menu,
    route_section_command,
    parse_section_input,
    create_section_menu_handler,
    SECTION_MENU_HANDLERS,
)

__all__ = [
    # nl_router
    "IntentMatch",
    "IntentPatterns",
    "NaturalLanguageRouter",
    "EXTRACTORS",
    "QUEST_SUGGESTION_PATTERNS",
    "route_natural_language",
    "check_quest_suggestion",
    "debug_nl_intent",
    # syscommand_router
    "SyscommandRouter",
    "SKIP_LLM_POSTPROCESS",
    # section_defs
    "CommandInfo",
    "Section",
    "SECTION_DEFS",
    "get_section_keys",
    "get_section",
    "get_section_commands",
    "get_section_title",
    "get_section_description",
    "find_section_for_command",
    "get_all_command_names",
    # section_handlers
    "SectionMenuState",
    "handle_help_sectioned",
    "handle_section_menu",
    "handle_section_menu_selection",
    "clear_section_menu",
    "get_active_section_menu",
    "route_section_command",
    "parse_section_input",
    "create_section_menu_handler",
    "SECTION_MENU_HANDLERS",
]
