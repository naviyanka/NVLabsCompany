"""Organizational chart management.

Pure logic class that operates on lists of model instances passed in,
making it fully testable without database access.
"""

import uuid
from typing import Any


class OrgChart:
    """Builds and queries organizational hierarchy from agent relationships."""

    def build_hierarchy(
        self, company_id: uuid.UUID, agents: list
    ) -> dict[uuid.UUID, dict]:
        """Construct tree from manager_id relationships.

        Returns nested dict {agent_id: {agent: ..., reports: [...]}}.
        Only includes agents belonging to the specified company_id.
        """
        # Filter agents by company
        company_agents = [a for a in agents if a.company_id == company_id]

        # Build lookup
        nodes: dict[uuid.UUID, dict] = {}
        for agent in company_agents:
            nodes[agent.id] = {"agent": agent, "reports": []}

        # Link children to parents
        roots: dict[uuid.UUID, dict] = {}
        for agent in company_agents:
            node = nodes[agent.id]
            if agent.manager_id is None or agent.manager_id not in nodes:
                roots[agent.id] = node
            else:
                nodes[agent.manager_id]["reports"].append(node)

        return roots

    def get_reporting_chain(
        self, agent_id: uuid.UUID, agents: list
    ) -> list:
        """Return list from agent up to CEO (agent with no manager_id).

        The chain starts with the specified agent and ends with the root
        (CEO or top-level agent with no manager).
        """
        agent_map = {a.id: a for a in agents}
        chain: list = []
        current_id: uuid.UUID | None = agent_id

        while current_id is not None and current_id in agent_map:
            agent = agent_map[current_id]
            chain.append(agent)
            current_id = agent.manager_id

        return chain

    def get_direct_reports(
        self, manager_id: uuid.UUID, agents: list
    ) -> list:
        """Return agents with this manager_id."""
        return [a for a in agents if a.manager_id == manager_id]

    def get_department_structure(
        self,
        company_id: uuid.UUID,
        departments: list,
        teams: list,
        agents: list,
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Return nested dict dept -> teams -> agents.

        Structure: {dept_id: {"department": dept, "teams": {team_id: {"team": team, "agents": [...]}}}}
        """
        # Filter by company
        company_departments = [d for d in departments if d.company_id == company_id]
        company_teams = [t for t in teams if t.company_id == company_id]
        company_agents = [a for a in agents if a.company_id == company_id]

        structure: dict[uuid.UUID, dict[str, Any]] = {}

        for dept in company_departments:
            dept_teams: dict[uuid.UUID, dict[str, Any]] = {}
            for team in company_teams:
                if team.department_id == dept.id:
                    team_agents = [
                        a for a in company_agents if a.team_id == team.id
                    ]
                    dept_teams[team.id] = {"team": team, "agents": team_agents}

            structure[dept.id] = {"department": dept, "teams": dept_teams}

        return structure

    def calculate_span_of_control(
        self, manager_id: uuid.UUID, agents: list
    ) -> dict[str, int]:
        """Return direct, indirect, and total report counts for a manager.

        Returns {"direct": int, "indirect": int, "total": int}.
        """
        direct = [a for a in agents if a.manager_id == manager_id]
        direct_count = len(direct)

        # BFS for indirect reports
        indirect_count = 0
        queue = [a.id for a in direct]
        while queue:
            current_id = queue.pop(0)
            subordinates = [a for a in agents if a.manager_id == current_id]
            indirect_count += len(subordinates)
            queue.extend(a.id for a in subordinates)

        total = direct_count + indirect_count
        return {"direct": direct_count, "indirect": indirect_count, "total": total}

    def serialize_to_dict(self, hierarchy: dict) -> dict:
        """Return JSON-serializable representation of the hierarchy.

        Converts agent objects to dicts with id, name, title, and role.
        Recursively serializes the reports tree.
        """
        result: dict[str, Any] = {}
        for agent_id, node in hierarchy.items():
            agent = node["agent"]
            serialized_reports = []
            for report_node in node["reports"]:
                serialized_reports.append(
                    self._serialize_node(report_node)
                )
            result[str(agent_id)] = {
                "id": str(agent.id),
                "name": agent.name,
                "title": getattr(agent, "title", None),
                "role": agent.role,
                "reports": serialized_reports,
            }
        return result

    def _serialize_node(self, node: dict) -> dict[str, Any]:
        """Recursively serialize a single node."""
        agent = node["agent"]
        serialized_reports = []
        for report_node in node["reports"]:
            serialized_reports.append(self._serialize_node(report_node))
        return {
            "id": str(agent.id),
            "name": agent.name,
            "title": getattr(agent, "title", None),
            "role": agent.role,
            "reports": serialized_reports,
        }
