# kernel/memory_policy.py
"""
v0.5.7 — Memory Policy Binding

Policy layer for memory operations:
- Pre-store guards: validate/transform memories before storage
- Recall transparency: annotate recalled memories with context
- Mode-based filtering: different behavior per environment mode
- Salience policies: automatic salience adjustment
- Identity protection: special handling for identity-tagged memories

Integrates with PolicyEngine for consistent policy enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .memory_engine import MemoryItem, MemoryType


# -----------------------------------------------------------------------------
# Policy Configuration
# -----------------------------------------------------------------------------

@dataclass
class MemoryPolicyConfig:
    """
    Configuration for memory policies.
    """
    # Pre-store policies
    require_tags: bool = True                    # Require at least one tag
    auto_add_timestamp_tag: bool = True          # Add YYYY-MM tag automatically
    min_payload_length: int = 3                  # Minimum payload length
    max_payload_length: int = 50000              # Maximum payload length
    
    # Salience policies
    identity_salience_boost: float = 0.2         # Boost for identity-tagged memories
    procedural_salience_boost: float = 0.1       # Boost for procedural memories
    source_salience_modifiers: Dict[str, float] = field(default_factory=lambda: {
        "user": 0.0,           # No modifier for user-sourced
        "system": -0.1,        # Slight reduction for system-generated
        "import": -0.05,       # Slight reduction for imported
        "inference": -0.15,    # Larger reduction for inferred memories
    })
    
    # Mode-based policies
    mode_recall_filters: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "deep_work": {
            "exclude_types": ["episodic"],       # Exclude episodic in deep work
            "min_salience": 0.3,                 # Only high-salience memories
        },
        "reflection": {
            "include_types": ["episodic", "semantic"],  # Focus on experiences
            "boost_tags": ["reflection", "insight", "lesson"],
        },
        "debug": {
            "include_all": True,                 # No filtering in debug
            "show_metadata": True,               # Include full metadata
        },
        "normal": {
            # Default behavior
        },
    })
    
    # Identity protection
    identity_tags: List[str] = field(default_factory=lambda: [
        "identity", "self", "values", "goals", "beliefs",
    ])
    protect_identity_from_decay: bool = True     # Slower decay for identity memories
    require_confirmation_for_identity: bool = True  # Flag for confirmation
    
    # Source attribution
    auto_attribute_source: bool = True           # Automatically set source field
    track_store_context: bool = True             # Include context in trace


# -----------------------------------------------------------------------------
# Policy Results
# -----------------------------------------------------------------------------

@dataclass
class PreStoreResult:
    """Result of pre-store policy check."""
    allowed: bool
    modified_item: Optional[Dict[str, Any]] = None  # Modified fields
    reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class RecallAnnotation:
    """Annotation added to recalled memory."""
    policy_notes: List[str] = field(default_factory=list)
    mode_context: Optional[str] = None
    relevance_boost: float = 0.0
    filtered_reason: Optional[str] = None


# -----------------------------------------------------------------------------
# Memory Policy Manager
# -----------------------------------------------------------------------------

class MemoryPolicy:
    """
    v0.5.7 Memory Policy Manager
    
    Provides policy hooks for memory operations:
    - pre_store(): Validate and transform before storage
    - post_recall(): Annotate and filter after recall
    - get_mode_filter(): Get recall filters for current mode
    - calculate_salience(): Apply salience policies
    
    Designed to be wired into MemoryManager/MemoryEngine.
    """

    def __init__(self, config: Optional[MemoryPolicyConfig] = None):
        self.config = config or MemoryPolicyConfig()
        self._current_mode: str = "normal"
        self._current_session: Optional[str] = None

    def set_mode(self, mode: str) -> None:
        """Set current environment mode."""
        self._current_mode = mode

    def set_session(self, session_id: str) -> None:
        """Set current session ID for context tracking."""
        self._current_session = session_id

    # ---------- Pre-Store Policy ----------

    def pre_store(
        self,
        payload: str,
        mem_type: str,
        tags: List[str],
        source: str = "user",
        salience: Optional[float] = None,
        trace: Optional[Dict[str, Any]] = None,
        module_tag: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> PreStoreResult:
        """
        Apply pre-store policies.
        
        Returns PreStoreResult with:
        - allowed: Whether storage should proceed
        - modified_item: Any field modifications to apply
        - reason: Rejection reason if not allowed
        - warnings: Non-blocking issues
        """
        warnings: List[str] = []
        modifications: Dict[str, Any] = {}
        
        # --- Validation ---
        
        # Check payload length
        if len(payload) < self.config.min_payload_length:
            return PreStoreResult(
                allowed=False,
                reason=f"Payload too short (min {self.config.min_payload_length} chars)",
            )
        
        if len(payload) > self.config.max_payload_length:
            return PreStoreResult(
                allowed=False,
                reason=f"Payload too long (max {self.config.max_payload_length} chars)",
            )
        
        # Check tags
        if self.config.require_tags and not tags:
            warnings.append("No tags provided, adding 'general'")
            modifications["tags"] = ["general"]
        
        # --- Transformations ---
        
        # Auto-add timestamp tag
        if self.config.auto_add_timestamp_tag:
            now = datetime.now(timezone.utc)
            month_tag = now.strftime("%Y-%m")
            current_tags = modifications.get("tags", list(tags))
            if month_tag not in current_tags:
                current_tags = list(current_tags) + [month_tag]
                modifications["tags"] = current_tags
        
        # --- Salience Calculation ---
        
        calculated_salience = self.calculate_salience(
            base_salience=salience,
            mem_type=mem_type,
            tags=modifications.get("tags", tags),
            source=source,
            module_tag=module_tag,
        )
        
        if salience is None or calculated_salience != salience:
            modifications["salience"] = calculated_salience
        
        # --- Source Attribution ---
        
        if self.config.auto_attribute_source and not source:
            modifications["source"] = "user"
        
        # --- Trace Enhancement ---
        
        if self.config.track_store_context:
            enhanced_trace = dict(trace or {})
            enhanced_trace["policy_version"] = "0.5.7"
            enhanced_trace["store_mode"] = self._current_mode
            if self._current_session:
                enhanced_trace["session_id"] = self._current_session
            enhanced_trace["store_timestamp"] = datetime.now(timezone.utc).isoformat()
            modifications["trace"] = enhanced_trace
        
        # --- Identity Protection ---
        
        is_identity = self._is_identity_tagged(modifications.get("tags", tags), module_tag)
        
        if is_identity and self.config.require_confirmation_for_identity:
            warnings.append("Identity-tagged memory flagged for confirmation")
            # Could set status to pending_confirmation here
        
        return PreStoreResult(
            allowed=True,
            modified_item=modifications if modifications else None,
            warnings=warnings,
        )

    # ---------- Salience Calculation ----------

    def calculate_salience(
        self,
        base_salience: Optional[float],
        mem_type: str,
        tags: List[str],
        source: str = "user",
        module_tag: Optional[str] = None,
    ) -> float:
        """
        Calculate final salience based on policies.
        
        Applies:
        - Source modifiers
        - Type-based boosts
        - Identity tag boost
        """
        # Start with base or type default
        from .memory_engine import DEFAULT_SALIENCE
        
        if base_salience is not None:
            salience = base_salience
        else:
            salience = DEFAULT_SALIENCE.get(mem_type, 0.5)
        
        # Apply source modifier
        source_mod = self.config.source_salience_modifiers.get(source, 0.0)
        salience += source_mod
        
        # Apply type boost
        if mem_type == "procedural":
            salience += self.config.procedural_salience_boost
        
        # Apply identity boost
        if self._is_identity_tagged(tags, module_tag):
            salience += self.config.identity_salience_boost
        
        # Clamp to valid range
        return max(0.01, min(1.0, salience))

    # ---------- Recall Policies ----------

    def get_mode_filter(self) -> Dict[str, Any]:
        """
        Get recall filter settings for current mode.
        """
        return self.config.mode_recall_filters.get(
            self._current_mode,
            self.config.mode_recall_filters.get("normal", {}),
        )

    def should_include_memory(
        self,
        mem_type: str,
        tags: List[str],
        salience: float,
        status: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a memory should be included in recall based on mode.
        
        Returns (include, reason_if_excluded).
        """
        mode_filter = self.get_mode_filter()
        
        # Debug mode includes everything
        if mode_filter.get("include_all"):
            return True, None
        
        # Check type exclusions
        exclude_types = mode_filter.get("exclude_types", [])
        if mem_type in exclude_types:
            return False, f"Type '{mem_type}' excluded in {self._current_mode} mode"
        
        # Check type inclusions (if specified, only include these)
        include_types = mode_filter.get("include_types")
        if include_types and mem_type not in include_types:
            return False, f"Type '{mem_type}' not in {self._current_mode} focus"
        
        # Check salience threshold
        min_salience = mode_filter.get("min_salience", 0.0)
        if salience < min_salience:
            return False, f"Salience {salience:.2f} below threshold {min_salience}"
        
        return True, None

    def post_recall(
        self,
        item_dict: Dict[str, Any],
    ) -> tuple[Dict[str, Any], RecallAnnotation]:
        """
        Apply post-recall policies.
        
        Returns (possibly_modified_item, annotation).
        """
        annotation = RecallAnnotation()
        annotation.mode_context = self._current_mode
        
        tags = item_dict.get("tags", [])
        module_tag = item_dict.get("module_tag")
        
        # Check for boost tags in reflection mode
        mode_filter = self.get_mode_filter()
        boost_tags = mode_filter.get("boost_tags", [])
        
        for tag in tags:
            if tag in boost_tags:
                annotation.relevance_boost += 0.1
                annotation.policy_notes.append(f"Boosted for '{tag}' tag in {self._current_mode} mode")
        
        # Identity memory note
        if self._is_identity_tagged(tags, module_tag):
            annotation.policy_notes.append("Identity-linked memory")
        
        # Debug mode: add metadata visibility note
        if mode_filter.get("show_metadata"):
            annotation.policy_notes.append("Full metadata visible (debug mode)")
        
        return item_dict, annotation

    # ---------- Policy Hooks for MemoryEngine ----------

    def create_pre_store_hook(self) -> Callable:
        """
        Create a pre-store hook function for MemoryEngine.
        
        The hook receives (item, meta) and returns True to allow, False to reject.
        """
        def hook(item: Any, meta: Dict[str, Any]) -> bool:
            # Extract fields from item
            result = self.pre_store(
                payload=item.payload,
                mem_type=item.type,
                tags=item.tags,
                source=item.source,
                salience=item.salience,
                trace=item.trace,
                module_tag=item.module_tag,
                meta=meta,
            )
            
            if not result.allowed:
                # Log rejection reason
                return False
            
            # Apply modifications
            if result.modified_item:
                for key, value in result.modified_item.items():
                    if hasattr(item, key):
                        setattr(item, key, value)
            
            return True
        
        return hook

    def create_post_recall_hook(self) -> Callable:
        """
        Create a post-recall hook function for MemoryEngine.
        
        The hook receives an item and returns the (possibly modified) item.
        """
        def hook(item: Any) -> Any:
            item_dict = item.to_dict() if hasattr(item, 'to_dict') else {}
            
            # Check if should be included
            include, reason = self.should_include_memory(
                mem_type=item.type,
                tags=item.tags,
                salience=item.salience,
                status=item.status,
            )
            
            if not include:
                # Mark as filtered (caller can check this)
                if hasattr(item, 'trace'):
                    item.trace = dict(item.trace or {})
                    item.trace['_filtered'] = True
                    item.trace['_filter_reason'] = reason
            
            return item
        
        return hook

    # ---------- Helpers ----------

    def _is_identity_tagged(
        self,
        tags: List[str],
        module_tag: Optional[str],
    ) -> bool:
        """Check if memory is identity-related."""
        if module_tag == "identity":
            return True
        
        for tag in tags:
            if tag in self.config.identity_tags:
                return True
        
        return False

    # ---------- Introspection ----------

    def get_config_summary(self) -> Dict[str, Any]:
        """Get current policy configuration."""
        return {
            "current_mode": self._current_mode,
            "require_tags": self.config.require_tags,
            "auto_timestamp_tag": self.config.auto_add_timestamp_tag,
            "identity_salience_boost": self.config.identity_salience_boost,
            "identity_tags": self.config.identity_tags,
            "protect_identity_from_decay": self.config.protect_identity_from_decay,
            "mode_filters": {
                mode: {
                    k: v for k, v in filters.items()
                    if k != "boost_tags"  # Simplify output
                }
                for mode, filters in self.config.mode_recall_filters.items()
            },
        }

    def get_active_policies(self) -> List[str]:
        """Get list of active policies for current mode."""
        policies = []
        
        if self.config.require_tags:
            policies.append("require_tags")
        if self.config.auto_add_timestamp_tag:
            policies.append("auto_timestamp_tag")
        if self.config.auto_attribute_source:
            policies.append("auto_source_attribution")
        if self.config.track_store_context:
            policies.append("track_store_context")
        
        mode_filter = self.get_mode_filter()
        if mode_filter.get("exclude_types"):
            policies.append(f"exclude_types:{','.join(mode_filter['exclude_types'])}")
        if mode_filter.get("min_salience"):
            policies.append(f"min_salience:{mode_filter['min_salience']}")
        if mode_filter.get("include_all"):
            policies.append("debug_include_all")
        
        return policies


# -----------------------------------------------------------------------------
# Factory Functions
# -----------------------------------------------------------------------------

def create_memory_policy(mode: str = "normal") -> MemoryPolicy:
    """
    Create a MemoryPolicy instance with default config.
    """
    policy = MemoryPolicy()
    policy.set_mode(mode)
    return policy


def create_strict_policy() -> MemoryPolicy:
    """
    Create a stricter memory policy for production use.
    """
    config = MemoryPolicyConfig(
        require_tags=True,
        min_payload_length=10,
        require_confirmation_for_identity=True,
        protect_identity_from_decay=True,
    )
    return MemoryPolicy(config)


def create_permissive_policy() -> MemoryPolicy:
    """
    Create a permissive policy for development/testing.
    """
    config = MemoryPolicyConfig(
        require_tags=False,
        min_payload_length=1,
        require_confirmation_for_identity=False,
        auto_add_timestamp_tag=False,
    )
    return MemoryPolicy(config)
