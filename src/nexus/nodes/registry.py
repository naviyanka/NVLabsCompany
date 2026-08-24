"""Node Registry — manages all available workflow nodes.

Each node has:
- A unique ID and category
- Input/output schema
- An execute function (async)
- Optional credentials requirement

Nodes are used by the pipeline runner and visual workflow builder.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class NodeCategory(str, Enum):
    """Categories for workflow nodes (31 categories from OpenCompany)."""
    AI = "ai"
    COMMUNICATION = "communication"
    DATA = "data"
    DEVOPS = "devops"
    FILE = "file"
    HTTP = "http"
    SCHEDULE = "schedule"
    TRIGGER = "trigger"
    CLOUD = "cloud"
    BROWSER = "browser"
    DEVICE = "device"
    FINANCE = "finance"
    PRODUCTIVITY = "productivity"
    SECURITY = "security"
    UTILITY = "utility"
    EMAIL = "email"
    MESSAGING = "messaging"
    DATABASE = "database"
    SEARCH = "search"
    ANALYTICS = "analytics"
    STORAGE = "storage"
    MONITORING = "monitoring"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    MEDIA = "media"
    SOCIAL = "social"
    CRM = "crm"
    ECOMMERCE = "ecommerce"
    VOICE = "voice"
    IOT = "iot"
    CUSTOM = "custom"


@dataclass
class NodeInput:
    """Definition of a node input parameter."""
    name: str
    type: str  # string, number, boolean, json, file, credential
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class NodeOutput:
    """Definition of a node output."""
    name: str
    type: str
    description: str = ""


@dataclass
class NodeDefinition:
    """Complete definition of a workflow node."""
    id: str
    name: str
    description: str
    category: NodeCategory
    icon: str = ""
    inputs: list[NodeInput] = field(default_factory=list)
    outputs: list[NodeOutput] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)  # Required credential types
    version: str = "1.0"
    execute_fn: Callable[..., Awaitable[Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to API-friendly dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "icon": self.icon,
            "inputs": [{"name": i.name, "type": i.type, "required": i.required, "default": i.default, "description": i.description} for i in self.inputs],
            "outputs": [{"name": o.name, "type": o.type, "description": o.description} for o in self.outputs],
            "credentials": self.credentials,
            "version": self.version,
        }


class NodeRegistry:
    """Central registry of all available workflow nodes."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeDefinition] = {}
        self._register_all()

    def _register_all(self) -> None:
        """Register all built-in nodes."""
        from nexus.nodes.categories.all_nodes import get_all_nodes
        for node in get_all_nodes():
            self._nodes[node.id] = node

    def get(self, node_id: str) -> NodeDefinition | None:
        """Get a node definition by ID."""
        return self._nodes.get(node_id)

    def list_all(self) -> list[NodeDefinition]:
        """List all registered nodes."""
        return list(self._nodes.values())

    def list_by_category(self, category: NodeCategory) -> list[NodeDefinition]:
        """List nodes in a specific category."""
        return [n for n in self._nodes.values() if n.category == category]

    def search(self, query: str) -> list[NodeDefinition]:
        """Search nodes by name or description."""
        q = query.lower()
        return [n for n in self._nodes.values() if q in n.name.lower() or q in n.description.lower()]

    @property
    def count(self) -> int:
        return len(self._nodes)

    @property
    def categories(self) -> list[str]:
        return sorted(set(n.category.value for n in self._nodes.values()))
