"""Hiring and onboarding management for AI agents.

Handles job description generation, agent creation from role templates,
onboarding plan design, probation evaluation, and team placement.
"""

import uuid
from typing import Any


class HiringManager:
    """Manages the hiring lifecycle for AI agents within a company."""

    def generate_job_description(
        self,
        role: str,
        department: str,
        responsibilities: list[str],
        required_skills: list[str],
    ) -> dict[str, Any]:
        """Generate a structured job description.

        Args:
            role: The role title.
            department: Department name.
            responsibilities: List of role responsibilities.
            required_skills: List of required skills.

        Returns:
            Dict with title, department, responsibilities, required_skills,
            preferred_skills, and description.
        """
        # Generate preferred skills based on role patterns
        preferred_skills = self._derive_preferred_skills(role, required_skills)

        description = (
            f"AI Agent role: {role} in {department} department. "
            f"Responsible for: {', '.join(responsibilities[:3])}. "
            f"Requires expertise in: {', '.join(required_skills[:3])}."
        )

        return {
            "title": role,
            "department": department,
            "responsibilities": responsibilities,
            "required_skills": required_skills,
            "preferred_skills": preferred_skills,
            "description": description,
        }

    def create_agent_from_role(
        self, company_id: uuid.UUID, role_template: dict[str, Any]
    ) -> dict[str, Any]:
        """Return agent config dict ready to construct Agent model.

        Template should contain: role, name, title, skills, tools, budget_monthly_cents.

        Args:
            company_id: The company this agent belongs to.
            role_template: Dict with role configuration.

        Returns:
            Dict with all fields needed to instantiate an Agent model.
        """
        return {
            "id": uuid.uuid4(),
            "company_id": company_id,
            "name": role_template.get("name", f"Agent-{role_template.get('role', 'unknown')}"),
            "title": role_template.get("title", role_template.get("role", "Agent")),
            "role": role_template.get("role", "worker"),
            "skills": role_template.get("skills", []),
            "tools": role_template.get("tools", []),
            "capabilities": role_template.get("capabilities", []),
            "budget_monthly_cents": role_template.get("budget_monthly_cents", 0),
            "spent_monthly_cents": 0,
            "status": "idle",
            "performance_score": None,
        }

    def design_onboarding(
        self, agent_id: uuid.UUID, role: str
    ) -> list[dict[str, Any]]:
        """Return onboarding plan as a list of steps.

        Covers: configure_skills, assign_tools, set_permissions, initial_tasks.

        Args:
            agent_id: The agent being onboarded.
            role: The role for context-specific onboarding.

        Returns:
            List of step dicts with step number, action, description, and status.
        """
        steps = [
            {
                "step": 1,
                "action": "configure_skills",
                "description": f"Configure skill set appropriate for {role} role",
                "status": "pending",
            },
            {
                "step": 2,
                "action": "assign_tools",
                "description": f"Assign tools and integrations needed for {role}",
                "status": "pending",
            },
            {
                "step": 3,
                "action": "set_permissions",
                "description": f"Set access permissions and security scope for {role}",
                "status": "pending",
            },
            {
                "step": 4,
                "action": "initial_tasks",
                "description": f"Assign introductory tasks to validate {role} capabilities",
                "status": "pending",
            },
        ]
        return steps

    def evaluate_probation(
        self,
        task_history: list[dict[str, Any]],
        probation_days: int = 30,
    ) -> dict[str, Any]:
        """Evaluate whether an agent passes probation.

        Args:
            task_history: List of task result dicts during probation period.
            probation_days: Length of probation period in days.

        Returns:
            Dict with passed (bool), score (float), and reasons (list[str]).
        """
        if not task_history:
            return {
                "passed": False,
                "score": 0.0,
                "reasons": ["no_tasks_completed_during_probation"],
            }

        # Calculate basic metrics
        total = len(task_history)
        completed = sum(
            1 for t in task_history if t.get("status") == "completed"
        )
        completion_rate = completed / total if total > 0 else 0.0

        quality_scores = [
            t.get("quality_score", 0.0) for t in task_history
            if t.get("quality_score") is not None
        ]
        avg_quality = (
            sum(quality_scores) / len(quality_scores)
            if quality_scores
            else 0.0
        )

        # Score: weighted combination
        score = (completion_rate * 60 + avg_quality * 40)

        # Determine pass/fail and reasons
        reasons: list[str] = []
        passed = True

        if completion_rate < 0.6:
            passed = False
            reasons.append("low_completion_rate")

        if avg_quality < 0.5:
            passed = False
            reasons.append("low_quality_score")

        if total < 3:
            passed = False
            reasons.append("insufficient_task_volume")

        if passed:
            reasons.append("meets_all_criteria")

        return {
            "passed": passed,
            "score": round(score, 2),
            "reasons": reasons,
        }

    def recommend_team_placement(
        self,
        agent_skills: list[str],
        teams: list,
        team_agents: dict[uuid.UUID, list[list[str]]],
    ) -> dict[str, Any]:
        """Suggest best team based on skill overlap and team composition.

        team_agents maps team_id to list of agent skill lists.

        Args:
            agent_skills: Skills of the agent to place.
            teams: List of Team model instances.
            team_agents: Dict mapping team_id to lists of skill lists
                         for agents already on that team.

        Returns:
            Dict with recommended_team_id, reason, and skill_overlap score.
        """
        if not teams:
            return {
                "recommended_team_id": None,
                "reason": "no_teams_available",
                "skill_overlap": 0.0,
            }

        agent_skills_set = set(s.lower() for s in agent_skills)
        best_team = None
        best_overlap = -1.0
        best_reason = ""

        for team in teams:
            # Get all skills for the team's existing agents
            member_skill_lists = team_agents.get(team.id, [])
            team_skills_set: set[str] = set()
            for skill_list in member_skill_lists:
                team_skills_set.update(s.lower() for s in skill_list)

            # Calculate overlap (Jaccard similarity)
            if agent_skills_set or team_skills_set:
                intersection = agent_skills_set & team_skills_set
                union = agent_skills_set | team_skills_set
                overlap = len(intersection) / len(union) if union else 0.0
            else:
                overlap = 0.0

            if overlap > best_overlap:
                best_overlap = overlap
                best_team = team
                best_reason = (
                    f"Best skill overlap with team '{team.name}' "
                    f"({len(agent_skills_set & team_skills_set)} shared skills)"
                )

        return {
            "recommended_team_id": best_team.id if best_team else None,
            "reason": best_reason,
            "skill_overlap": round(best_overlap, 4),
        }

    def _derive_preferred_skills(
        self, role: str, required_skills: list[str]
    ) -> list[str]:
        """Derive preferred (nice-to-have) skills based on role context.

        Args:
            role: The role title.
            required_skills: Already required skills (excluded from preferred).

        Returns:
            List of preferred skill strings.
        """
        # Common complementary skills by role keywords
        skill_map: dict[str, list[str]] = {
            "engineer": ["testing", "documentation", "code_review", "ci_cd"],
            "manager": ["delegation", "mentoring", "planning", "reporting"],
            "analyst": ["visualization", "statistics", "communication", "sql"],
            "designer": ["prototyping", "user_research", "accessibility", "animation"],
            "researcher": ["writing", "experimentation", "data_analysis", "presentation"],
        }

        preferred: list[str] = []
        role_lower = role.lower()
        for keyword, skills in skill_map.items():
            if keyword in role_lower:
                preferred.extend(
                    s for s in skills if s not in required_skills
                )

        # If no match, provide generic preferred skills
        if not preferred:
            preferred = [
                s for s in ["communication", "collaboration", "problem_solving"]
                if s not in required_skills
            ]

        return preferred
