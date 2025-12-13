# kernel/domain_normalizer.py
"""
v2.0.0 - Topic-Agnostic Domain Normalizer (Robust Extraction)

Handles various input formats:
- Structured curriculum documents (phases, focus areas, outputs)
- Simple objective statements ("Learn Docker and Kubernetes")
- Bullet-point lists
- Freeform descriptions

KEY INSIGHT:
- DOMAINS = Major topics/subjects (Networking, AWS, Active Directory)
- SUBDOMAINS = Layer-based breakdown (Fundamentals, Architecture, Implementation, Operations)

The learning layers are applied WITHIN each domain as subdomains,
NOT as separate domains.

Usage:
    from domain_normalizer import extract_domains_robust
    
    result = extract_domains_robust(
        text="Phase A1 - Fundamentals...",
        llm_client=kernel.llm_client,
    )
    # Returns: [
    #   {"name": "Networking", "subdomains": ["Networking Fundamentals", "Network Architecture", ...]},
    #   {"name": "Active Directory", "subdomains": ["AD Fundamentals", "AD Architecture", ...]},
    # ]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


# =============================================================================
# LEARNING LAYERS (used to generate subdomains, NOT domains)
# =============================================================================

class LearningLayer(Enum):
    FOUNDATIONS = "foundations"
    ARCHITECTURE = "architecture"  
    IMPLEMENTATION = "implementation"
    OPERATIONS = "operations"


LAYER_SUFFIXES = {
    LearningLayer.FOUNDATIONS: "Fundamentals",
    LearningLayer.ARCHITECTURE: "Architecture", 
    LearningLayer.IMPLEMENTATION: "Implementation",
    LearningLayer.OPERATIONS: "Operations",
}

LAYER_DESCRIPTIONS = {
    LearningLayer.FOUNDATIONS: "core concepts, terminology, principles, why it exists",
    LearningLayer.ARCHITECTURE: "structure, components, how parts connect, design patterns",
    LearningLayer.IMPLEMENTATION: "hands-on setup, configuration, building, coding",
    LearningLayer.OPERATIONS: "troubleshooting, monitoring, maintenance, debugging",
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExtractedDomain:
    """A domain with its subdomains."""
    name: str
    subdomains: List[str] = field(default_factory=list)
    raw_subtopics: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Result of domain extraction."""
    domains: List[ExtractedDomain]
    raw_topics_found: List[str]
    input_type: str
    

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def extract_domains_robust(
    text: str,
    llm_client: Any,
    max_domains: int = 8,
    generate_subdomains: bool = True,
) -> List[Dict[str, Any]]:
    """
    Robustly extract domains from any input format.
    
    This is the main entry point. Handles:
    - Curriculum documents with phases, focus areas, outputs
    - Simple "Learn X, Y, and Z" statements
    - Bullet-point lists
    - Freeform descriptions
    
    Args:
        text: Raw input text (any format)
        llm_client: LLM client for extraction
        max_domains: Maximum number of domains to extract
        generate_subdomains: If True, generate layer-based subdomains
    
    Returns:
        List of {"name": "Domain", "subdomains": ["Sub1", "Sub2", ...]}
    """
    print(f"[DomainNormalizer] Extracting domains from {len(text)} chars...", flush=True)
    
    # Step 1: Detect input type and preprocess
    input_type, cleaned_text = _preprocess_input(text)
    print(f"[DomainNormalizer] Input type: {input_type}", flush=True)
    
    # Step 2: Extract raw topics using LLM
    raw_topics = _extract_raw_topics(cleaned_text, llm_client, max_domains, input_type)
    
    if not raw_topics:
        print(f"[DomainNormalizer] No topics extracted, using fallback", flush=True)
        raw_topics = _fallback_extract_topics(cleaned_text)
    
    print(f"[DomainNormalizer] Found {len(raw_topics)} topics: {[t['name'] for t in raw_topics]}", flush=True)
    
    # Step 3: Generate subdomains for each topic
    domains = []
    for topic in raw_topics:
        domain_name = topic["name"]
        raw_subtopics = topic.get("subtopics", [])
        
        if generate_subdomains:
            subdomains = _generate_subdomains_for_topic(
                domain_name, 
                raw_subtopics,
                llm_client
            )
        else:
            subdomains = raw_subtopics
        
        domains.append({
            "name": domain_name,
            "subdomains": subdomains,
            "subtopics": raw_subtopics,
        })
    
    print(f"[DomainNormalizer] Generated {len(domains)} domains with subdomains", flush=True)
    
    return domains


# =============================================================================
# INPUT PREPROCESSING
# =============================================================================

def _preprocess_input(text: str) -> Tuple[str, str]:
    """
    Detect input type and clean the text.
    
    Returns:
        Tuple of (input_type, cleaned_text)
    """
    text_lower = text.lower()
    
    # Detect curriculum/phase document
    if any(marker in text_lower for marker in [
        "phase", "your goal:", "focus areas", "outputs:", 
        "objectives:", "learning path", "curriculum"
    ]):
        input_type = "curriculum"
        cleaned = _extract_focus_section(text)
    
    # Detect simple objectives
    elif text_lower.startswith(("learn ", "study ", "understand ", "master ")):
        input_type = "objectives"
        cleaned = text
    
    # Detect bullet/numbered list
    elif re.search(r'^[\s]*[-*\d.]+\s+', text, re.MULTILINE):
        input_type = "list"
        cleaned = text
    
    else:
        input_type = "freeform"
        cleaned = text
    
    return input_type, cleaned


def _extract_focus_section(text: str) -> str:
    """
    Extract the focus areas / topics section from a curriculum document.
    
    Removes meta text like "Phase A1", "Your goal:", "Outputs:", etc.
    """
    lines = text.split('\n')
    relevant_lines = []
    in_focus_section = False
    
    skip_patterns = [
        r'^#+\s*\*?\*?phase',
        r'^your goal:',
        r'^outputs?:?$',
        r'^\s*[-*]\s*(mini\s+)?labs?:',
        r'^you\s+(become|will)',
        r'^\d+[-\u2013]\d+\s*(months?|weeks?)',
    ]
    
    start_patterns = [
        r'^focus\s+areas?:?',
        r'^topics?:?',
        r'^learning\s+areas?:?',
        r'^subjects?:?',
    ]
    
    for line in lines:
        line_lower = line.lower().strip()
        
        if not line_lower:
            continue
        
        if any(re.match(p, line_lower) for p in start_patterns):
            in_focus_section = True
            continue
        
        if any(re.match(p, line_lower) for p in skip_patterns):
            in_focus_section = False
            continue
        
        if re.match(r'^\s*[-*]\s+\w', line) or re.match(r'^\s*\d+[.)]\s+\w', line):
            relevant_lines.append(line)
            in_focus_section = True
        elif in_focus_section:
            relevant_lines.append(line)
    
    result = '\n'.join(relevant_lines)
    
    if not result.strip():
        filtered = []
        for line in lines:
            line_lower = line.lower().strip()
            if not any(re.match(p, line_lower) for p in skip_patterns):
                if not line_lower.startswith('#'):
                    filtered.append(line)
        result = '\n'.join(filtered)
    
    return result


# =============================================================================
# TOPIC EXTRACTION (LLM)
# =============================================================================

def _extract_raw_topics(
    text: str,
    llm_client: Any,
    max_topics: int,
    input_type: str,
) -> List[Dict[str, Any]]:
    """
    Extract raw topics from preprocessed text.
    
    Returns list of {"name": "Topic", "subtopics": ["sub1", "sub2"]}
    """
    
    system_prompt = """You are a curriculum analyst. Extract the main TOPICS from this learning content.

A TOPIC is a distinct subject area to learn. Examples:
- "Networking" (not "Networking routing" or "VLANs")
- "Active Directory" (not "AD trusts" or "GPOs")  
- "AWS" (not "EC2" or "S3")
- "Identity" (not "OAuth2" or "SAML")

CRITICAL RULES:
1. Extract TOP-LEVEL topics only (the main subjects, not sub-items)
2. Topic names should be 1-3 words maximum
3. If you see "Topic (sub1, sub2, sub3)", extract:
   - name: "Topic"
   - subtopics: ["sub1", "sub2", "sub3"]
4. Combine related items: "AWS fundamentals (IAM, EC2, S3)" = one topic "AWS"
5. Do NOT create separate topics for sub-items
6. Maximum {max_topics} topics

DISAMBIGUATION RULES (resolve ambiguous acronyms):
- "AD" alone = "Active Directory" (unless clearly about advertising)
- "AD architecture" or "AD trusts" = "Active Directory"
- "Azure AD" or "Entra" = keep as "Azure AD" or "Entra ID" (separate from on-prem AD)
- "IAM" with AWS context (EC2, S3, etc.) = subtopic under "AWS", not separate topic
- "IAM" with Azure context = subtopic under "Azure", not separate topic
- "IAM" standalone = "Identity Management" as topic name
- "RBAC" with K8s context = subtopic under "Kubernetes"
- "RBAC" with Azure context = subtopic under "Azure"
- "DNS" as protocol/concept = subtopic under "Networking"
- "Route53" = subtopic under "AWS"
- "Azure DNS" = subtopic under "Azure"
- "K8s" = "Kubernetes"
- "SIEM" alone = "Logging/SIEM" as topic name

EXAMPLES:
Input: "Networking (routing, VLANs, DNS, segmentation)"
Output: {{"name": "Networking", "subtopics": ["routing", "VLANs", "DNS", "segmentation"]}}

Input: "AWS fundamentals (IAM, EC2, S3, networking, logging)"  
Output: {{"name": "AWS", "subtopics": ["IAM", "EC2", "S3", "networking", "logging"]}}

Input: "Active Directory architecture (trusts, delegation, GPOs)"
Output: {{"name": "Active Directory", "subtopics": ["trusts", "delegation", "GPOs"]}}

Input: "Azure fundamentals (Entra, Azure AD, hybrid identity, RBAC)"
Output: {{"name": "Azure", "subtopics": ["Entra ID", "hybrid identity", "RBAC"]}}

Input: "Learn Docker containerization and Kubernetes orchestration"
Output: [{{"name": "Docker", "subtopics": []}}, {{"name": "Kubernetes", "subtopics": []}}]

Return JSON only:
{{
  "topics": [
    {{"name": "Topic Name", "subtopics": ["sub1", "sub2"]}}
  ]
}}"""

    user_prompt = f"""Extract topics from this {input_type} content:

{text}

Return JSON with topics array. Remember: extract TOP-LEVEL topics only, put details in subtopics."""

    try:
        result = llm_client.complete_system(
            system=system_prompt.format(max_topics=max_topics),
            user=user_prompt,
            command="domain-extract-topics",
        )
        
        response_text = result.get("text", "").strip()
        data = _parse_json_response(response_text)
        
        if data and "topics" in data:
            topics = []
            for item in data["topics"][:max_topics]:
                name = item.get("name", "").strip()
                if name:
                    topics.append({
                        "name": _clean_topic_name(name),
                        "subtopics": item.get("subtopics", []),
                    })
            return topics
        
        return []
        
    except Exception as e:
        print(f"[DomainNormalizer] Topic extraction error: {e}", flush=True)
        return []


def _fallback_extract_topics(text: str) -> List[Dict[str, Any]]:
    """
    Fallback topic extraction using pattern matching.
    """
    topics = []
    seen = set()
    
    # Pattern 1: "Topic (sub1, sub2, sub3)"
    pattern1 = r'[-*]\s*([A-Za-z][A-Za-z\s/]+?)\s*\(([^)]+)\)'
    for match in re.finditer(pattern1, text):
        name = match.group(1).strip()
        subtopics_str = match.group(2)
        subtopics = [s.strip() for s in re.split(r'[,;]', subtopics_str) if s.strip()]
        
        name_lower = name.lower()
        if name_lower not in seen and len(name) > 2:
            topics.append({"name": _clean_topic_name(name), "subtopics": subtopics})
            seen.add(name_lower)
    
    # Pattern 2: Simple bullets
    if not topics:
        pattern2 = r'[-*]\s*([A-Za-z][A-Za-z\s/]+?)(?:\s*[-:]|$)'
        for match in re.finditer(pattern2, text):
            name = match.group(1).strip()
            if len(name.split()) > 4:
                continue
            
            name_lower = name.lower()
            if name_lower not in seen and len(name) > 2:
                topics.append({"name": _clean_topic_name(name), "subtopics": []})
                seen.add(name_lower)
    
    return topics[:8]


# =============================================================================
# SUBDOMAIN GENERATION
# =============================================================================

def _generate_subdomains_for_topic(
    domain_name: str,
    raw_subtopics: List[str],
    llm_client: Any,
) -> List[str]:
    """
    Generate layer-based subdomains for a topic.
    """
    
    if raw_subtopics:
        return _organize_subtopics_into_subdomains(domain_name, raw_subtopics, llm_client)
    else:
        return _generate_generic_subdomains(domain_name)


def _organize_subtopics_into_subdomains(
    domain_name: str,
    raw_subtopics: List[str],
    llm_client: Any,
) -> List[str]:
    """
    Organize raw subtopics into coherent subdomains.
    """
    
    system_prompt = """You are a curriculum designer. Organize these subtopics into coherent learning subdomains.

RULES:
1. Create 4-6 subdomains that cover all the subtopics
2. Each subdomain should be a learnable unit (60-120 minutes)
3. Group related subtopics together
4. Use clear, specific names (not generic like "Basics" or "Advanced")
5. Include a fundamentals/concepts subdomain if needed
6. Include a hands-on/implementation subdomain if applicable

NAMING GUIDELINES:
- Good: "Network Routing Fundamentals", "VLAN Configuration and Segmentation"
- Bad: "Networking Basics", "Advanced Networking", "Networking 101"

Return JSON only:
{"subdomains": ["Subdomain 1", "Subdomain 2", ...]}"""

    user_prompt = f"""Domain: {domain_name}
Subtopics to organize: {', '.join(raw_subtopics)}

Create 4-6 coherent subdomains that cover all these subtopics:"""

    try:
        result = llm_client.complete_system(
            system=system_prompt,
            user=user_prompt,
            command="domain-generate-subdomains",
        )
        
        response_text = result.get("text", "").strip()
        data = _parse_json_response(response_text)
        
        if data and "subdomains" in data:
            return data["subdomains"][:6]
        
    except Exception as e:
        print(f"[DomainNormalizer] Subdomain generation error: {e}", flush=True)
    
    return _fallback_create_subdomains(domain_name, raw_subtopics)


def _generate_generic_subdomains(domain_name: str) -> List[str]:
    """
    Generate generic layer-based subdomains when no subtopics provided.
    """
    short_name = _get_short_name(domain_name)
    
    return [
        f"{short_name} Fundamentals and Core Concepts",
        f"{short_name} Architecture and Components",
        f"{short_name} Implementation and Configuration",
        f"{short_name} Operations and Troubleshooting",
    ]


def _fallback_create_subdomains(domain_name: str, raw_subtopics: List[str]) -> List[str]:
    """
    Fallback: create subdomains by grouping subtopics.
    """
    short_name = _get_short_name(domain_name)
    
    if len(raw_subtopics) <= 2:
        subdomains = [f"{short_name} Fundamentals"]
        for st in raw_subtopics:
            subdomains.append(f"{short_name} {st.title()}")
        subdomains.append(f"{short_name} Implementation")
        return subdomains
    
    subdomains = [f"{short_name} Fundamentals"]
    
    i = 0
    while i < len(raw_subtopics):
        if i + 1 < len(raw_subtopics):
            subdomains.append(f"{raw_subtopics[i].title()} and {raw_subtopics[i+1].title()}")
            i += 2
        else:
            subdomains.append(f"{short_name} {raw_subtopics[i].title()}")
            i += 1
    
    return subdomains[:6]


# =============================================================================
# UTILITIES
# =============================================================================

def _clean_topic_name(name: str) -> str:
    """
    Clean up a topic name and apply disambiguation rules.
    """
    # First, apply disambiguation
    name = _disambiguate_topic(name)
    
    # Fix slash-separated acronyms (Ci/Cd -> CI/CD)
    def fix_slash_acronym(match):
        parts = match.group(0).split('/')
        if all(len(p) <= 4 for p in parts):
            return '/'.join(p.upper() for p in parts)
        return match.group(0)
    
    result = re.sub(r'\b[A-Za-z]{1,4}/[A-Za-z]{1,4}\b', fix_slash_acronym, name)
    
    # Fix common acronyms
    acronyms = {'aws', 'gcp', 'api', 'sql', 'dns', 'vpn', 'vpc', 'iam', 'rbac', 'siem'}
    for acr in acronyms:
        result = re.sub(rf'\b{acr}\b', acr.upper(), result, flags=re.IGNORECASE)
    
    # Title case other words but preserve acronyms
    words = result.split()
    cleaned_words = []
    for word in words:
        if word.isupper() and len(word) <= 5:
            cleaned_words.append(word)
        elif '/' in word:
            cleaned_words.append(word)
        else:
            cleaned_words.append(word.title())
    
    return ' '.join(cleaned_words).strip()


def _disambiguate_topic(name: str) -> str:
    """
    Resolve ambiguous acronyms to full names.
    
    Rules:
    - "AD" alone -> "Active Directory"
    - "K8s" -> "Kubernetes"
    - "SIEM" alone -> "Logging/SIEM"
    - "IAM" alone -> "Identity Management"
    - Preserves context when present (e.g., "Azure AD" stays as-is)
    """
    name_lower = name.lower().strip()
    
    # Special cases to preserve as-is (Azure AD and Entra are distinct products)
    PRESERVE_PATTERNS = [
        (r'azure\s+ad\b', 'Azure AD'),
        (r'entra\s+id\b', 'Entra ID'),
        (r'entra\b', 'Entra ID'),
        (r'aad\b', 'Azure AD'),
    ]
    
    for pattern, replacement in PRESERVE_PATTERNS:
        if re.search(pattern, name_lower):
            return re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    
    # Exact matches for standalone acronyms
    STANDALONE_EXPANSIONS = {
        "ad": "Active Directory",
        "k8s": "Kubernetes",
        "siem": "Logging/SIEM",
        "iam": "Identity Management",
        "rbac": "Role-Based Access Control",
        "gpo": "Group Policy",
        "gpos": "Group Policy",
    }
    
    # Check for exact standalone match
    if name_lower in STANDALONE_EXPANSIONS:
        return STANDALONE_EXPANSIONS[name_lower]
    
    # Contextual expansions (when acronym appears with context)
    # "AD architecture" -> "Active Directory Architecture"
    CONTEXTUAL_PATTERNS = [
        (r'^ad\s+', 'Active Directory '),
        (r'\s+ad$', ' Active Directory'),
        (r'^k8s\s+', 'Kubernetes '),
        (r'\s+k8s$', ' Kubernetes'),
    ]
    
    result = name
    for pattern, replacement in CONTEXTUAL_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    return result


def _get_short_name(domain_name: str) -> str:
    """Get a short version of the domain name for prefixing subdomains."""
    if len(domain_name.split()) <= 2:
        return domain_name
    
    words = domain_name.split()
    skip_words = {'and', 'the', 'of', 'for', 'with', 'in', 'on', 'at', 'to'}
    significant = [w for w in words if w.lower() not in skip_words]
    
    if significant:
        return ' '.join(significant[:2])
    return words[0]


def _parse_json_response(text: str) -> Optional[Dict]:
    """Parse JSON from LLM response."""
    
    if "```" in text:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1)
    
    start = text.find('{')
    end = text.rfind('}') + 1
    
    if start == -1 or end == 0:
        return None
    
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


# =============================================================================
# INTEGRATION WITH QUEST_COMPOSE_WIZARD
# =============================================================================

def extract_domains_for_quest_compose(
    text: str,
    llm_client: Any,
) -> List[Dict[str, Any]]:
    """
    Main entry point for quest_compose_wizard integration.
    
    Returns domains in the format expected by the wizard:
    [{"name": "Domain", "subtopics": [...]}]
    
    Note: "subtopics" in output = "subdomains" we generated
    """
    domains = extract_domains_robust(text, llm_client)
    
    return [
        {
            "name": d["name"],
            "subtopics": d.get("subdomains", []),
        }
        for d in domains
    ]
