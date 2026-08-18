"""Meetings module for structured agent collaboration sessions.

Provides scheduling, conducting, and templating for various meeting types
including standups, planning sessions, retrospectives, design reviews,
and priority alignment meetings.
"""

from nexus.meetings.conductor import MeetingConductor
from nexus.meetings.scheduler import MeetingScheduler
from nexus.meetings.templates import MeetingTemplates

__all__ = ["MeetingScheduler", "MeetingConductor", "MeetingTemplates"]
