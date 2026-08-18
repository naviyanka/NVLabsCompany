"""Agent Persona - memory namespace and working context assembly.

The Persona system manages an agent's working memory and context window:
- Memory namespace isolation (each agent has its own memory space)
- Working context assembly (soul + recent memory + task context)
- Token budget allocation and enforcement
- Identity persistence and loading

Context budgeting ensures the agent's limited context window is used
effectively across identity, memory, and task information.
"""

from dataclasses import dataclass, field
from typing import Any

from nexus.identity.soul import Soul, system_prompt_from_soul


@dataclass
class ContextBudget:
    """Token allocation strategy for context window management.

    Divides available tokens between identity (soul/system prompt),
    memory (recent interactions and knowledge), and task (current
    objective and working data).

    Attributes:
        total_tokens: Total available tokens in the context window.
        identity_tokens: Tokens allocated for soul/system prompt.
        memory_tokens: Tokens allocated for recent memories.
        task_tokens: Tokens allocated for current task context.
    """

    total_tokens: int = 4096
    identity_tokens: int = 1024
    memory_tokens: int = 1024
    task_tokens: int = 2048


@dataclass
class WorkingContext:
    """Assembled context ready for model consumption.

    Represents the complete context window contents after applying
    the token budget. All fields are pre-truncated to fit within
    their allocated budget.

    Attributes:
        soul: The agent's Soul definition.
        recent_memories: List of recent memory entries (truncated to budget).
        task_context: Current task data (truncated to budget).
        system_prompt: Generated system prompt from soul.
        total_tokens: Estimated total token usage.
    """

    soul: Soul = field(default_factory=Soul)
    recent_memories: list[dict[str, Any]] = field(default_factory=list)
    task_context: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""
    total_tokens: int = 0


def allocate_budget(
    total_tokens: int,
    identity_weight: float = 0.25,
    memory_weight: float = 0.25,
    task_weight: float = 0.50,
) -> ContextBudget:
    """Split tokens proportionally between identity, memory, and task.

    Allocates the total token budget according to the given weights.
    Weights are normalized if they don't sum to 1.0.

    Args:
        total_tokens: Total available context window tokens.
        identity_weight: Proportion allocated to identity/soul (0.0-1.0).
        memory_weight: Proportion allocated to memories (0.0-1.0).
        task_weight: Proportion allocated to task context (0.0-1.0).

    Returns:
        A ContextBudget with token allocations.
    """
    # Normalize weights
    total_weight = identity_weight + memory_weight + task_weight
    if total_weight <= 0:
        total_weight = 1.0

    identity_frac = identity_weight / total_weight
    memory_frac = memory_weight / total_weight
    task_frac = task_weight / total_weight

    identity_alloc = int(total_tokens * identity_frac)
    memory_alloc = int(total_tokens * memory_frac)
    # Task gets the remainder to avoid rounding loss
    task_alloc = total_tokens - identity_alloc - memory_alloc

    return ContextBudget(
        total_tokens=total_tokens,
        identity_tokens=identity_alloc,
        memory_tokens=memory_alloc,
        task_tokens=task_alloc,
    )


def _estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses a simple heuristic of ~4 characters per token (common for
    English text with code). This avoids requiring a tokenizer library.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget.

    Args:
        text: The text to truncate.
        max_tokens: Maximum allowed tokens.

    Returns:
        The text, truncated if necessary.
    """
    if max_tokens <= 0:
        return ""
    estimated = _estimate_tokens(text)
    if estimated <= max_tokens:
        return text
    # Truncate by character count approximation
    max_chars = max_tokens * 4
    return text[:max_chars] + "..."


class Persona:
    """Manages an agent's identity, memory namespace, and working context.

    Each Persona instance represents a single agent's identity state,
    including their soul definition and memory namespace. Provides
    methods for assembling working context within token budgets.

    The in-memory store enables persistence and loading without requiring
    a database connection. Store has a configurable max size with LRU
    eviction to prevent unbounded memory growth in long-lived servers.
    """

    # Class-level storage for persistence (in-memory) with max size
    _store: dict[str, dict[str, Any]] = {}
    _store_max_size: int = 10000
    _store_access_order: list[str] = []

    def __init__(self, agent_id: str, namespace: str | None = None) -> None:
        """Initialize a Persona for a specific agent.

        Args:
            agent_id: Unique identifier for the agent.
            namespace: Optional memory namespace (defaults to agent_id).
        """
        self.agent_id = agent_id
        self.memory_namespace = namespace or f"agent_{agent_id}"
        self._memories: list[dict[str, Any]] = []
        self._soul: Soul | None = None

    @property
    def soul(self) -> Soul | None:
        """Get the agent's current soul definition."""
        return self._soul

    @soul.setter
    def soul(self, value: Soul) -> None:
        """Set the agent's soul definition."""
        self._soul = value

    def add_memory(self, memory: dict[str, Any]) -> None:
        """Add a memory entry to this agent's namespace.

        Args:
            memory: A dictionary containing memory data (e.g., content,
                    timestamp, type).
        """
        self._memories.append(memory)

    def get_memories(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent memories, most recent first.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            List of memory dictionaries.
        """
        return list(reversed(self._memories[-limit:]))

    def clear_memories(self) -> None:
        """Clear all memories in this agent's namespace."""
        self._memories.clear()

    def build_working_context(
        self,
        soul: Soul | None = None,
        memories: list[dict[str, Any]] | None = None,
        task: dict[str, Any] | None = None,
        budget: ContextBudget | None = None,
    ) -> WorkingContext:
        """Assemble a working context respecting the token budget.

        Combines soul/identity, recent memories, and current task into
        a WorkingContext. If the combined content exceeds the budget,
        memories are truncated first, then task context.

        Args:
            soul: The soul to use (defaults to self._soul).
            memories: Memory entries to include (defaults to self._memories).
            task: Current task context dictionary.
            budget: Token budget allocation (uses default if not provided).

        Returns:
            A WorkingContext with all components fit within budget.
        """
        effective_soul = soul or self._soul or Soul()
        effective_memories = memories if memories is not None else self.get_memories()
        effective_task = task or {}
        effective_budget = budget or ContextBudget()

        # Generate system prompt from soul
        raw_prompt = system_prompt_from_soul(effective_soul)
        system_prompt = _truncate_to_tokens(raw_prompt, effective_budget.identity_tokens)
        identity_tokens_used = _estimate_tokens(system_prompt)

        # Fit memories within memory budget
        fitted_memories: list[dict[str, Any]] = []
        memory_tokens_used = 0
        for mem in effective_memories:
            mem_text = str(mem)
            mem_tokens = _estimate_tokens(mem_text)
            if memory_tokens_used + mem_tokens > effective_budget.memory_tokens:
                break
            fitted_memories.append(mem)
            memory_tokens_used += mem_tokens

        # Fit task context within task budget
        task_text = str(effective_task)
        task_tokens = _estimate_tokens(task_text)
        if task_tokens > effective_budget.task_tokens:
            # Truncate task context by removing keys until it fits
            fitted_task: dict[str, Any] = {}
            used = 0
            for key, value in effective_task.items():
                entry_text = f"{key}: {value}"
                entry_tokens = _estimate_tokens(entry_text)
                if used + entry_tokens > effective_budget.task_tokens:
                    break
                fitted_task[key] = value
                used += entry_tokens
            task_tokens = used
        else:
            fitted_task = dict(effective_task)

        total_used = identity_tokens_used + memory_tokens_used + task_tokens

        return WorkingContext(
            soul=effective_soul,
            recent_memories=fitted_memories,
            task_context=fitted_task,
            system_prompt=system_prompt,
            total_tokens=total_used,
        )

    def save_persona(self) -> None:
        """Persist this persona's state to the in-memory store.

        Saves the soul definition and memory namespace for later retrieval.
        Enforces a maximum store size with LRU eviction to prevent
        unbounded memory growth in long-lived servers.
        """
        data: dict[str, Any] = {
            "agent_id": self.agent_id,
            "namespace": self.memory_namespace,
            "memories": list(self._memories),
        }
        if self._soul is not None:
            data["soul"] = {
                "name": self._soul.name,
                "role": self._soul.role,
                "personality_traits": list(self._soul.personality_traits),
                "communication_style": self._soul.communication_style,
                "expertise": list(self._soul.expertise),
                "values": list(self._soul.values),
                "constraints": list(self._soul.constraints),
                "background": self._soul.background,
                "tone": self._soul.tone,
            }

        # Update access order for LRU tracking
        if self.agent_id in Persona._store_access_order:
            Persona._store_access_order.remove(self.agent_id)
        Persona._store_access_order.append(self.agent_id)

        # Evict oldest entries if over max size
        while len(Persona._store) >= Persona._store_max_size and Persona._store_access_order:
            oldest_id = Persona._store_access_order.pop(0)
            Persona._store.pop(oldest_id, None)

        Persona._store[self.agent_id] = data

    @classmethod
    def load_persona(cls, agent_id: str) -> "Persona | None":
        """Load a persona from the in-memory store.

        Updates access order for LRU tracking.

        Args:
            agent_id: The agent identifier to load.

        Returns:
            A Persona instance if found, None otherwise.
        """
        data = cls._store.get(agent_id)
        if data is None:
            return None

        # Update access order (move to most recently used)
        if agent_id in cls._store_access_order:
            cls._store_access_order.remove(agent_id)
        cls._store_access_order.append(agent_id)

        persona = cls(
            agent_id=data["agent_id"],
            namespace=data.get("namespace"),
        )
        persona._memories = list(data.get("memories", []))

        soul_data = data.get("soul")
        if soul_data is not None:
            persona._soul = Soul(**soul_data)

        return persona

    @classmethod
    def clear_store(cls) -> None:
        """Clear the in-memory persona store (useful for testing)."""
        cls._store.clear()
        cls._store_access_order.clear()
