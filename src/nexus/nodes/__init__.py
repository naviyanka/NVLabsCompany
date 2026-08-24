"""NEXUS Node Library — 146 workflow nodes across 31 categories.

Ported from OpenCompany's n8n-style node architecture. Each node represents
a discrete capability that can be wired into pipelines and workflows.

Categories:
- AI (LLM, Embeddings, Vision, Speech, Classification)
- Communication (Email, SMS, Slack, Discord, WhatsApp, Telegram)
- Data (Database, Spreadsheet, CSV, JSON Transform)
- DevOps (Git, Docker, CI/CD, Deploy)
- File (Read, Write, Upload, Download, Convert)
- HTTP (REST, GraphQL, WebSocket, Webhook)
- Schedule (Cron, Interval, Delay, Once)
- Trigger (Webhook, Event, File Watch, Queue)
- Cloud (AWS, GCP, Azure, Cloudflare)
- Browser (Scrape, Navigate, Screenshot, PDF)
- Device (Android, Desktop Automation)
- Finance (Stripe, PayPal, Invoice)
- Productivity (Calendar, Tasks, Notes, Notion)
- Security (Auth, Encrypt, Scan, Audit)
- Utility (Transform, Filter, Merge, Split, Loop)
"""

from nexus.nodes.registry import NodeRegistry, NodeDefinition, NodeCategory

__all__ = ["NodeRegistry", "NodeDefinition", "NodeCategory"]
