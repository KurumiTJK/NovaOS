# kernel/lesson_engine/step_builder.py
"""
v4.0.0 — Lesson Engine: Daily Learning Step Builder

Designed for WORKING ADULTS with limited time (~30-60 min/day).

PHILOSOPHY:
- Each step = 1 day of realistic learning after work
- Focus on LEARNING, not busywork
- Small, achievable wins build momentum
- Quality understanding > quantity of tasks

STRUCTURE PER DOMAIN:
  Domain: Networking (5 subdomains)
  ├── Day 1: Routing - Learn core concept + tiny practice
  ├── Day 2: VLANs - Learn core concept + tiny practice
  ├── Day 3: DNS - Learn core concept + tiny practice
  ├── Day 4: Segmentation - Learn core concept + tiny practice
  └── Day 5: BOSS - Practical that ties it all together

STEP STRUCTURE (30-60 min total):
  1. Learn (15-25 min): Read/watch ONE focused resource
  2. Practice (10-20 min): ONE small exercise to cement understanding
  3. Check (5-10 min): Quick self-verification

NOT:
  - Multi-hour labs
  - "Build a complete system from scratch"
  - "Write 5 scripts"
  - "Design a full architecture"
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

from .schemas import (
    EvidencePack,
    EvidenceResource,
    LessonStep,
    LessonManifest,
    validate_subdomain_coverage,
)


# =============================================================================
# TIME CONSTANTS (realistic for working adults)
# =============================================================================

# Daily time budget
MIN_DAILY_TIME = 30   # Minimum realistic daily commitment
MAX_DAILY_TIME = 60   # Maximum before burnout
TARGET_DAILY_TIME = 45  # Sweet spot

# Action budgets within daily time
LEARN_TIME_MIN = 15
LEARN_TIME_MAX = 25
PRACTICE_TIME_MIN = 10
PRACTICE_TIME_MAX = 20
CHECK_TIME_MIN = 5
CHECK_TIME_MAX = 10


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def build_steps_streaming(
    evidence_packs: List[EvidencePack],
    quest_title: str,
    manifest: Optional[LessonManifest] = None,
    llm_client: Any = None,
) -> Generator[Dict[str, Any], None, List[LessonStep]]:
    """
    Build daily learning steps from evidence packs.
    
    Each subdomain = 1 day of learning.
    Last subdomain of each domain = BOSS (synthesis).
    
    Yields progress updates, returns final steps.
    """
    yield {"type": "log", "message": f"[StepBuilder] Building daily steps for {len(evidence_packs)} subdomains"}
    
    all_steps: List[LessonStep] = []
    step_counter = 1
    total_packs = len(evidence_packs)
    
    # Group by domain to identify BOSS positions
    domain_packs: Dict[str, List[Tuple[int, EvidencePack]]] = {}
    for i, pack in enumerate(evidence_packs):
        domain = pack.domain or "General"
        if domain not in domain_packs:
            domain_packs[domain] = []
        domain_packs[domain].append((i, pack))
    
    # Find BOSS indices (last subdomain per domain)
    boss_indices = set()
    for domain, packs in domain_packs.items():
        if packs:
            boss_indices.add(packs[-1][0])
    
    # Track processed to prevent duplicates
    processed: Set[str] = set()
    
    for i, pack in enumerate(evidence_packs):
        # Skip duplicates
        key = f"{pack.domain}::{pack.subdomain}".lower()
        if key in processed:
            yield {"type": "log", "message": f"[StepBuilder] Skipping duplicate: {pack.subdomain}"}
            continue
        processed.add(key)
        
        # Progress update
        percent = int(((i + 1) / total_packs) * 100)
        yield {
            "type": "progress",
            "message": f"Building: {pack.subdomain}",
            "percent": percent,
        }
        
        is_boss = i in boss_indices
        
        # Build ONE step per subdomain (daily learning unit)
        step = _build_daily_step(
            pack=pack,
            step_num=step_counter,
            is_boss=is_boss,
            llm_client=llm_client,
        )
        
        yield {"type": "log", "message": f"[StepBuilder] Day {step_counter}: {step.title} ({step.estimated_time_minutes} min)"}
        
        all_steps.append(step)
        step_counter += 1
    
    yield {"type": "log", "message": f"[StepBuilder] Complete: {len(all_steps)} daily steps"}
    
    return all_steps


# =============================================================================
# DAILY STEP BUILDER
# =============================================================================

def _build_daily_step(
    pack: EvidencePack,
    step_num: int,
    is_boss: bool,
    llm_client: Any = None,
) -> LessonStep:
    """
    Build a single daily learning step.
    
    Regular step (30-45 min):
        1. Learn: Read/watch ONE resource
        2. Practice: ONE small exercise
        3. Check: Quick verification
    
    BOSS step (45-60 min):
        1. Review: Quick recap of domain concepts
        2. Challenge: Practical mini-project tying concepts together
        3. Reflect: What did you learn? What's still fuzzy?
    """
    
    if is_boss:
        return _build_boss_step(pack, step_num, llm_client)
    else:
        return _build_learning_step(pack, step_num, llm_client)


def _build_learning_step(
    pack: EvidencePack,
    step_num: int,
    llm_client: Any = None,
) -> LessonStep:
    """
    Build a regular daily learning step.
    
    Structure:
        Learn (20 min): ONE focused resource
        Practice (15 min): ONE small hands-on exercise
        Check (5 min): Quick self-test
    """
    
    subdomain = pack.subdomain
    domain = pack.domain or "General"
    
    # Select best resource for learning
    learn_resource = _select_best_resource(pack.resources)
    
    # Build actions
    actions = []
    
    # 1. LEARN (20 min)
    if learn_resource:
        learn_action = _create_learn_action(learn_resource, subdomain, 20)
    else:
        learn_action = {
            "type": "learn",
            "description": f"Research {subdomain} - find one quality article or video explaining the core concepts",
            "time_minutes": 20,
            "deliverable": f"Write 3 bullet points summarizing what {subdomain} is and why it matters",
        }
    actions.append(learn_action)
    
    # 2. PRACTICE (15 min) - ONE small exercise
    practice_action = _create_practice_action(subdomain, domain, 15)
    actions.append(practice_action)
    
    # 3. CHECK (5 min) - Quick verification
    check_action = _create_check_action(subdomain, 5)
    actions.append(check_action)
    
    # Calculate total time
    total_time = sum(a.get("time_minutes", 0) for a in actions)
    
    # Convert actions to simple string list for LessonStep
    action_strings = [a.get("description", str(a)) for a in actions]
    
    return LessonStep(
        step_id=f"day-{step_num:02d}",
        title=f"{subdomain}",
        step_type="INFO",
        estimated_time_minutes=total_time,
        goal=f"Learn the fundamentals of {subdomain} and practice with a small exercise.",
        actions=action_strings,
        completion_check=f"Can explain {subdomain} in your own words and completed the practice exercise",
        resource_refs=[r.url for r in pack.resources if r.url][:3],
        subdomain=subdomain,
        domain=domain,
        subdomains_covered=[subdomain],
    )


def _build_boss_step(
    pack: EvidencePack,
    step_num: int,
    llm_client: Any = None,
) -> LessonStep:
    """
    Build a BOSS step - synthesis challenge for the domain.
    
    Structure:
        Review (10 min): Quick recap of domain concepts
        Challenge (35 min): Practical mini-project
        Reflect (10 min): Self-assessment
    """
    
    subdomain = pack.subdomain
    domain = pack.domain or "General"
    
    actions = []
    
    # 1. REVIEW (10 min)
    review_action = {
        "type": "review",
        "description": f"Quick review: Skim your notes from previous {domain} days. What are the key concepts?",
        "time_minutes": 10,
        "deliverable": f"List the 5 most important things you learned about {domain}",
    }
    actions.append(review_action)
    
    # 2. CHALLENGE (35 min) - Mini practical project
    challenge_action = _create_boss_challenge(domain, subdomain, 35)
    actions.append(challenge_action)
    
    # 3. REFLECT (10 min)
    reflect_action = {
        "type": "reflect",
        "description": "Self-assessment: What clicked? What's still fuzzy? What would you like to explore more?",
        "time_minutes": 10,
        "deliverable": "Write a short reflection (3-5 sentences) on your understanding of this domain",
    }
    actions.append(reflect_action)
    
    total_time = sum(a.get("time_minutes", 0) for a in actions)
    
    # Convert actions to simple string list for LessonStep
    action_strings = [a.get("description", str(a)) for a in actions]
    
    return LessonStep(
        step_id=f"day-{step_num:02d}",
        title=f"BOSS: {domain} Synthesis",
        step_type="BOSS",
        estimated_time_minutes=total_time,
        goal=f"Put your {domain} knowledge together with a practical challenge.",
        actions=action_strings,
        completion_check=f"Completed the {domain} challenge and can connect different concepts together",
        resource_refs=[r.url for r in pack.resources if r.url][:2],
        subdomain=subdomain,
        domain=domain,
        subdomains_covered=[subdomain],
    )


# =============================================================================
# ACTION BUILDERS
# =============================================================================

def _create_learn_action(
    resource: EvidenceResource,
    subdomain: str,
    time_minutes: int,
) -> Dict[str, Any]:
    """Create a learning action from a resource."""
    
    # Determine resource type
    url = resource.url or ""
    title = resource.title or subdomain
    
    if "youtube.com" in url or "youtu.be" in url:
        action_type = "watch"
        verb = "Watch"
    elif url.endswith(".pdf"):
        action_type = "read"
        verb = "Read"
    else:
        action_type = "read"
        verb = "Read/skim"
    
    return {
        "type": action_type,
        "description": f"{verb}: {title}",
        "time_minutes": time_minutes,
        "url": url if url else None,
        "deliverable": f"Write 3 key takeaways about {subdomain}",
    }


def _create_practice_action(
    subdomain: str,
    domain: str,
    time_minutes: int,
) -> Dict[str, Any]:
    """
    Create a small, achievable practice action.
    
    NOT: "Build a complete lab from scratch"
    YES: "Try one command/config and observe the result"
    """
    
    # Generate practice based on subdomain keywords
    subdomain_lower = subdomain.lower()
    
    # Detect topic type and generate appropriate small exercise
    practice = _get_small_practice(subdomain_lower, subdomain, domain)
    
    return {
        "type": "practice",
        "description": practice["description"],
        "time_minutes": time_minutes,
        "deliverable": practice["deliverable"],
    }


def _get_small_practice(subdomain_lower: str, subdomain: str, domain: str) -> Dict[str, str]:
    """
    Generate a SMALL, achievable practice exercise.
    
    Principle: One focused task, not a project.
    """
    
    # Networking topics
    if any(kw in subdomain_lower for kw in ["routing", "route"]):
        return {
            "description": "Run `ip route` (Linux) or `route print` (Windows) and identify: default gateway, any static routes",
            "deliverable": "Screenshot of route table with default gateway highlighted",
        }
    
    if any(kw in subdomain_lower for kw in ["vlan", "segmentation"]):
        return {
            "description": "Draw a simple diagram showing 2 VLANs (HR, Engineering) with a router between them",
            "deliverable": "Hand-drawn or digital diagram showing VLAN separation concept",
        }
    
    if "dns" in subdomain_lower:
        return {
            "description": "Use `nslookup` or `dig` to query 3 different record types (A, MX, TXT) for a domain you own or a public domain",
            "deliverable": "Screenshot showing the 3 queries and their results",
        }
    
    # Active Directory topics
    if any(kw in subdomain_lower for kw in ["active directory", "ad ", "trust", "gpo"]):
        return {
            "description": "If you have AD access: run `gpresult /r` to see applied GPOs. If not: diagram what a GPO inheritance chain looks like",
            "deliverable": "GPO output screenshot OR hand-drawn GPO inheritance diagram",
        }
    
    # Identity topics
    if any(kw in subdomain_lower for kw in ["oauth", "oidc", "saml", "jwt", "identity", "mfa"]):
        return {
            "description": "Decode a sample JWT token at jwt.io - identify the header, payload sections and what claims are present",
            "deliverable": "Screenshot of decoded JWT with 3 claims you identified labeled",
        }
    
    # AWS topics
    if "iam" in subdomain_lower:
        return {
            "description": "In AWS console (or read a sample policy): identify what a policy allows/denies. What's the Effect, Action, Resource?",
            "deliverable": "Write out one IAM policy in plain English: 'This policy allows X to do Y on Z'",
        }
    
    if any(kw in subdomain_lower for kw in ["ec2", "s3", "aws"]):
        return {
            "description": "In AWS console: find the region selector. List 3 different regions and guess why you'd pick one over another",
            "deliverable": "List of 3 regions with one reason each for choosing that region",
        }
    
    # Azure topics
    if any(kw in subdomain_lower for kw in ["azure", "entra", "rbac"]):
        return {
            "description": "Look up Azure RBAC built-in roles. Find 3 roles and write what each can do in one sentence",
            "deliverable": "3 Azure roles with one-sentence descriptions",
        }
    
    # SIEM/Logging topics
    if any(kw in subdomain_lower for kw in ["logging", "siem", "cloudtrail", "sentinel"]):
        return {
            "description": "Find a sample log entry (CloudTrail, Syslog, or any log). Identify: timestamp, source, event type, relevant details",
            "deliverable": "Annotated log entry with 4 fields labeled",
        }
    
    # Threat modeling
    if any(kw in subdomain_lower for kw in ["threat", "stride", "attack"]):
        return {
            "description": "Pick a simple app (like a todo app). Apply STRIDE: find one example threat for each letter",
            "deliverable": "STRIDE table with 6 rows, one threat per category",
        }
    
    # Docker topics
    if any(kw in subdomain_lower for kw in ["docker", "container", "image"]):
        return {
            "description": "Run `docker images` and `docker ps -a`. Identify one image and one container. What's the difference?",
            "deliverable": "Screenshot with one image and one container labeled, plus one sentence explaining the difference",
        }
    
    # Kubernetes topics
    if any(kw in subdomain_lower for kw in ["kubernetes", "k8s", "pod", "deployment"]):
        return {
            "description": "Read a sample Pod YAML. Identify: apiVersion, kind, metadata.name, container image, container port",
            "deliverable": "Annotated Pod YAML with 5 fields highlighted",
        }
    
    # CI/CD topics
    if any(kw in subdomain_lower for kw in ["ci/cd", "cicd", "pipeline", "github action"]):
        return {
            "description": "Find a sample GitHub Actions workflow. Identify: trigger event, jobs, steps within a job",
            "deliverable": "Annotated workflow YAML with trigger, job, and steps labeled",
        }
    
    # Default fallback - generic but still small
    return {
        "description": f"Find one real-world example of {subdomain}. Write down: what it is, one benefit, one challenge",
        "deliverable": f"3-sentence summary of a real {subdomain} example: what, benefit, challenge",
    }


def _create_check_action(subdomain: str, time_minutes: int) -> Dict[str, Any]:
    """Create a quick self-check action."""
    
    return {
        "type": "check",
        "description": f"Self-test: Without looking at notes, explain {subdomain} to an imaginary coworker in 2-3 sentences",
        "time_minutes": time_minutes,
        "deliverable": "If you struggled, review your notes. If it was easy, you're ready to move on!",
    }


def _create_boss_challenge(domain: str, subdomain: str, time_minutes: int) -> Dict[str, Any]:
    """
    Create a BOSS challenge that ties together domain concepts.
    
    NOT: "Build a complete production system"
    YES: "Apply 3-4 concepts together in a mini scenario"
    """
    
    domain_lower = domain.lower()
    
    # Domain-specific challenges
    if "network" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: You're setting up a small office network. Draw a diagram showing: 2 VLANs, routing between them, DNS server placement, and one security boundary",
            "time_minutes": time_minutes,
            "deliverable": "Network diagram with all 4 elements labeled and one paragraph explaining your design choices",
        }
    
    if "active directory" in domain_lower or domain_lower == "ad":
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design a simple AD structure for a company with 3 departments. Show: OUs, one GPO per department, and delegation for helpdesk",
            "time_minutes": time_minutes,
            "deliverable": "AD structure diagram with OUs, GPOs, and delegation noted. One paragraph on why you structured it this way",
        }
    
    if "identity" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Diagram an OAuth2 login flow for a web app. Show: user, app, authorization server, and what tokens move where",
            "time_minutes": time_minutes,
            "deliverable": "Sequence diagram of OAuth2 flow with 4 actors and token movements labeled",
        }
    
    if "aws" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Sketch an AWS setup for a simple web app. Show: VPC, public/private subnet, EC2, S3, and IAM role",
            "time_minutes": time_minutes,
            "deliverable": "AWS architecture diagram with 5 components. One paragraph on your IAM approach",
        }
    
    if "azure" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design an Azure identity setup for a hybrid company. Show: Entra ID, on-prem AD sync, and RBAC for 2 admin types",
            "time_minutes": time_minutes,
            "deliverable": "Azure identity diagram showing hybrid setup. One paragraph explaining the RBAC choices",
        }
    
    if "logging" in domain_lower or "siem" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design a log collection strategy. What 5 log sources would you collect first? Where would they go? One detection rule you'd create",
            "time_minutes": time_minutes,
            "deliverable": "Log collection diagram with 5 sources, destination, and one detection rule written out",
        }
    
    if "threat" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Threat model a login page. Apply STRIDE, identify top 3 risks, suggest one mitigation per risk",
            "time_minutes": time_minutes,
            "deliverable": "STRIDE analysis for login page with top 3 risks and mitigations",
        }
    
    if "docker" in domain_lower or "container" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design a containerized app with web frontend, API, and database. Sketch the docker-compose structure (don't need to write full YAML)",
            "time_minutes": time_minutes,
            "deliverable": "Docker architecture diagram showing 3 containers, networks, and volumes",
        }
    
    if "kubernetes" in domain_lower or "k8s" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design a K8s deployment for a web app. Show: Deployment, Service, ConfigMap, and how traffic flows in",
            "time_minutes": time_minutes,
            "deliverable": "K8s architecture diagram with 4 resources and traffic flow arrows",
        }
    
    if "ci/cd" in domain_lower or "pipeline" in domain_lower:
        return {
            "type": "challenge",
            "description": "Mini-scenario: Design a CI/CD pipeline for a web app. Show: stages (build, test, deploy), triggers, and one quality gate",
            "time_minutes": time_minutes,
            "deliverable": "Pipeline diagram with stages, triggers, and quality gate. One paragraph on your branching strategy",
        }
    
    # Generic fallback
    return {
        "type": "challenge",
        "description": f"Mini-scenario: Apply your {domain} knowledge to a realistic problem. Design a simple solution using 3-4 concepts you learned",
        "time_minutes": time_minutes,
        "deliverable": f"Diagram or outline showing how you'd apply {domain} concepts together",
    }


# =============================================================================
# RESOURCE SELECTION
# =============================================================================

def _select_best_resource(resources: List[EvidenceResource]) -> Optional[EvidenceResource]:
    """
    Select the single best resource for learning.
    
    Priority:
    1. Official docs (high quality, authoritative)
    2. Tutorials with good titles
    3. Videos (if short/focused)
    4. Any remaining resource
    """
    
    if not resources:
        return None
    
    # Score resources
    scored = []
    for r in resources:
        score = 0
        url = (r.url or "").lower()
        title = (r.title or "").lower()
        
        # Prefer official docs
        if any(d in url for d in ["docs.", "documentation", "learn.microsoft", "docs.aws", "kubernetes.io/docs"]):
            score += 10
        
        # Prefer tutorials
        if any(t in title for t in ["tutorial", "getting started", "introduction", "guide", "101"]):
            score += 5
        
        # Slight boost for videos (engaging)
        if "youtube.com" in url or "youtu.be" in url:
            score += 3
        
        # Penalize very long titles (often clickbait)
        if len(title) > 100:
            score -= 2
        
        scored.append((score, r))
    
    # Return highest scored
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


# =============================================================================
# LEGACY COMPATIBILITY
# =============================================================================

# Keep old function signature working
def build_steps_from_evidence(
    evidence_packs: List[EvidencePack],
    quest_title: str,
    manifest: Optional[LessonManifest] = None,
    llm_client: Any = None,
) -> Generator[Dict[str, Any], None, List[LessonStep]]:
    """Legacy alias for build_steps_streaming."""
    return build_steps_streaming(evidence_packs, quest_title, manifest, llm_client)


# =============================================================================
# STORAGE FUNCTIONS
# =============================================================================

def save_raw_steps(steps: List[LessonStep], data_dir) -> bool:
    """Save raw steps to JSON file."""
    import json
    from pathlib import Path
    
    try:
        data_dir = Path(data_dir)
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "raw_steps.json"
        
        steps_data = [s.to_dict() if hasattr(s, 'to_dict') else s for s in steps]
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(steps_data, f, indent=2, ensure_ascii=False)
        
        print(f"[StepBuilder] Saved {len(steps)} raw steps to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[StepBuilder] Error saving raw steps: {e}", flush=True)
        return False


def load_raw_steps(data_dir) -> List[LessonStep]:
    """Load raw steps from JSON file."""
    import json
    from pathlib import Path
    
    try:
        data_dir = Path(data_dir)
        file_path = data_dir / "lessons" / "raw_steps.json"
        
        if not file_path.exists():
            return []
        
        with open(file_path, "r", encoding="utf-8") as f:
            steps_data = json.load(f)
        
        steps = [LessonStep.from_dict(s) if hasattr(LessonStep, 'from_dict') else LessonStep(**s) for s in steps_data]
        
        print(f"[StepBuilder] Loaded {len(steps)} raw steps from {file_path}", flush=True)
        return steps
        
    except Exception as e:
        print(f"[StepBuilder] Error loading raw steps: {e}", flush=True)
        return []


def validate_steps_coverage(
    steps: List[LessonStep],
    manifest: LessonManifest,
) -> Tuple[bool, List[str]]:
    """
    Validate that steps cover all subdomains in manifest.
    
    Returns:
        Tuple of (all_covered: bool, missing_subdomains: List[str])
    """
    # Get all subdomains from manifest
    expected_subdomains = set()
    
    # Handle both object and dict formats for manifest.domains
    domains = manifest.domains if hasattr(manifest, 'domains') else []
    
    for domain in domains:
        # Handle both dict and object formats
        if isinstance(domain, dict):
            subdomains = domain.get("subdomains", [])
        else:
            subdomains = getattr(domain, 'subdomains', [])
        
        for subdomain in subdomains:
            # Handle both string and object subdomains
            if isinstance(subdomain, str):
                expected_subdomains.add(subdomain.lower())
            elif isinstance(subdomain, dict):
                expected_subdomains.add(subdomain.get("name", "").lower())
            else:
                expected_subdomains.add(str(subdomain).lower())
    
    # Get covered subdomains from steps
    covered_subdomains = set()
    for step in steps:
        if hasattr(step, 'subdomain') and step.subdomain:
            covered_subdomains.add(step.subdomain.lower())
        if hasattr(step, 'subdomains_covered') and step.subdomains_covered:
            for sd in step.subdomains_covered:
                covered_subdomains.add(sd.lower())
    
    # Find missing
    missing = expected_subdomains - covered_subdomains
    
    return len(missing) == 0, list(missing)
