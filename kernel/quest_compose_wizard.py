# kernel/quest_compose_wizard.py
"""
SHIM: This module has moved to kernel/quests/quest_compose_wizard.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.quests.quest_compose_wizard directly.
"""

# Public exports
from kernel.quests.quest_compose_wizard import *

# Private functions that are used externally (import * doesn't export these)
from kernel.quests.quest_compose_wizard import (
    _base_response,
    _error_response,
    _generate_quest_id,
    _parse_steps_input,
    _parse_list_input,
    _calculate_difficulty,
    _get_difficulty_label,
    _get_default_validation,
    _format_steps_with_actions,
    _format_preview,
    _build_quest_dict,
    _prefill_from_args,
    _advance_to_next_missing,
    _get_current_prompt,
    _get_module_list,
    _get_available_modules,
    _process_wizard_input,
    _handle_metadata_stage,
    _handle_objectives_stage,
    _trigger_domain_extraction,
    _extract_domains_for_review,
    _format_domain_list_for_review,
    _handle_domain_review_stage,
    _handle_manual_domain_input,
    _handle_subdomain_review_stage,
    _handle_manual_subdomain_input,
    _get_manual_subdomain_prompt,
    _get_subdomain_review_prompt,
    _trigger_subdomain_generation,
    _validate_and_repair_subdomains,
    _dedupe_intra_domain,
    _enforce_keystones,
    _get_forbidden_keywords_for_domain,
    _check_cross_domain_reference,
    _generate_fallback_subdomains,
    _generate_subtopic_patch_steps,
    _generate_programmatic_outline,
    _generate_steps_with_llm,
    _generate_steps_with_llm_streaming,
)
