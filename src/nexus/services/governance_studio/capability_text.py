"""Human-readable text for the capability catalogue.

This is presentation metadata only. A capability is always identified, authorized, granted,
audited and matched by its technical id (and tool name); nothing here is an authorization key.
Names are written out because acronyms, providers and domain terms cannot be derived from an id.
An id with no entry (a tool added after this table) gets a deterministic fallback that never
touches its support or enforcement state.
"""

from __future__ import annotations

from typing import Any

UNAVAILABLE = "Description unavailable"

# id -> (display name, description, limitations or None, examples)
_T: dict[str, tuple[str, str, str | None, tuple[str, ...]]] = {
    # Organization: CEO tools
    "org.ceo_create_goal_or_work_order": (
        "Create a Goal or Work Order",
        "Allows the CEO to create a company goal or a work order (a task). Repeating a request "
        "with the same idempotency key does not create a duplicate.",
        None, ("Create the quarterly revenue goal", "Issue a work order for a market study")),
    "org.ceo_delegate_task_to_manager": (
        "Delegate a Task to a Manager",
        "Allows the CEO to assign an existing work task to a manager who reports to them. "
        "This queues a task attempt for that manager.",
        None, ()),
    "org.ceo_get_work_status": (
        "View Work Status",
        "Allows the CEO to read the company's live work orders, their tasks, current attempts, "
        "verification state, failures and verified results, straight from stored state.",
        "Read-only: it never starts, changes or verifies work.", ()),
    "org.ceo_get_manager_status": (
        "View Manager Status",
        "Allows the CEO to read one manager's team status from the latest organization snapshot.",
        None, ()),
    "org.ceo_get_organization_snapshot": (
        "View the Organization Snapshot",
        "Allows the CEO to read the latest precomputed organization snapshot, including its "
        "version, hash and freshness.",
        None, ()),
    "org.ceo_list_managers": (
        "List Company Managers",
        "Allows the CEO to view the company's managers, their direct reports and work states, "
        "taken from the latest snapshot.",
        None, ()),
    "org.ceo_list_pending_approvals": (
        "View Pending Approvals",
        "Allows the CEO to view approval requests that are waiting for a human. It does not "
        "allow the CEO to approve them.",
        "Read-only: the CEO cannot approve anything with this capability.", ()),
    "org.ceo_record_decision": (
        "Record an Executive Decision",
        "Allows the CEO to record a decision, commitment, risk or outcome in executive memory. "
        "It may supersede or resolve an earlier entry.",
        None, ()),
    "org.ceo_request_hire": (
        "Request a New Agent Hire",
        "Allows the CEO to submit a request for a new direct report. The hiring policy and a "
        "human decide; this does not bypass the required human approval.",
        "The CEO cannot approve a hire.", ()),
    "org.ceo_search_executive_memory": (
        "Search Executive Memory",
        "Allows the CEO to search executive memory (directives, decisions, commitments, "
        "delegations, hires, risks and outcomes), newest first.",
        "Memory is not status: the organization snapshot is the source of current status.", ()),
    # Organization: manager tools
    "org.manager_assign_work": (
        "Assign Work to a Direct Report",
        "Allows a manager to create one task under a work order delegated to them and assign "
        "it to a direct report, naming the deliverable expected. Repeating the request with "
        "the same idempotency key does not create a duplicate.",
        "Only direct reports, and only the manager's own delegated work orders.", ()),
    "org.manager_review_work": (
        "Verify or Reject Submitted Work",
        "Allows a manager to verify or reject a deliverable submitted by one of their direct "
        "reports. A rejection needs a reason and may allow one bounded retry.",
        "A manager cannot review their own work, or work of anyone who does not report to them.",
        ()),
    "org.manager_delegate_task": (
        "Delegate a Task to a Direct Report",
        "Allows a manager to assign an existing task to one of their direct reports. "
        "Repeating the request does not create a duplicate.",
        "Only direct reports. Company work only by the manager that owns its work order.",
        ()),
    "org.manager_employee_status": (
        "View a Direct Report's Status",
        "Allows a manager to read one direct report's current state, active task, progress, "
        "evidence, last success and latest failure.",
        None, ()),
    "org.manager_get_hiring_request": (
        "View a Hiring Request",
        "Allows a manager to read one of their own hiring requests.",
        None, ()),
    "org.manager_list_hiring_requests": (
        "List Hiring Requests",
        "Allows a manager to list their own hiring requests with status, policy decision, "
        "costs and the hired employee.",
        None, ()),
    "org.manager_list_reports": (
        "List Direct Reports",
        "Allows a manager to list their direct reports.",
        None, ()),
    "org.manager_request_hire": (
        "Request a New Team Member",
        "Allows a manager to submit a request for a new direct report. The company's hiring "
        "policy decides: auto-approved within explicit limits, otherwise a human approves or "
        "rejects it.",
        "A request is not an approval; the hiring policy or a human decides.", ()),
    "org.manager_rollup": (
        "View the Team Roll-up",
        "Allows a manager to read their team roll-up: active, queued, completed, failed or "
        "blocked, and stale work.",
        None, ()),
    "org.manager_task_evidence": (
        "View Task Evidence",
        "Allows a manager to read the attempts, results and evidence of a task held by one of "
        "their direct reports.",
        None, ()),
    "org.organization_get_snapshot": (
        "View the Team Organization Snapshot",
        "Allows a manager to read the latest precomputed organization snapshot and its "
        "freshness: their own team's projection, or the whole organization when a policy "
        "explicitly allows org-wide reporting.",
        None, ()),
    # Tools (MCP node registry)
    "tool.ai-chat": (
        "Chat with an AI Model",
        "Allows the agent to send a prompt to a language model and get a response.",
        None, ()),
    "tool.ai-sentiment": (
        "Analyze Text Sentiment",
        "Allows the agent to analyze the sentiment of a piece of text.",
        None, ()),
    "tool.ai-summarize": (
        "Summarize Text",
        "Allows the agent to summarize long text.",
        None, ()),
    "tool.ai-translate": (
        "Translate Text",
        "Allows the agent to translate text between languages.",
        None, ()),
    "tool.db-redis-get": (
        "Read a Redis Value",
        "Allows the agent to get a value from Redis.",
        "Classified as a write-level capability by the tool registry.", ()),
    "tool.db-redis-set": (
        "Write a Redis Value",
        "Allows the agent to set a value in Redis, replacing any value stored under that key.",
        None, ()),
    "tool.db-sqlite-query": (
        "Run a SQLite Query",
        "Allows the agent to execute SQL on the local SQLite database. A statement can change "
        "data, so this counts as a write capability.",
        None, ()),
    "tool.file-csv-parse": (
        "Parse CSV Data",
        "Allows the agent to parse CSV text into rows.",
        None, ()),
    "tool.file-json-parse": (
        "Parse JSON Data",
        "Allows the agent to parse a JSON string into an object.",
        None, ()),
    "tool.http-request": (
        "Make an HTTP Request",
        "Allows the agent to make an HTTP request (GET, POST, PUT or DELETE) to a URL. It is "
        "treated as arbitrary network access and as a way to post data outside NEXUS.",
        None, ("Call a partner's REST API", "Post JSON to a webhook")),
    "tool.msg-discord-send": (
        "Send a Discord Message",
        "Allows the agent to send a message to Discord.",
        None, ()),
    "tool.msg-slack-send": (
        "Send a Slack Message",
        "Allows the agent to send a message to a Slack channel.",
        None, ()),
    "tool.msg-telegram-send": (
        "Send a Telegram Message",
        "Allows the agent to send a Telegram message.",
        None, ()),
    "tool.msg-webhook-notify": (
        "Send a Webhook Notification",
        "Allows the agent to send a notification to a webhook URL.",
        None, ()),
    # Execution: autonomy-gated actions
    "exec.delete": (
        "Delete Data",
        "Covers actions classified as deleting data. The agent's autonomy level decides whether "
        "it runs, runs and notifies an operator, or waits for approval (levels L1 to L3).",
        None, ()),
    "exec.execute_code": (
        "Execute Code",
        "Covers actions classified as running code. The agent's autonomy level decides whether "
        "it runs, runs and notifies an operator, or waits for approval (levels L1 to L3).",
        None, ()),
    "exec.send_external_message": (
        "Send External Messages",
        "Covers actions classified as sending a message outside the company. The agent's "
        "autonomy level decides whether it runs, runs and notifies an operator, or waits for "
        "approval (levels L1 to L3).",
        None, ()),
    "exec.write_file": (
        "Write Files",
        "Covers actions classified as writing a file. The agent's autonomy level decides whether "
        "it runs, runs and notifies an operator, or waits for approval (levels L1 to L3).",
        None, ()),
    "exec.spend": (
        "Spend Money",
        "Covers actions classified as spending money. The agent's autonomy level decides whether "
        "it runs, runs and notifies an operator, or waits for approval (levels L1 to L3).",
        None, ()),
    # Computer use: not enforceable
    "computer.browser": (
        "Control a Web Browser",
        "Drives a browser, including signed-in sessions. NEXUS cannot currently enforce this: "
        "CLI agents run out of process, so no policy, grant or lockdown can prevent it.",
        None, ()),
    "computer.terminal": (
        "Run Terminal Commands",
        "Runs shell commands on the host. NEXUS cannot currently enforce this: CLI agents run "
        "out of process, so no policy, grant or lockdown can prevent it.",
        None, ()),
    "computer.filesystem_write": (
        "Write Files Outside the Workspace",
        "Writes files outside the agent workspace. NEXUS cannot currently enforce this: CLI "
        "agents run out of process, so no policy, grant or lockdown can prevent it.",
        None, ()),
    "computer.desktop": (
        "Control the Desktop",
        "Controls the desktop through screenshots and input. NEXUS cannot currently enforce "
        "this: CLI agents run out of process, so no policy, grant or lockdown can prevent it.",
        None, ()),
    # Data and providers: shown, not configured here
    "data.memory": (
        "Use Company Memory",
        "Allows the agent to read and write its scoped memory. Access is limited to this "
        "company by tenant isolation.",
        None, ()),
    "data.secrets": (
        "Use Bound Secrets",
        "Allows the agent to use secrets that are bound to it. Secret values are never shown or "
        "returned here.",
        None, ()),
    "provider.runtime": (
        "Run on a Runtime Provider",
        "Shows the CLI or model backend the agent runs on. This is informational; policy rules "
        "do not control it.",
        None, ()),
}

# Applied when an entry gives no limitation of its own. Wording follows each support state.
_SUPPORT_LIMIT = {
    "approval_only": "Policy cannot deny this. The agent's autonomy level decides whether it "
    "runs, notifies an operator or needs approval.",
    "display_only": "Shown for visibility. Tenant isolation or role checks limit it; policy "
    "rules do not.",
    "unsupported": "NEXUS cannot currently enforce this, so no policy, grant or lockdown "
    "applies to it.",
}


def humanize(cap_id: str) -> str:
    """Fallback name for an id with no entry: ``tool.my-new_tool`` -> ``My New Tool``."""
    tail = cap_id.split(".", 1)[-1]
    words = tail.replace("-", " ").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) or cap_id


def describe(cap_id: str, support: str) -> dict[str, Any]:
    """Display metadata for one capability. Never changes support or enforcement."""
    known = _T.get(cap_id)
    if known is None:
        return {
            "display_name": humanize(cap_id), "description": UNAVAILABLE,
            "limitations": _SUPPORT_LIMIT.get(support), "examples": [], "metadata_known": False,
        }
    name, description, limit, examples = known
    return {
        "display_name": name, "description": description,
        "limitations": limit or _SUPPORT_LIMIT.get(support), "examples": list(examples),
        "metadata_known": True,
    }


# State and reason code -> a sentence for a person. The stable code is returned separately and
# stays visible; this only restates it. Keys are (code, state), then code alone.
_PLAIN: dict[Any, str] = {
    "NOT_ENFORCEABLE": "NEXUS cannot currently enforce this, so nothing prevents it and it "
    "cannot be controlled here.",
    ("AUTONOMY_L3", "approval_required"): "The agent's autonomy level requires a person to "
    "approve each use first.",
    "AUTONOMY_L1": "The agent's autonomy level lets this run without asking.",
    "AUTONOMY_L2": "The agent's autonomy level lets this run and notifies an operator.",
    "RBAC_DENIED": "The agent's role is not allowed to run tools, so this is denied.",
    "RESTRICTION_ACTIVE": "A company lockdown or agent isolation is active, so this write or "
    "external capability is denied.",
    "TEMP_DENY": "A temporary deny is in force, so this is blocked until it expires or is revoked.",
    "POLICY_ALLOW": "A policy rule explicitly allows this.",
    ("POLICY_ALLOW", "approval_required"): "A policy rule allows this, but the agent's autonomy "
    "level requires approval first.",
    "POLICY_DENY": "A policy rule explicitly denies this.",
    "DEFAULT_ALLOW": "No policy rule mentions this, so it inherits the default, which is Allow.",
    ("DEFAULT_ALLOW", "approval_required"): "No policy rule mentions this and the default is "
    "Allow, but the agent's autonomy level requires approval first.",
    "DEFAULT_DENY": "No policy grants this capability, so the safe default is Deny.",
    "TEMP_ALLOW": "A temporary grant allows this for now. Without it the default would be Deny.",
    ("TEMP_ALLOW", "approval_required"): "A temporary grant allows this, but the agent's "
    "autonomy level requires approval first.",
    "GRANT_EXPIRED": "A temporary grant existed but has expired or been used up, so the safe "
    "default is Deny again.",
    "SECRET_BOUND": "Secrets are bound to this agent. Their values are never shown.",
    "NO_SECRET_BINDING": "No secrets are bound to this agent.",
    "NO_BACKEND": "The agent uses a CLI adapter but no backend is set, so it cannot run.",
    "PROVIDER_SET": "The agent runs on the provider shown. This is informational.",
    "TENANT_SCOPED": "Always limited to this company's data by tenant isolation.",
}


def plain_explanation(code: str, state: str, fallback: str) -> str:
    """A sentence for a person; ``fallback`` (the engine's own wording) for any other code."""
    return _PLAIN.get((code, state)) or _PLAIN.get(code) or fallback
