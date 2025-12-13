# kernel/subdomain_validator.py
"""
v1.0.0 — Topic-Agnostic Subdomain Validation

Layered validation for lesson plan subdomains:
  Layer 1: Deterministic rules (fast, reliable)
  Layer 2: Semantic similarity via embeddings (no LLM)
  Layer 3: LLM resolution for ambiguous cases (optional, constrained)

This module is TOPIC-AGNOSTIC. No hardcoded domains or keywords.
Works for Docker, cooking, finance, music theory, anything.

Usage:
    from subdomain_validator import validate_subdomain_structure
    
    result = validate_subdomain_structure(
        domains={"Docker Basics": ["Images", "Containers"], ...},
        llm_client=kernel.llm_client,  # Optional
    )
    
    if result["valid"]:
        clean_domains = result["domains"]
    else:
        issues = result["issues"]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

# Try to import sentence-transformers for Layer 2
_HAS_EMBEDDINGS = False
_embedding_model = None

try:
    from sentence_transformers import SentenceTransformer, util
    _HAS_EMBEDDINGS = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

# Similarity threshold for semantic deduplication (0.0 - 1.0)
# Higher = stricter (fewer merges), Lower = more aggressive merging
SEMANTIC_SIMILARITY_THRESHOLD = 0.82

# Maximum subdomains per domain
MAX_SUBDOMAINS_PER_DOMAIN = 8

# Minimum subdomains per domain (warn if below)
MIN_SUBDOMAINS_PER_DOMAIN = 2

# Phrases that indicate a subdomain is too vague (topic-agnostic)
VAGUE_PATTERNS = [
    r"^(general|basic|advanced)\s+(overview|concepts?|topics?)$",
    r"^(introduction|intro)\s+to\s+.+$",
    r"^(misc|miscellaneous|other)\b",
    r"^(best practices|tips and tricks)$",
    r"^(more|additional|further)\s+.+$",
    r"^.+\s+(and more|etc\.?)$",
]

# Words that often indicate overlap when shared between domains
OVERLAP_SIGNAL_WORDS = {
    "management", "managing", "configuration", "configuring",
    "fundamentals", "basics", "concepts", "principles",
    "operations", "operational", "implementation", "implementing",
    "monitoring", "troubleshooting", "debugging",
    "architecture", "design", "patterns",
    "security", "authentication", "authorization",
    "lifecycle", "workflow", "process",
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ValidationIssue:
    """A single validation issue found."""
    issue_type: str  # "duplicate", "vague", "overlap", "count"
    severity: str    # "error", "warning", "info"
    domain: str
    subdomain: str
    related_to: Optional[str] = None  # For duplicates: the other subdomain
    similarity: Optional[float] = None
    message: str = ""
    
    def __str__(self):
        if self.related_to:
            return f"[{self.severity.upper()}] {self.issue_type}: '{self.subdomain}' ↔ '{self.related_to}' ({self.similarity:.2f})"
        return f"[{self.severity.upper()}] {self.issue_type}: '{self.subdomain}' in {self.domain}"


@dataclass
class ValidationResult:
    """Result of subdomain validation."""
    valid: bool
    domains: Dict[str, List[str]]  # Cleaned domains
    issues: List[ValidationIssue] = field(default_factory=list)
    merges_applied: List[Tuple[str, str, str]] = field(default_factory=list)  # (kept, dropped, domain)
    stats: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def validate_subdomain_structure(
    domains: Dict[str, List[str]],
    llm_client: Any = None,
    auto_fix: bool = True,
    similarity_threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> ValidationResult:
    """
    Validate and optionally fix subdomain structure.
    
    This is TOPIC-AGNOSTIC. Works for any subject matter.
    
    Args:
        domains: Dict mapping domain names to subdomain lists
        llm_client: Optional LLM client for Layer 3 resolution
        auto_fix: If True, automatically apply fixes. If False, only report issues.
        similarity_threshold: Threshold for semantic similarity (default 0.82)
    
    Returns:
        ValidationResult with cleaned domains and issues found
    """
    issues: List[ValidationIssue] = []
    merges: List[Tuple[str, str, str]] = []
    
    # Work on a copy
    working_domains = {k: list(v) for k, v in domains.items()}
    
    # =========================================================================
    # LAYER 1: DETERMINISTIC RULES
    # =========================================================================
    print("[SubdomainValidator] Layer 1: Deterministic rules...", flush=True)
    
    # 1a. Exact duplicate removal (cross-domain)
    working_domains, exact_dupes = _remove_exact_duplicates(working_domains)
    for kept, dropped, domain in exact_dupes:
        issues.append(ValidationIssue(
            issue_type="exact_duplicate",
            severity="error",
            domain=domain,
            subdomain=dropped,
            related_to=kept,
            message=f"Exact duplicate of '{kept}'"
        ))
        merges.append((kept, dropped, domain))
    
    # 1b. Vague/overly broad subdomain detection
    working_domains, vague_found = _remove_vague_subdomains(working_domains)
    for sub, domain in vague_found:
        issues.append(ValidationIssue(
            issue_type="vague",
            severity="warning",
            domain=domain,
            subdomain=sub,
            message="Subdomain is too vague or broad"
        ))
    
    # 1c. Count enforcement
    for domain, subs in working_domains.items():
        if len(subs) > MAX_SUBDOMAINS_PER_DOMAIN:
            issues.append(ValidationIssue(
                issue_type="count_exceeded",
                severity="warning",
                domain=domain,
                subdomain=f"{len(subs)} subdomains",
                message=f"Domain has {len(subs)} subdomains, max is {MAX_SUBDOMAINS_PER_DOMAIN}"
            ))
            if auto_fix:
                working_domains[domain] = subs[:MAX_SUBDOMAINS_PER_DOMAIN]
        
        if len(subs) < MIN_SUBDOMAINS_PER_DOMAIN:
            issues.append(ValidationIssue(
                issue_type="count_low",
                severity="info",
                domain=domain,
                subdomain=f"{len(subs)} subdomains",
                message=f"Domain has only {len(subs)} subdomains, consider expanding"
            ))
    
    print(f"[SubdomainValidator] Layer 1 complete: {len(exact_dupes)} exact dupes, {len(vague_found)} vague", flush=True)
    
    # =========================================================================
    # LAYER 2: SEMANTIC SIMILARITY (if embeddings available)
    # =========================================================================
    if _HAS_EMBEDDINGS:
        print("[SubdomainValidator] Layer 2: Semantic similarity...", flush=True)
        
        # 2a. Cross-domain semantic duplicates
        working_domains, cross_dupes = _remove_semantic_duplicates_cross_domain(
            working_domains, threshold=similarity_threshold
        )
        for kept, dropped, domain, sim in cross_dupes:
            issues.append(ValidationIssue(
                issue_type="semantic_duplicate_cross",
                severity="error",
                domain=domain,
                subdomain=dropped,
                related_to=kept,
                similarity=sim,
                message=f"Semantically similar to '{kept}' in another domain"
            ))
            merges.append((kept, dropped, domain))
        
        # 2b. Intra-domain semantic duplicates
        working_domains, intra_dupes = _remove_semantic_duplicates_intra_domain(
            working_domains, threshold=similarity_threshold
        )
        for kept, dropped, domain, sim in intra_dupes:
            issues.append(ValidationIssue(
                issue_type="semantic_duplicate_intra",
                severity="warning",
                domain=domain,
                subdomain=dropped,
                related_to=kept,
                similarity=sim,
                message=f"Semantically similar to '{kept}' in same domain"
            ))
            merges.append((kept, dropped, domain))
        
        # 2c. Cross-domain concept overlap detection (doesn't remove, just warns)
        overlaps = _detect_concept_overlap(working_domains)
        for sub_a, sub_b, domain_a, domain_b, sim in overlaps:
            issues.append(ValidationIssue(
                issue_type="concept_overlap",
                severity="warning",
                domain=domain_a,
                subdomain=sub_a,
                related_to=f"{sub_b} ({domain_b})",
                similarity=sim,
                message=f"Potential overlap with '{sub_b}' in {domain_b}"
            ))
        
        print(f"[SubdomainValidator] Layer 2 complete: {len(cross_dupes)} cross-domain, {len(intra_dupes)} intra-domain, {len(overlaps)} overlaps", flush=True)
    else:
        print("[SubdomainValidator] Layer 2 skipped: sentence-transformers not available", flush=True)
        # Fall back to word-overlap heuristic
        working_domains, word_dupes = _remove_word_overlap_duplicates(working_domains)
        for kept, dropped, domain in word_dupes:
            issues.append(ValidationIssue(
                issue_type="word_overlap_duplicate",
                severity="warning",
                domain=domain,
                subdomain=dropped,
                related_to=kept,
                message=f"High word overlap with '{kept}'"
            ))
            merges.append((kept, dropped, domain))
    
    # =========================================================================
    # LAYER 3: LLM RESOLUTION (only for ambiguous cases)
    # =========================================================================
    ambiguous_issues = [i for i in issues if i.severity == "warning" and i.issue_type == "concept_overlap"]
    
    if llm_client and ambiguous_issues and auto_fix:
        print(f"[SubdomainValidator] Layer 3: LLM resolution for {len(ambiguous_issues)} ambiguous cases...", flush=True)
        
        resolutions = _llm_resolve_ambiguous(ambiguous_issues, working_domains, llm_client)
        
        for resolution in resolutions:
            if resolution["action"] == "merge":
                kept = resolution["keep"]
                dropped = resolution["drop"]
                domain = resolution["domain"]
                
                if dropped in working_domains.get(domain, []):
                    working_domains[domain].remove(dropped)
                    merges.append((kept, dropped, domain))
                    print(f"[SubdomainValidator] LLM merged: '{dropped}' → '{kept}'", flush=True)
        
        print(f"[SubdomainValidator] Layer 3 complete: {len(resolutions)} resolutions", flush=True)
    
    # =========================================================================
    # FINAL STATS
    # =========================================================================
    total_original = sum(len(v) for v in domains.values())
    total_final = sum(len(v) for v in working_domains.values())
    
    stats = {
        "original_count": total_original,
        "final_count": total_final,
        "removed_count": total_original - total_final,
        "domains_count": len(working_domains),
        "issues_count": len(issues),
        "errors_count": len([i for i in issues if i.severity == "error"]),
        "warnings_count": len([i for i in issues if i.severity == "warning"]),
    }
    
    # Valid if no errors remain
    has_errors = any(i.severity == "error" for i in issues if i.subdomain in 
                     [s for subs in working_domains.values() for s in subs])
    
    print(f"[SubdomainValidator] Complete: {total_original} → {total_final} subdomains", flush=True)
    
    return ValidationResult(
        valid=not has_errors,
        domains=working_domains,
        issues=issues,
        merges_applied=merges,
        stats=stats,
    )


# =============================================================================
# LAYER 1: DETERMINISTIC RULES
# =============================================================================

def _remove_exact_duplicates(
    domains: Dict[str, List[str]]
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str, str]]]:
    """
    Remove exact duplicate subdomains across domains.
    
    Returns:
        Tuple of (cleaned_domains, list of (kept, dropped, dropped_domain))
    """
    seen: Dict[str, Tuple[str, str]] = {}  # normalized -> (original, domain)
    removed = []
    
    result = {}
    for domain, subs in domains.items():
        clean_subs = []
        for sub in subs:
            normalized = sub.lower().strip()
            
            if normalized in seen:
                original, orig_domain = seen[normalized]
                removed.append((original, sub, domain))
            else:
                seen[normalized] = (sub, domain)
                clean_subs.append(sub)
        
        result[domain] = clean_subs
    
    return result, removed


def _remove_vague_subdomains(
    domains: Dict[str, List[str]]
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str]]]:
    """
    Remove subdomains that are too vague or broad.
    
    Returns:
        Tuple of (cleaned_domains, list of (subdomain, domain))
    """
    removed = []
    result = {}
    
    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in VAGUE_PATTERNS]
    
    for domain, subs in domains.items():
        clean_subs = []
        for sub in subs:
            is_vague = any(p.search(sub) for p in compiled_patterns)
            
            if is_vague:
                removed.append((sub, domain))
            else:
                clean_subs.append(sub)
        
        result[domain] = clean_subs
    
    return result, removed


def _remove_word_overlap_duplicates(
    domains: Dict[str, List[str]],
    threshold: float = 0.7,
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str, str]]]:
    """
    Fallback: Remove duplicates based on word overlap (when embeddings unavailable).
    
    Returns:
        Tuple of (cleaned_domains, list of (kept, dropped, domain))
    """
    def get_words(text: str) -> Set[str]:
        """Extract meaningful words from text."""
        fillers = {"and", "the", "of", "in", "for", "with", "to", "a", "an", "on", "at", "by", "or"}
        words = set(re.findall(r'\b\w+\b', text.lower())) - fillers
        return words
    
    removed = []
    
    # Cross-domain check
    all_subs: List[Tuple[str, str, Set[str]]] = []
    for domain, subs in domains.items():
        for sub in subs:
            all_subs.append((sub, domain, get_words(sub)))
    
    to_remove: Set[Tuple[str, str]] = set()
    
    for i, (sub_a, domain_a, words_a) in enumerate(all_subs):
        if (sub_a, domain_a) in to_remove:
            continue
        
        for j, (sub_b, domain_b, words_b) in enumerate(all_subs):
            if j <= i or (sub_b, domain_b) in to_remove:
                continue
            
            # Calculate overlap
            if not words_a or not words_b:
                continue
            
            intersection = words_a & words_b
            smaller = min(len(words_a), len(words_b))
            overlap = len(intersection) / smaller if smaller > 0 else 0
            
            if overlap >= threshold:
                # Keep the more specific one (longer usually = more specific)
                if len(sub_a) >= len(sub_b):
                    to_remove.add((sub_b, domain_b))
                    removed.append((sub_a, sub_b, domain_b))
                else:
                    to_remove.add((sub_a, domain_a))
                    removed.append((sub_b, sub_a, domain_a))
                    break
    
    # Build result
    result = {}
    for domain, subs in domains.items():
        result[domain] = [s for s in subs if (s, domain) not in to_remove]
    
    return result, removed


# =============================================================================
# LAYER 2: SEMANTIC SIMILARITY
# =============================================================================

def _get_embedding_model():
    """Get or initialize the embedding model."""
    global _embedding_model
    
    if _embedding_model is None and _HAS_EMBEDDINGS:
        print("[SubdomainValidator] Loading embedding model...", flush=True)
        # Use a small, fast model
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    return _embedding_model


def _remove_semantic_duplicates_cross_domain(
    domains: Dict[str, List[str]],
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str, str, float]]]:
    """
    Remove semantically similar subdomains across different domains.
    
    Returns:
        Tuple of (cleaned_domains, list of (kept, dropped, dropped_domain, similarity))
    """
    model = _get_embedding_model()
    if model is None:
        return domains, []
    
    # Collect all subdomains with their domains
    all_subs: List[Tuple[str, str]] = []
    for domain, subs in domains.items():
        for sub in subs:
            all_subs.append((sub, domain))
    
    if len(all_subs) < 2:
        return domains, []
    
    # Compute embeddings
    texts = [sub for sub, _ in all_subs]
    embeddings = model.encode(texts, convert_to_tensor=True)
    
    # Find duplicates
    to_remove: Set[Tuple[str, str]] = set()
    removed = []
    
    for i in range(len(all_subs)):
        if all_subs[i] in to_remove:
            continue
        
        sub_a, domain_a = all_subs[i]
        
        for j in range(i + 1, len(all_subs)):
            if all_subs[j] in to_remove:
                continue
            
            sub_b, domain_b = all_subs[j]
            
            # Only check cross-domain pairs
            if domain_a == domain_b:
                continue
            
            # Calculate similarity
            sim = util.cos_sim(embeddings[i], embeddings[j]).item()
            
            if sim >= threshold:
                # Keep the more specific one
                if len(sub_a) >= len(sub_b):
                    to_remove.add((sub_b, domain_b))
                    removed.append((sub_a, sub_b, domain_b, sim))
                else:
                    to_remove.add((sub_a, domain_a))
                    removed.append((sub_b, sub_a, domain_a, sim))
                    break
    
    # Build result
    result = {}
    for domain, subs in domains.items():
        result[domain] = [s for s in subs if (s, domain) not in to_remove]
    
    return result, removed


def _remove_semantic_duplicates_intra_domain(
    domains: Dict[str, List[str]],
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> Tuple[Dict[str, List[str]], List[Tuple[str, str, str, float]]]:
    """
    Remove semantically similar subdomains within the same domain.
    
    Returns:
        Tuple of (cleaned_domains, list of (kept, dropped, domain, similarity))
    """
    model = _get_embedding_model()
    if model is None:
        return domains, []
    
    removed = []
    result = {}
    
    for domain, subs in domains.items():
        if len(subs) < 2:
            result[domain] = subs
            continue
        
        # Compute embeddings for this domain
        embeddings = model.encode(subs, convert_to_tensor=True)
        
        to_remove: Set[int] = set()
        
        for i in range(len(subs)):
            if i in to_remove:
                continue
            
            for j in range(i + 1, len(subs)):
                if j in to_remove:
                    continue
                
                sim = util.cos_sim(embeddings[i], embeddings[j]).item()
                
                if sim >= threshold:
                    # Keep the more specific one
                    if len(subs[i]) >= len(subs[j]):
                        to_remove.add(j)
                        removed.append((subs[i], subs[j], domain, sim))
                    else:
                        to_remove.add(i)
                        removed.append((subs[j], subs[i], domain, sim))
                        break
        
        result[domain] = [s for i, s in enumerate(subs) if i not in to_remove]
    
    return result, removed


def _detect_concept_overlap(
    domains: Dict[str, List[str]],
    threshold: float = 0.65,  # Lower threshold for overlap detection (warning only)
) -> List[Tuple[str, str, str, str, float]]:
    """
    Detect potential concept overlaps between domains (warning, not removal).
    
    This catches cases like:
    - "Pod Lifecycle" in Fundamentals AND "Pod Lifecycle Troubleshooting" in Operations
    
    Returns:
        List of (sub_a, sub_b, domain_a, domain_b, similarity)
    """
    model = _get_embedding_model()
    if model is None:
        return []
    
    # Collect all subdomains
    all_subs: List[Tuple[str, str]] = []
    for domain, subs in domains.items():
        for sub in subs:
            all_subs.append((sub, domain))
    
    if len(all_subs) < 2:
        return []
    
    # Compute embeddings
    texts = [sub for sub, _ in all_subs]
    embeddings = model.encode(texts, convert_to_tensor=True)
    
    overlaps = []
    
    for i in range(len(all_subs)):
        sub_a, domain_a = all_subs[i]
        
        for j in range(i + 1, len(all_subs)):
            sub_b, domain_b = all_subs[j]
            
            # Only check cross-domain pairs
            if domain_a == domain_b:
                continue
            
            sim = util.cos_sim(embeddings[i], embeddings[j]).item()
            
            # Flag moderate similarity as potential overlap (but not high enough to auto-remove)
            if threshold <= sim < SEMANTIC_SIMILARITY_THRESHOLD:
                overlaps.append((sub_a, sub_b, domain_a, domain_b, sim))
    
    return overlaps


# =============================================================================
# LAYER 3: LLM RESOLUTION
# =============================================================================

def _llm_resolve_ambiguous(
    issues: List[ValidationIssue],
    domains: Dict[str, List[str]],
    llm_client: Any,
) -> List[Dict[str, str]]:
    """
    Use LLM to resolve ambiguous overlap cases.
    
    CRITICAL: LLM is constrained to ONLY choose between existing options.
    It CANNOT invent new subdomains or rename things.
    
    Returns:
        List of resolution dicts with action, keep, drop, domain
    """
    if not issues:
        return []
    
    # Build prompt with pairs to resolve
    pairs_text = []
    for i, issue in enumerate(issues[:10]):  # Limit to 10 pairs
        pairs_text.append(f"{i+1}. '{issue.subdomain}' ({issue.domain}) vs '{issue.related_to}'")
    
    pairs_str = "\n".join(pairs_text)
    
    system_prompt = """You are a curriculum structure validator. You must decide how to handle overlapping subdomain pairs.

STRICT RULES:
1. You can ONLY choose "keep_first", "keep_second", or "keep_both"
2. You CANNOT invent new names or merge into a new concept
3. You CANNOT add explanations or caveats
4. Choose "keep_both" if they serve genuinely different learning purposes

Output format (JSON array):
[
  {"pair": 1, "action": "keep_first"},
  {"pair": 2, "action": "keep_both"},
  ...
]

JSON only, no explanation."""

    user_prompt = f"""These subdomain pairs have moderate semantic overlap. For each pair, decide what to do:

{pairs_str}

If they teach the same thing, keep the more specific one.
If they serve different purposes (e.g., "learning X" vs "troubleshooting X"), keep both.

Return JSON array:"""

    try:
        result = llm_client.complete_system(
            system=system_prompt,
            user=user_prompt,
            command="subdomain-validation",
        )
        
        response_text = result.get("text", "").strip()
        
        # Parse JSON
        import json
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        
        if start == -1 or end == 0:
            return []
        
        decisions = json.loads(response_text[start:end])
        
        resolutions = []
        for decision in decisions:
            pair_idx = decision.get("pair", 0) - 1
            action = decision.get("action", "keep_both")
            
            if 0 <= pair_idx < len(issues):
                issue = issues[pair_idx]
                
                if action == "keep_first":
                    # Parse related_to to get just the subdomain name
                    related = issue.related_to.split(" (")[0] if " (" in issue.related_to else issue.related_to
                    # Find which domain has the related subdomain
                    for domain, subs in domains.items():
                        if related in subs:
                            resolutions.append({
                                "action": "merge",
                                "keep": issue.subdomain,
                                "drop": related,
                                "domain": domain,
                            })
                            break
                
                elif action == "keep_second":
                    related = issue.related_to.split(" (")[0] if " (" in issue.related_to else issue.related_to
                    resolutions.append({
                        "action": "merge",
                        "keep": related,
                        "drop": issue.subdomain,
                        "domain": issue.domain,
                    })
        
        return resolutions
        
    except Exception as e:
        print(f"[SubdomainValidator] LLM resolution error: {e}", flush=True)
        return []


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def print_validation_report(result: ValidationResult) -> str:
    """Generate a human-readable validation report."""
    lines = [
        "=" * 60,
        "SUBDOMAIN VALIDATION REPORT",
        "=" * 60,
        "",
        f"Status: {'✅ VALID' if result.valid else '❌ NEEDS ATTENTION'}",
        f"Subdomains: {result.stats.get('original_count', 0)} → {result.stats.get('final_count', 0)}",
        f"Removed: {result.stats.get('removed_count', 0)}",
        "",
    ]
    
    if result.issues:
        lines.append("Issues Found:")
        for issue in result.issues:
            icon = "❌" if issue.severity == "error" else "⚠️" if issue.severity == "warning" else "ℹ️"
            lines.append(f"  {icon} {issue}")
        lines.append("")
    
    if result.merges_applied:
        lines.append("Merges Applied:")
        for kept, dropped, domain in result.merges_applied:
            lines.append(f"  • '{dropped}' → '{kept}' (in {domain})")
        lines.append("")
    
    lines.append("Final Structure:")
    for domain, subs in result.domains.items():
        lines.append(f"  📁 {domain} ({len(subs)} subdomains)")
        for sub in subs:
            lines.append(f"      • {sub}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)
