"""Built-in Policies - pre-configured safety policies for NEXUS governance.

These policies implement common safety constraints that should be active
in most production deployments. They can be enabled/disabled individually.
"""

from nexus.governance.policies.engine import Policy, PolicyRule


# 1. Any deployment action needs human approval
production_deploy_requires_approval = Policy(
    name="production_deploy_requires_approval",
    description="Any deployment action requires human approval",
    priority=90,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["deploy", "release", "rollout"],
                "resource_type": "production",
            },
        ),
    ],
)

# 2. Spending over threshold needs approval
financial_operations_require_approval = Policy(
    name="financial_operations_require_approval",
    description="Financial operations exceeding threshold require approval",
    priority=85,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["spend", "purchase", "subscribe", "transfer"],
                "cost_min": 10000,  # $100.00 in cents
            },
        ),
    ],
)

# 3. Creating privileged agents needs approval
agent_creation_requires_approval = Policy(
    name="agent_creation_requires_approval",
    description="Creating privileged agents requires human approval",
    priority=80,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["create", "promote"],
                "resource_type": "agent",
                "sensitivity_level": ["high", "critical"],
            },
        ),
    ],
)

# 4. Sending emails/messages externally needs approval
external_communication_requires_approval = Policy(
    name="external_communication_requires_approval",
    description="External communications require human approval",
    priority=75,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["send_email", "send_message", "post_external"],
                "resource_type": ["email", "message", "external_api"],
            },
        ),
    ],
)

# 5. Any delete of production data needs approval
data_deletion_requires_approval = Policy(
    name="data_deletion_requires_approval",
    description="Deletion of production data requires human approval",
    priority=88,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["delete", "purge", "truncate"],
                "sensitivity_level": ["high", "critical"],
            },
        ),
    ],
)

# 6. Agents cannot modify their own governance rules
self_modification_denied = Policy(
    name="self_modification_denied",
    description="Agents cannot modify their own governance rules",
    priority=100,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="deny",
            conditions={
                "actor_type": "agent",
                "action": ["modify_policy", "disable_policy", "delete_policy"],
                "resource_type": "governance",
            },
        ),
    ],
)

# 7. Strict tenant isolation
cross_tenant_access_denied = Policy(
    name="cross_tenant_access_denied",
    description="Cross-tenant access is strictly denied",
    priority=100,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="deny",
            conditions={
                "action": ["read", "write", "execute", "delete"],
                "environment": {"cross_tenant": True},
            },
        ),
    ],
)

# 8. Hard budget limit enforcement
budget_exceeded_deny = Policy(
    name="budget_exceeded_deny",
    description="Actions exceeding hard budget limit are denied",
    priority=95,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="budget_cap",
            conditions={
                "cost_max": 500000,  # $5000.00 in cents
            },
        ),
    ],
)

# 9. Max operations per minute/hour per agent
rate_limit_per_agent = Policy(
    name="rate_limit_per_agent",
    description="Rate limit operations per agent",
    priority=70,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="rate_limit",
            conditions={
                "actor_type": "agent",
            },
        ),
    ],
)

# 10. Certain operations blocked outside business hours (9am-5pm)
nighttime_restricted = Policy(
    name="nighttime_restricted",
    description="High-risk operations restricted outside business hours (9-17)",
    priority=60,
    enabled=True,
    rules=[
        PolicyRule(
            rule_type="require_approval",
            conditions={
                "action": ["deploy", "delete", "modify_policy"],
                "time_hour_min": 17,
                "time_hour_max": 8,
            },
        ),
    ],
)


# Registry of all built-in policies
BUILTIN_POLICIES: list[Policy] = [
    production_deploy_requires_approval,
    financial_operations_require_approval,
    agent_creation_requires_approval,
    external_communication_requires_approval,
    data_deletion_requires_approval,
    self_modification_denied,
    cross_tenant_access_denied,
    budget_exceeded_deny,
    rate_limit_per_agent,
    nighttime_restricted,
]
