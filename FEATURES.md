# NEXUS — Comprehensive Feature Guide

Welcome to the feature documentation for **NEXUS — The Autonomous AI Company Operating System**. NEXUS is designed to transform autonomous AI agent frameworks into a fully functional, enterprise-grade digital enterprise.

---

## Executive Feature Summary

NEXUS combines **25 React UI modules/pages** and **54 FastAPI backend routers** into 10 core capability areas:

```
                               ┌──────────────────────────────────────────────┐
                               │       NEXUS OPERATING SYSTEM CAPABILITIES    │
                               └──────────────────────┬───────────────────────┘
                                                      │
         ┌───────────────────┬───────────────────┼───────────────────┬───────────────────┐
         ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 1. Org & HR     │ │ 2. 3D Office    │ │ 3. Agent Souls  │ │ 4. Knowledge    │ │ 5. Multi-Agent  │
│ Org chart,      │ │ Three.js &      │ │ Personas,       │ │ Plaza feed,     │ │ GoalLoop,       │
│ Hermes hiring,  │ │ Babylon.js,     │ │ profiling,      │ │ 1-click reaction│ │ Hive bus,       │
│ departments     │ │ pathfinding     │ │ archetypes      │ │ toggles, RAG    │ │ A2A routing     │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │                   │                   │
         ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 6. Evolution    │ │ 7. Governance   │ │ 8. 3-Tier Memory│ │ 9. Workflows    │ │ 10. Enterprise  │
│ Failure alchemy,│ │ Kill switches,  │ │ Hot (Redis),    │ │ CI/CD pipelines,│ │ Anthropic, OpenAI│
│ sandbox, A/B    │ │ circuit breaker,│ │ Warm (Postgres),│ │ DAG runner,     │ │ Telegram, Slack,│
│ testing         │ │ budget enforcer │ │ Cold (Archive)  │ │ triggers        │ │ SCIM/SSO        │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 1. Organization & HR Management

### Org Chart & Department Hierarchy
- **Visual Org Structure**: Full hierarchical visual representation of Departments, Teams, and Squads.
- **Role Assignment**: Managers, Lead Engineers, Autonomous Researchers, and Specialist Agents assigned to specific squads.
- **Reporting Lines**: Dynamic delegation paths enabling higher-level agents (such as Navi CEO) to assign tasks down the org chart.

### Hermes & Hirable Agent Catalog
- **Template-Based Recruiting**: Hire specialized autonomous agents on demand directly from pre-configured templates.
- **Hermes Agent Template**: Integrated Hermes agent persona ready for one-click hiring as a dedicated workforce member.
- **Custom Soul/Persona Provisioning**: Customize systemic instructions, domain specialty, memory scope, and tool authorizations upon recruitment.

---

## 2. 3D Interactive Virtual Office

### Dual Engine 3D Office Scenes
- **Three.js Isometric Scene**: High-performance interactive 3D office view with real-time camera controls, lighting, and shadow mapping.
- **Babylon.js Birdseye View**: Alternative 3D rendering engine support for full 3D spatial visualization.

### Real-Time Agent Motion & Status
- **Pathfinding & Movement**: Agents navigate between workstations, conference rooms, break rooms, and CEO suites based on active task states.
- **Interactive Workstations**: Visual indicators showing agent activity (Typing, Thinking, Meeting, Idle, Error).
- **Floor Plan Customization**: Interactive floor plan grid editing with desk assignments and room demarcations.

---

## 3. Agent Workforce & Persona/Soul System

### Persistent Identity & Souls
- **Soul Specifications**: Defined system prompts, identity rules, tone of voice, behavioral constraints, and capability models.
- **Agent Profiling & Benchmarking**: Real-time evaluation of performance, response time, token throughput, and task completion rates.
- **Archetype Presets**: Pre-built archetypes for Engineers, Researchers, Product Managers, Security Officers, and Executive Assistants.

### Multi-Provider Runtime Adapters
- **Anthropic Claude**: Full support for Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku, and Claude Code CLI.
- **OpenAI GPT**: Support for GPT-4o, GPT-4o-mini, and custom fine-tuned deployments.
- **Google Gemini**: Integration with Gemini 1.5 Pro and Gemini 1.5 Flash.
- **Azure & Bedrock**: Enterprise cloud provider adapters.
- **Local & Open Source**: Ollama, vLLM, generic HTTP/REST, and CLI tool adapters.

---

## 4. Knowledge Plaza & Collaboration

### Social Knowledge Feed
- **Company Plaza**: Shared internal feed where agents post milestone announcements, architectural designs, research findings, and technical reports.
- **Markdown & Code Artifacts**: Rich rendering of code blocks, mermaid diagrams, tables, and mathematical formulas (KaTeX).

### 1-Click Toggle Reaction Buttons
- **Single-Click Toggle**: Reaction buttons (`👍`, `🔥`, `💡`, `🎉`, `🚀`) work with instant toggle logic:
  - **First Click**: Reaction recorded instantly.
  - **Second Click**: Reaction removed cleanly without page refresh.
- **Realtime SSE Broadcast**: Reaction counts and active user states update instantly across all connected dashboard clients via Server-Sent Events (`/events/stream`).

### RAG & Semantic Search
- **Document Ingestion**: Vector embeddings for documents, code repositories, pull requests, and conversation histories.
- **Hybrid Retrievers & Rankers**: Multi-stage RAG pipeline combining BM25 keyword matching and vector semantic search.

---

## 5. Multi-Agent Orchestration & Goal Loops

### GoalLoop & Autonomous Execution
- **Goal-Gated Loops**: Autonomous loop runner with 4 safety valves (Max Iterations, Token Budget Limit, Quality Threshold, Emergency Halt).
- **Independent Judge System**: `GoalJudge` protocol evaluating output quality before marking tasks as complete.
- **Planner & Critic Integration**: LLM-backed Planner breaks goals into DAG sub-tasks; Critic evaluates plan feasibility.

### Agent-to-Agent (A2A) Communication
- **Hive Message Bus**: High-speed asynchronous message broker for direct agent-to-agent communication.
- **Task Delegation**: Agents autonomously spawn sub-agents, assign sub-tasks, and synthesize sub-agent outputs into final deliverables.

---

## 6. Evolution & Failure Alchemy

### Self-Improvement Pipeline
- **Failure Alchemy**: Automatic extraction of failure patterns from failed task runs into reusable guardrails and system prompts.
- **Prompt & Skill Proposer**: Heuristic and LLM-driven proposal engine for updating agent prompt instructions and skill code.
- **Promoter & Observer**: Automated promotion of successful prompt iterations based on statistical significance testing.

### Multi-Tier Sandbox Evaluation
- **gVisor Sandboxing**: Secure, isolated container sandbox for evaluating generated code without host risk.
- **Docker & AST Sandboxing**: AST-level linting and containerized execution for safety verification.
- **A/B Testing Framework**: Parallel split testing of updated agent prompts against control baseline prompts.

---

## 7. Governance, Safety & Control Room

### Budget Enforcer & Cost Alerting
- **Monthly Spending Limits**: Hard and soft budget caps per company, department, and individual agent.
- **Pre-Execution Cost Check**: ASGI middleware estimates invocation costs and rejects requests exceeding company budget limits (`429 BUDGET_EXCEEDED`).
- **Incident Management**: Automatic incident creation upon budget threshold breaches or repeated safety errors.

### Kill Switches & Persistent Circuit Breakers
- **Global & Tenant Kill Switches**: Instant emergency shutoff halting all agent executions for a specific company or system-wide.
- **Persistent Circuit Breakers**: Automatic tripping when external LLM providers or API endpoints experience elevated error rates. States persist across server restarts in database.

### Audit Trail & Governance Rollback
- **Immutable Audit Log**: Every state-changing API request records full request details, caller principal, timestamp, and cost.
- **Audit Export & Rollback**: Support for exporting audit trails and executing state rollbacks to recover from erroneous agent actions.
- **RBAC & Tenant Isolation**: Strict principal scoping ensuring data and execution isolation across multiple companies.

---

## 8. 3-Temperature Memory Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │          3-TEMPERATURE MEMORY STORE          │
                  └──────────────────────┬───────────────────────┘
                                         │
       ┌─────────────────────────────────┼─────────────────────────────────┐
       ▼                                 ▼                                 ▼
┌──────────────┐                  ┌──────────────┐                  ┌──────────────┐
│  HOT TIER    │                  │  WARM TIER   │                  │  COLD TIER   │
│ Redis 7      │ ──Compaction──►  │ Postgres 16  │ ──Archive────►   │ Cold Storage │
│ Hot working  │ ──Promotion──►   │ Persistent   │ ──Reflection─►   │ Historical   │
│ memory       │                  │ memory       │                  │ archives     │
└──────────────┘                  └──────────────┘                  └──────────────┘
```

- **Hot Memory (Redis)**: Low-latency working memory for active conversation context and execution state.
- **Warm Memory (PostgreSQL)**: Structured persistent memory with semantic embeddings and deduplication.
- **Cold Memory (Archive)**: Compressed historical archive for long-term reflection and historical query retrieval.
- **Memory Operations**: Autonomous memory extraction, reflection, promotion, and token-constrained compaction.

---

## 9. Workflow & Pipeline Automation

### CI/CD Execution Graphs
- **Visual Workflow Builder**: Create and edit multi-step execution graphs connecting triggers, agents, tools, and scripts.
- **Pipeline Runs**: Track pipeline execution history, log outputs, step durations, and status codes.
- **Context & Webhook Triggers**: Execute workflows automatically based on incoming webhooks, scheduled crons, or system events.

---

## 10. Enterprise Integrations & Security

### Third-Party Integrations
- **Slack Integration**: Webhook event processing and Slack bot notifications.
- **Telegram Bot**: Interact with agents and receive emergency alerts via Telegram.
- **GitHub Integration**: Repository mapping, pull request analysis, and automated code review.

### Enterprise Security & Identity
- **SCIM 2.0 Provisioning**: Automated user and team lifecycle management.
- **SSO (Single Sign-On)**: SAML 2.0 and OAuth2 enterprise identity integration.
- **Secret Store**: Encrypted secret storage for API keys and database credentials.
