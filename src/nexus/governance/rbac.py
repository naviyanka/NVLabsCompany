"""RBAC Manager - role-based access control with capability-based permissions."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Permission:
    """A single permission grant.

    Attributes:
        id: Unique permission identifier.
        action: The action being permitted (e.g., 'execute', 'read', 'write').
        resource_type: The type of resource (e.g., 'tool', 'agent', 'task').
        resource_id: Specific resource ID, or '*' for all resources of the type.
        conditions: Optional conditions for the permission.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    action: str = ""
    resource_type: str = ""
    resource_id: str = "*"
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Role:
    """A named role with a set of permissions.

    Attributes:
        name: The role name.
        description: Human-readable description.
        permissions: Permissions included in this role.
    """

    name: str
    description: str = ""
    permissions: list[Permission] = field(default_factory=list)


# Standard role definitions
ROLE_ADMIN = Role(
    name="admin",
    description="Full system access - can manage all resources and configurations",
    permissions=[
        Permission(action="*", resource_type="*", resource_id="*"),
    ],
)

ROLE_MANAGER = Role(
    name="manager",
    description="Can manage agents, tasks, and view budgets within their scope",
    permissions=[
        Permission(action="read", resource_type="*", resource_id="*"),
        Permission(action="write", resource_type="task", resource_id="*"),
        Permission(action="write", resource_type="agent", resource_id="*"),
        Permission(action="execute", resource_type="tool", resource_id="*"),
        Permission(action="approve", resource_type="approval", resource_id="*"),
    ],
)

ROLE_AGENT = Role(
    name="agent",
    description="Can execute assigned tasks and use permitted tools",
    permissions=[
        Permission(action="read", resource_type="task", resource_id="*"),
        Permission(action="write", resource_type="task", resource_id="*"),
        Permission(action="execute", resource_type="tool", resource_id="*"),
        Permission(action="read", resource_type="memory", resource_id="*"),
        Permission(action="write", resource_type="memory", resource_id="*"),
    ],
)

ROLE_VIEWER = Role(
    name="viewer",
    description="Read-only access to resources",
    permissions=[
        Permission(action="read", resource_type="*", resource_id="*"),
    ],
)

# Default roles registry
STANDARD_ROLES: dict[str, Role] = {
    "admin": ROLE_ADMIN,
    "manager": ROLE_MANAGER,
    "agent": ROLE_AGENT,
    "viewer": ROLE_VIEWER,
}


def permission_grants(
    permission: Permission,
    action: str,
    resource_type: str,
    resource_id: str | None = "*",
) -> bool:
    """Whether one permission entry covers the requested action.

    A ``"*"`` in the permission's action, resource type or resource ID matches
    anything in that position.
    """
    if permission.action != "*" and permission.action != action:
        return False

    if permission.resource_type != "*" and permission.resource_type != resource_type:
        return False

    if resource_id and permission.resource_id != "*":
        if permission.resource_id != resource_id:
            return False

    return True


def role_allows(
    role_name: str,
    action: str,
    resource_type: str,
    resource_id: str = "*",
) -> bool:
    """Whether a named standard role permits an action on a resource.

    This is the stateless counterpart to :meth:`RBACManager.check_permission`,
    for callers that know a role name rather than an actor id — request
    authorization reads the role off the caller's membership or API key, and
    must not have to register that caller in a process-global permission table
    first.

    An unrecognised role name grants nothing.
    """
    role = STANDARD_ROLES.get(role_name)
    if role is None:
        return False

    return any(
        permission_grants(perm, action, resource_type, resource_id)
        for perm in role.permissions
    )


class RBACManager:
    """Role-based access control manager with capability-based tool access.

    Manages permission grants for actors (users, agents, services) and
    provides efficient permission checking for authorization decisions.
    """

    def __init__(self, roles: dict[str, Role] | None = None) -> None:
        """Initialize the RBAC manager.

        Args:
            roles: Available role definitions. Uses standard roles if None.
        """
        self._roles = roles or STANDARD_ROLES
        # actor_id -> list of permissions
        self._actor_permissions: dict[uuid.UUID, list[Permission]] = {}
        # actor_id -> role name
        self._actor_roles: dict[uuid.UUID, str] = {}

    def assign_role(self, actor_id: uuid.UUID, role_name: str) -> bool:
        """Assign a role to an actor.

        Args:
            actor_id: The actor to assign the role to.
            role_name: The role name (must exist in configured roles).

        Returns:
            True if the role was assigned, False if role not found.
        """
        if role_name not in self._roles:
            return False
        self._actor_roles[actor_id] = role_name
        return True

    def grant_permission(
        self, actor_id: uuid.UUID, permission: Permission
    ) -> None:
        """Grant an explicit permission to an actor.

        This is in addition to any role-based permissions.

        Args:
            actor_id: The actor to grant the permission to.
            permission: The permission to grant.
        """
        if actor_id not in self._actor_permissions:
            self._actor_permissions[actor_id] = []
        self._actor_permissions[actor_id].append(permission)

    def revoke_permission(
        self, actor_id: uuid.UUID, permission: Permission
    ) -> bool:
        """Revoke a specific permission from an actor.

        Args:
            actor_id: The actor to revoke from.
            permission: The permission to revoke.

        Returns:
            True if the permission was found and revoked.
        """
        perms = self._actor_permissions.get(actor_id, [])
        for i, p in enumerate(perms):
            if p.id == permission.id:
                perms.pop(i)
                return True
        return False

    def check_permission(
        self,
        actor_id: uuid.UUID,
        actor_type: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
    ) -> bool:
        """Check if an actor has permission for an action.

        Checks both role-based and explicitly granted permissions.

        Args:
            actor_id: The actor requesting access.
            actor_type: Type of actor (user, agent, system).
            action: The action to check (read, write, execute, etc.).
            resource_type: The type of resource.
            resource_id: Specific resource ID. None checks type-level access.

        Returns:
            True if the actor has the required permission.
        """
        # Check role-based permissions
        role_name = self._actor_roles.get(actor_id)
        if role_name:
            role = self._roles.get(role_name)
            if role:
                for perm in role.permissions:
                    if self._permission_matches(
                        perm, action, resource_type, resource_id
                    ):
                        return True

        # Check explicit permissions
        explicit_perms = self._actor_permissions.get(actor_id, [])
        for perm in explicit_perms:
            if self._permission_matches(perm, action, resource_type, resource_id):
                return True

        return False

    def _permission_matches(
        self,
        permission: Permission,
        action: str,
        resource_type: str,
        resource_id: str | None,
    ) -> bool:
        """Check if a permission entry matches the requested action.

        Args:
            permission: The permission to check.
            action: Requested action.
            resource_type: Requested resource type.
            resource_id: Requested resource ID.

        Returns:
            True if the permission grants the requested access.
        """
        return permission_grants(permission, action, resource_type, resource_id)

    def get_permissions(self, actor_id: uuid.UUID) -> list[Permission]:
        """Get all effective permissions for an actor.

        Combines role-based and explicit permissions.

        Args:
            actor_id: The actor to get permissions for.

        Returns:
            List of all effective Permission objects.
        """
        all_perms: list[Permission] = []

        # Role permissions
        role_name = self._actor_roles.get(actor_id)
        if role_name:
            role = self._roles.get(role_name)
            if role:
                all_perms.extend(role.permissions)

        # Explicit permissions
        all_perms.extend(self._actor_permissions.get(actor_id, []))

        return all_perms

    def get_role(self, actor_id: uuid.UUID) -> str | None:
        """Get the assigned role for an actor.

        Args:
            actor_id: The actor to check.

        Returns:
            Role name, or None if no role assigned.
        """
        return self._actor_roles.get(actor_id)
