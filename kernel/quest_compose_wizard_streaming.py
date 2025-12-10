# =============================================================================
# v0.10.3: STREAMING SUPPORT FOR QUEST COMPOSE
# =============================================================================
#
# Add this function to kernel/quest_compose_wizard.py
# Place it AFTER the existing _generate_steps_with_llm function
#
# This provides a streaming version that yields progress events instead of
# blocking until completion. Used by /nova/stream for real-time UI updates.
# =============================================================================

def _generate_steps_with_llm_streaming(
    draft: Dict[str, Any], 
    kernel: Any,
    session_id: str,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming version of step generation that yields progress events.
    
    v0.10.3: NEW - Streaming generator for QuestCompose.
    
    Instead of blocking until all steps are generated, this yields events:
    - {"type": "log", "message": "..."} - Log messages
    - {"type": "progress", "message": "...", "percent": N} - Progress updates
    - {"type": "update", "content": "..."} - Partial content previews
    - {"type": "steps", "steps": [...]} - Final generated steps
    - {"type": "error", "message": "..."} - Error occurred
    
    This allows the frontend to show real-time progress during the heavy
    LLM generation phases (outline + content), avoiding Cloudflare 524 timeouts.
    
    Args:
        draft: Quest draft dictionary with title, objectives, domains, etc.
        kernel: NovaKernel instance
        session_id: Session ID for logging
    
    Yields:
        Dict events with type and payload
    """
    def _log(msg: str):
        return {"type": "log", "message": f"[QuestCompose] {msg}"}
    
    def _progress(msg: str, pct: int):
        return {"type": "progress", "message": msg, "percent": pct}
    
    def _update(content: str):
        return {"type": "update", "content": content}
    
    def _steps(steps_list: List[Dict[str, Any]]):
        return {"type": "steps", "steps": steps_list}
    
    def _error(msg: str):
        return {"type": "error", "message": msg}
    
    try:
        yield _log("Starting domain-balanced generation...")
        yield _progress("Initializing...", 5)
        
        # Get LLM client from kernel
        llm_client = getattr(kernel, 'llm_client', None)
        if not llm_client:
            yield _error("No LLM client available")
            return
        
        title = draft.get("title", "Untitled Quest")
        category = draft.get("category", "general")
        objectives = draft.get("objectives", [])
        
        yield _log(f"Quest: {title}")
        yield _log(f"Objectives: {len(objectives)}")
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 1: USE CONFIRMED DOMAINS
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 1: Loading confirmed domains...", 10)
        
        domains = draft.get("domains", [])
        
        if domains:
            yield _log(f"Using {len(domains)} confirmed domains")
            for d in domains:
                domain_name = d.get("name", "?")
                subtopics = d.get("subtopics", [])
                yield _log(f"  - {domain_name}: {len(subtopics)} subtopics")
        else:
            # Fallback: extract from objectives
            yield _log("No confirmed domains, extracting from objectives...")
            yield _progress("Phase 1: Extracting domains from objectives...", 12)
            
            domains = _extract_domains_from_objectives(objectives, llm_client)
            yield _log(f"Extracted {len(domains)} domains")
        
        if not domains:
            yield _log("Warning: No domains found, using single-shot fallback")
            yield _progress("Using fallback generation...", 15)
            
            # Use single-shot fallback
            steps = _generate_single_shot_fallback(draft, kernel)
            if steps:
                yield _steps(steps)
            else:
                yield _error("Could not generate steps")
            return
        
        # Calculate target steps
        total_subtopics = sum(len(d.get("subtopics", [])) for d in domains)
        steps_per_subtopic = 2
        boss_steps = len(domains)
        target_steps = max(10, (total_subtopics * steps_per_subtopic) + boss_steps)
        target_steps = min(target_steps, 45)
        
        yield _log(f"Target: {target_steps} steps across {len(domains)} domains")
        yield _progress("Phase 1 complete", 20)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 2: GENERATE SUBTOPIC-AWARE OUTLINE
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 2: Generating outline...", 25)
        yield _log("Creating subtopic-aware outline with LLM...")
        
        # Build domain list text for prompt
        domain_list_text = ""
        for d in domains:
            domain_name = d.get("name", "Unknown")
            subtopics = d.get("subtopics", [])
            if subtopics:
                subtopic_str = ", ".join(subtopics)
                domain_list_text += f"- {domain_name}: [{subtopic_str}]\n"
            else:
                domain_list_text += f"- {domain_name}: (general coverage)\n"
        
        outline_system = """You are a curriculum architect for NovaOS micro-learning.
Create a detailed day-by-day outline that ensures ALL subtopics are covered.

RULES:
1. Every subtopic MUST appear in at least one step
2. Each domain ends with exactly ONE BOSS step
3. BOSS steps integrate 2-4 subtopics into a capstone
4. Distribute subtopics evenly across the timeline

Output ONLY valid JSON. No markdown."""

        outline_user = f"""Create a {target_steps}-step outline for "{title}".

DOMAINS AND SUBTOPICS TO COVER:
{domain_list_text}

OUTPUT THIS EXACT JSON STRUCTURE:
{{
  "total_steps": {target_steps},
  "outline": [
    {{"day": 1, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Intro to Subtopic A", "step_type": "INFO"}},
    {{"day": 2, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Hands-on with Subtopic A", "step_type": "APPLY"}},
    {{"day": 3, "domain": "Domain Name", "subtopics": ["Subtopic B"], "topic": "Learn Subtopic B", "step_type": "INFO"}},
    {{"day": 4, "domain": "Domain Name", "subtopics": ["Subtopic A", "Subtopic B"], "topic": "Domain Capstone", "step_type": "BOSS"}}
  ]
}}

JSON only:"""

        yield _log("Calling LLM for outline generation...")
        
        outline_steps = []
        try:
            # Use streaming LLM call for outline
            outline_text = ""
            for chunk in llm_client.stream_complete_system(
                system=outline_system,
                user=outline_user,
                command="quest-compose-outline-stream",
                think_mode=True,
            ):
                outline_text += chunk
                # Yield periodic updates so connection stays alive
                if len(outline_text) % 200 == 0:
                    yield _log(f"Generating outline... ({len(outline_text)} chars)")
            
            yield _progress("Phase 2: Parsing outline...", 35)
            
            # Parse the outline JSON
            start_idx = outline_text.find('{')
            end_idx = outline_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx > 0:
                outline_json = outline_text[start_idx:end_idx]
                parsed = json.loads(outline_json)
                outline_steps = parsed.get("outline", [])
                yield _log(f"Parsed {len(outline_steps)} outline steps")
            
        except Exception as e:
            yield _log(f"Outline LLM error: {e}")
            yield _log("Using programmatic outline fallback...")
            outline_steps = _generate_programmatic_outline(domains, target_steps)
        
        if not outline_steps:
            yield _log("Using programmatic outline fallback...")
            outline_steps = _generate_programmatic_outline(domains, target_steps)
        
        yield _progress("Phase 2 complete", 40)
        yield _update(f"Outline: {len(outline_steps)} steps planned")
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 3: GENERATE CONTENT PER DOMAIN (STREAMING)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 3: Generating step content...", 45)
        
        # Group outline by domain
        domain_outlines = {}
        for step in outline_steps:
            domain = step.get("domain", "Unknown")
            if domain not in domain_outlines:
                domain_outlines[domain] = []
            domain_outlines[domain].append(step)
        
        all_steps = []
        domain_count = len(domain_outlines)
        processed_domains = 0
        
        for domain_name, domain_outline in domain_outlines.items():
            processed_domains += 1
            base_percent = 45 + int((processed_domains / domain_count) * 45)
            
            yield _log(f"Generating content for domain: {domain_name}")
            yield _progress(f"Domain {processed_domains}/{domain_count}: {domain_name}", base_percent)
            
            # Get subtopics for this domain
            domain_info = next((d for d in domains if d.get("name") == domain_name), {})
            subtopics = domain_info.get("subtopics", [])
            
            # Build outline text for this domain
            domain_outline_text = ""
            for i, step in enumerate(domain_outline, 1):
                step_type = step.get("step_type", "INFO")
                topic = step.get("topic", f"Step {i}")
                step_subtopics = step.get("subtopics", [])
                domain_outline_text += f"{i}. [{step_type}] {topic} (subtopics: {step_subtopics})\n"
            
            content_system = """You are a micro-learning content designer.

HARD CONSTRAINTS:
1. Each step = 60-90 minutes (tired working adult)
2. EXACTLY 3-4 actions per step
3. Each action = 15-25 minutes, specific and completable
4. ONE theme per step

STEP TYPES:
- INFO: Reading, videos, studying concepts
- APPLY: Hands-on labs, building, testing
- RECALL: Flashcards, quizzes, summaries
- BOSS: Capstone challenge, multi-step scenario

Output ONLY JSON array. No markdown."""

            content_user = f"""Generate micro-step content for "{domain_name}".

**Quest:** {title}
**Subtopics to cover:** {subtopics}

**Steps to generate:**
{domain_outline_text}

Generate a JSON array with EXACTLY {len(domain_outline)} steps:
[
  {{
    "step_type": "INFO",
    "title": "Day X: Topic",
    "prompt": "Today's goal (2-3 sentences)",
    "actions": ["15-25 min task", "15-25 min task", "15-25 min task"],
    "subtopics": ["from input"]
  }}
]

JSON array only:"""

            try:
                # Stream content generation
                content_text = ""
                for chunk in llm_client.stream_complete_system(
                    system=content_system,
                    user=content_user,
                    command="quest-compose-content-stream",
                    think_mode=True,
                ):
                    content_text += chunk
                    # Keep connection alive
                    if len(content_text) % 300 == 0:
                        yield _log(f"  Generating content... ({len(content_text)} chars)")
                
                # Parse content
                start_idx = content_text.find('[')
                end_idx = content_text.rfind(']') + 1
                
                if start_idx != -1 and end_idx > 0:
                    content_json = content_text[start_idx:end_idx]
                    content_steps = json.loads(content_json)
                    
                    # Normalize and add steps
                    step_num = len(all_steps) + 1
                    for step_data in content_steps:
                        if not isinstance(step_data, dict):
                            continue
                        
                        step_type = _normalize_step_type(step_data)
                        actions = step_data.get("actions", [])
                        if not isinstance(actions, list):
                            actions = []
                        actions = [str(a) for a in actions if a][:4]  # Max 4 actions
                        
                        step = {
                            "id": f"step_{step_num}",
                            "type": step_type,
                            "prompt": step_data.get("prompt", step_data.get("description", "")),
                            "title": step_data.get("title", f"Step {step_num}"),
                            "actions": actions,
                            "subtopics": step_data.get("subtopics", []),
                            "_domain": domain_name,
                            "_generation_mode": "streaming",
                        }
                        
                        if step["prompt"]:
                            all_steps.append(step)
                            step_num += 1
                    
                    yield _log(f"  Generated {len(content_steps)} steps for {domain_name}")
                
            except Exception as e:
                yield _log(f"  Content generation error for {domain_name}: {e}")
                # Continue with other domains
        
        yield _progress("Phase 3 complete", 95)
        
        # ═══════════════════════════════════════════════════════════════════════
        # FINALIZE
        # ═══════════════════════════════════════════════════════════════════════
        if all_steps:
            yield _log(f"Generation complete: {len(all_steps)} total steps")
            yield _progress("Complete!", 100)
            yield _steps(all_steps)
        else:
            yield _log("No steps generated, trying single-shot fallback...")
            yield _progress("Using fallback...", 98)
            
            fallback_steps = _generate_single_shot_fallback(draft, kernel)
            if fallback_steps:
                yield _steps(fallback_steps)
            else:
                yield _error("Could not generate steps after all attempts")
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield _error(f"Generation failed: {str(e)}")


def _normalize_step_type(step_data: Dict[str, Any]) -> str:
    """Normalize step type from various formats."""
    step_type = step_data.get("step_type", step_data.get("type", "info"))
    step_type = str(step_type).lower()
    
    valid_types = {"info", "recall", "apply", "reflect", "boss", "action", "transfer", "mini_boss"}
    if step_type not in valid_types:
        step_type = "info"
    
    return step_type


# =============================================================================
# INTEGRATION NOTES
# =============================================================================
#
# 1. Add the import at the top of quest_compose_wizard.py:
#    from typing import Generator
#
# 2. Add the _generate_steps_with_llm_streaming function above
#
# 3. Make sure these existing helper functions are available:
#    - _generate_programmatic_outline (already exists)
#    - _generate_single_shot_fallback (already exists)
#    - _format_steps_with_actions (already exists)
#    - _base_response (already exists)
#    - _extract_domains_from_objectives (may need to add if not present)
#
# 4. The nova_api.py imports this function:
#    from kernel.quest_compose_wizard import _generate_steps_with_llm_streaming
#
# =============================================================================
