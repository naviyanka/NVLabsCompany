"""Meeting templates for structured agent collaboration sessions.

Provides predefined templates for common meeting types with sections,
prompts, expected formats, duration, and required roles.
"""


class MeetingTemplates:
    """Provides structured templates for different meeting types.

    Each template defines the meeting structure including sections with
    prompts and expected response formats, estimated duration, and the
    roles required for the meeting to be effective.
    """

    @classmethod
    def get_standup_template(cls) -> dict:
        """Get the daily standup meeting template.

        A brief synchronization meeting where agents report blockers,
        progress, and next steps.

        Returns:
            Template dict with meeting_type, sections, duration_minutes,
            and required_roles.
        """
        return {
            "meeting_type": "standup",
            "sections": [
                {
                    "name": "blockers",
                    "prompt": "What is currently blocking your progress?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "progress",
                    "prompt": "What have you accomplished since the last standup?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "next_steps",
                    "prompt": "What do you plan to work on next?",
                    "expected_format": "bullet_list",
                },
            ],
            "duration_minutes": 15,
            "required_roles": ["facilitator", "required"],
        }

    @classmethod
    def get_planning_template(cls) -> dict:
        """Get the planning meeting template.

        A session for defining goals, assessing capacity, selecting tasks,
        and assigning work across agents.

        Returns:
            Template dict with meeting_type, sections, duration_minutes,
            and required_roles.
        """
        return {
            "meeting_type": "planning",
            "sections": [
                {
                    "name": "goal",
                    "prompt": "What is the primary goal for this planning period?",
                    "expected_format": "paragraph",
                },
                {
                    "name": "capacity",
                    "prompt": "What is each agent's available capacity for this period?",
                    "expected_format": "table",
                },
                {
                    "name": "task_selection",
                    "prompt": "Which tasks should be prioritized and selected for this period?",
                    "expected_format": "ranked_list",
                },
                {
                    "name": "assignments",
                    "prompt": "Who is assigned to each selected task?",
                    "expected_format": "table",
                },
            ],
            "duration_minutes": 60,
            "required_roles": ["facilitator", "required"],
        }

    @classmethod
    def get_retrospective_template(cls) -> dict:
        """Get the retrospective meeting template.

        A reflective session for identifying what went well, what to
        improve, and specific actions to take.

        Returns:
            Template dict with meeting_type, sections, duration_minutes,
            and required_roles.
        """
        return {
            "meeting_type": "retrospective",
            "sections": [
                {
                    "name": "went_well",
                    "prompt": "What went well during this period?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "improve",
                    "prompt": "What could be improved?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "actions",
                    "prompt": "What specific actions will we take to improve?",
                    "expected_format": "action_items",
                },
            ],
            "duration_minutes": 45,
            "required_roles": ["facilitator", "required"],
        }

    @classmethod
    def get_design_review_template(cls) -> dict:
        """Get the design review meeting template.

        A structured review session for evaluating proposals, providing
        critique, making decisions, and defining next steps.

        Returns:
            Template dict with meeting_type, sections, duration_minutes,
            and required_roles.
        """
        return {
            "meeting_type": "design_review",
            "sections": [
                {
                    "name": "proposal",
                    "prompt": "Present the design proposal for review.",
                    "expected_format": "paragraph",
                },
                {
                    "name": "critique",
                    "prompt": "What concerns, risks, or improvements do you see in this proposal?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "decision",
                    "prompt": "What is the decision on this proposal? (approve/revise/reject)",
                    "expected_format": "paragraph",
                },
                {
                    "name": "next_steps",
                    "prompt": "What are the next steps following this decision?",
                    "expected_format": "action_items",
                },
            ],
            "duration_minutes": 60,
            "required_roles": ["facilitator", "required"],
        }

    @classmethod
    def get_priority_alignment_template(cls) -> dict:
        """Get the priority alignment meeting template.

        A consensus-building session for aligning on goals, discussing
        priorities, evaluating trade-offs, and reaching agreement.

        Returns:
            Template dict with meeting_type, sections, duration_minutes,
            and required_roles.
        """
        return {
            "meeting_type": "priority_alignment",
            "sections": [
                {
                    "name": "goals",
                    "prompt": "What are the current high-level goals we need to align on?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "priorities",
                    "prompt": "How should these goals be prioritized?",
                    "expected_format": "ranked_list",
                },
                {
                    "name": "trade_offs",
                    "prompt": "What trade-offs are we making with these priorities?",
                    "expected_format": "bullet_list",
                },
                {
                    "name": "consensus",
                    "prompt": "Do all participants agree on the final priority ordering?",
                    "expected_format": "paragraph",
                },
            ],
            "duration_minutes": 45,
            "required_roles": ["facilitator", "required"],
        }

    @classmethod
    def get_all_templates(cls) -> dict[str, dict]:
        """Get all available meeting templates indexed by meeting type.

        Returns:
            Dict mapping meeting_type strings to their template dicts.
        """
        return {
            "standup": cls.get_standup_template(),
            "planning": cls.get_planning_template(),
            "retrospective": cls.get_retrospective_template(),
            "design_review": cls.get_design_review_template(),
            "priority_alignment": cls.get_priority_alignment_template(),
        }
