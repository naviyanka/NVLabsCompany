# MetaGPT - Repository Analysis

## Overview

MetaGPT is a **Python framework** for multi-agent software development simulation. It models a software company with predefined roles (ProductManager, Architect, Engineer, QA) collaborating through Standard Operating Procedures (SOPs). The framework emphasizes structured outputs (PRDs, system designs, code) and role-based specialization with a publish/subscribe message-passing architecture.

---

## 1. Architecture

**Type:** Single Python package  
**Pattern:** Role-based multi-agent with SOP-driven collaboration  
**Primary Language:** Python 3.9-3.11

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `metagpt/roles/` | Predefined role implementations (17 files) |
| `metagpt/actions/` | Role actions (20+ action types) |
| `metagpt/memory/` | Memory subsystem (5 implementations) |
| `metagpt/tools/` | Utility tools (search, TTS, code) |
| `metagpt/environment/` | Agent communication environment |
| `metagpt/strategy/` | Planning and strategy |
| `metagpt/skills/` | Skill definitions (SummarizeSkill, WriterSkill) |
| `metagpt/rag/` | RAG system |
| `metagpt/learn/` | Learning capabilities |
| `metagpt/provider/` | LLM provider abstractions |
| `metagpt/configs/` | Configuration management |
| `metagpt/ext/` | Extensions |
| `metagpt/exp_pool/` | Experience pool |
| `metagpt/document_store/` | Document persistence |
| `config/` | Default configurations |
| `tests/` | Test suite |

### Architectural Patterns
- **Pydantic BaseModel everywhere**: All entities are Pydantic models (serializable, validatable)
- **Publish/Subscribe messaging**: Roles communicate via message publication with tag-based filtering
- **SOP-driven execution**: Predefined sequences of actions per role
- **Action-based execution**: Each role has a set of Actions it can perform
- **Environment abstraction**: Shared communication space for all roles
- **Serialization-first**: Full team state can be saved/restored

---

## 2. Runtime

- **Language:** Python 3.9-3.11
- **Framework:** Pydantic v2 (data modeling)
- **Async:** asyncio (all role execution is async)
- **LLM:** Multiple providers via `metagpt/provider/`
- **Config:** YAML-based configuration (`config/`)
- **Testing:** pytest
- **Linting:** ruff
- **Packaging:** setuptools (`setup.py`)
- **Docker:** Dockerfile provided

---

## 3. Agent System

### Role Base Class (`metagpt/roles/role.py`)
Core abstractions:
- `Role(BaseModel)` - Base agent class
- `RoleReactMode` (enum): REACT, BY_ORDER, PLAN_AND_ACT
- Action subscription: roles subscribe to message types
- Message routing: `publish_message()` sends, `put_message()` receives
- Private message buffer (`rc.msg_buffer`)
- Planner integration for complex reasoning

### Predefined Roles
| Role | Purpose |
|------|---------|
| `ProductManager` | Requirements gathering, PRD generation |
| `Architect` | System design, API design |
| `ProjectManager` | Task decomposition, scheduling |
| `Engineer` | Code implementation |
| `QAEngineer` | Test generation, quality assurance |
| `Researcher` | Information gathering |
| `Searcher` | Web search integration |
| `Teacher` | Knowledge transfer |
| `Assistant` | General assistance |
| `Sales` | Sales-related tasks |
| `CustomerService` | Customer interaction |
| `InvoiceOCRAssistant` | Document processing |
| `TutorialAssistant` | Tutorial generation |

### Role Execution Model
1. `_observe()` - Read incoming messages from environment
2. `_think()` - Decide next action based on state and messages
3. `_act()` - Execute the chosen action
4. `_react()` - Full observe-think-act cycle
5. `_plan_and_act()` - Extended planning before acting

### Team Orchestration (`metagpt/team.py`)
- `Team(BaseModel)` - Collection of roles with shared environment
- Investment/budget tracking
- `hire()` - Add roles to team
- MGX environment (enhanced multi-agent coordination)
- Serializable team state (save/restore)

---

## 4. Skills

### Built-in Skills (`metagpt/skills/`)
- `SummarizeSkill` - Text summarization
- `WriterSkill` - Content generation

### Action-as-Skill Pattern
Actions effectively serve as skills:
- `AnalyzeRequirements` - Requirement analysis
- `DesignAPI` - API design generation
- `DesignAPIReview` - Design review
- `ExecuteTask` - Generic task execution
- `DebugError` - Error diagnosis
- `FixBug` - Bug repair
- `GenerateQuestions` - Question generation
- `ImportRepo` - Repository analysis
- `PrepareDocuments` - Document preparation
- `ExtractReadme` - Documentation extraction

### Data Interpreter (`metagpt/actions/di/`)
- Code generation and execution for data analysis
- Iterative refinement based on execution results
- Structured output generation

---

## 5. Memory

### Memory Implementations (`metagpt/memory/`)
| Implementation | Purpose |
|----------------|---------|
| `Memory` | Base memory - in-memory storage with tag indexing |
| `BrainMemory` | Structured cognitive memory |
| `LongtermMemory` | Persistent long-term storage |
| `RoleZeroMemory` | Specialized for role-zero coordination |
| `MemoryStorage` | Persistence backend abstraction |

### Memory Features
- **Tag-based indexing**: Messages indexed by `cause_by` action type
- **Role filtering**: Retrieve messages by source role
- **Content search**: Find messages containing specific content
- **Batch operations**: Add/remove multiple messages
- **Serialization**: Full memory state save/restore via Pydantic

### Document Store (`metagpt/document_store/`)
- Document persistence for generated artifacts
- Versioned document management

### Experience Pool (`metagpt/exp_pool/`)
- Store and retrieve past execution experiences
- Pattern matching for similar situations

---

## 6. Tools

### Built-in Tools (`metagpt/tools/`)
| Tool | Purpose |
|------|---------|
| `search_engine.py` | Unified search interface |
| `search_engine_bing.py` | Bing search |
| `search_engine_ddg.py` | DuckDuckGo search |
| `search_engine_googleapi.py` | Google search |
| `search_engine_serpapi.py` | SerpAPI |
| `search_engine_serper.py` | Serper.dev |
| `search_engine_meilisearch.py` | Meilisearch |
| `azure_tts.py` | Azure text-to-speech |
| `iflytek_tts.py` | iFlytek TTS |
| `openai_text_to_image.py` | Image generation |
| `openai_text_to_embedding.py` | Text embeddings |
| `metagpt_text_to_image.py` | MetaGPT image service |
| `moderation.py` | Content moderation |
| `prompt_writer.py` | Prompt engineering |
| `tool_convert.py` | Tool format conversion |
| `swe_agent_commands/` | SWE-agent compatible commands |
| `libs/` | Tool utility libraries |

### Tool Integration
- `metagpt_oas3_api_svc.py` - OpenAPI 3.0 service bridge
- `openapi_v3_hello.py` - OpenAPI example server
- Tools are invoked within Actions, not directly by Roles

---

## 7. Orchestration

### SOP-Driven Collaboration
The core orchestration model is Standard Operating Procedures:
1. `ProductManager` produces PRD from requirements
2. `Architect` produces system design from PRD
3. `ProjectManager` decomposes into tasks
4. `Engineer` implements code for each task
5. `QAEngineer` writes and runs tests

### Message Routing
- Publish/Subscribe with tag-based filtering
- Roles subscribe to specific action output types
- Messages include `cause_by` metadata for routing
- `MESSAGE_ROUTE_TO_SELF` for self-directed messages
- Environment handles message distribution

### Planning Strategies (`metagpt/strategy/`)
- `Planner` class for complex reasoning
- Task decomposition
- Priority-based execution ordering

### Software Company Pattern (`metagpt/software_company.py`)
- Pre-configured team with all standard roles
- End-to-end software development pipeline
- Budget management with `NoMoneyException`

---

## 8. Persistence

### Serialization
- All models extend `SerializationMixin`
- Full team state serialization to JSON
- Role state including memory, pending actions
- Configurable serialization path (`SERDESER_PATH`)

### Storage
- File-based JSON persistence
- Document store for generated artifacts
- Memory storage backends
- Experience pool for historical patterns
- Configurable workspace paths

---

## 9. APIs

### Programmatic API
- `Team` class as main entry point
- `Role` creation and configuration
- `Message` passing between components
- `Context` management for shared state
- `Action` definition and execution

### Configuration API
- YAML-based global configuration
- Per-role configuration
- LLM provider configuration
- Tool configuration

### Integration Points
- `startup.py` - Application initialization
- `management/` - Administrative operations
- `provider/` - LLM provider interface

---

## 10. Extension Points

- **Custom Roles**: Extend `Role` base class with custom actions and subscriptions
- **Custom Actions**: Implement `Action` class for new capabilities
- **LLM Providers**: Add providers via `metagpt/provider/` abstraction
- **Tools**: Register new tools in `metagpt/tools/`
- **Memory Types**: Implement custom memory backends
- **Environment Types**: Custom communication environments (`metagpt/environment/`)
  - `MGXEnv` - Enhanced multi-agent coordination
  - Custom environments for domain-specific collaboration
- **Skills**: Add domain skills (currently minimal)
- **RAG**: Pluggable RAG pipeline (`metagpt/rag/`)
- **Extensions** (`metagpt/ext/`): Plugin-like additions

---

## 11. Licensing

- **License:** MIT
- Permissive for commercial use
- No copyleft dependencies in core
- Some optional dependencies may have different licenses

---

## 12. Dependencies

### Core Dependencies
- `pydantic` v2 - Data modeling and validation
- `openai` - Default LLM provider
- `aiohttp` - Async HTTP
- `tenacity` - Retry logic
- `tiktoken` - Token counting
- `mermaid` support - Diagram generation

### Optional Dependencies
- Various LLM provider SDKs
- Search engine APIs
- TTS services
- Image generation
- Vector stores for RAG
- `chromadb` for embeddings

### Development
- `pytest` - Testing
- `ruff` - Linting
- `Dockerfile` - Container build

---

## Summary for NEXUS

**Strengths for NEXUS:**
- Elegant role-based specialization model (maps directly to company departments)
- SOP-driven collaboration (predefined workflows for software development)
- Publish/Subscribe message routing (clean inter-agent communication)
- Predefined roles cover entire software development lifecycle
- Structured output generation (PRDs, designs, code, tests)
- Serializable team state (pause/resume, migration)
- Pydantic-based (type-safe, validatable, serializable)
- Budget/investment tracking at team level

**Weaknesses / Gaps:**
- Limited to software development domain (roles are hardcoded)
- Simple message-based memory (no semantic search, no long-term learning)
- No durable execution (single-process, no recovery from crashes)
- No API server (library-only, programmatic use)
- No visual interface
- No tool access control or governance
- No multi-tenancy or organizational hierarchy
- No agent lifecycle management
- Relatively simple orchestration (SOP sequences, not dynamic graphs)
- Python 3.9-3.11 ceiling may limit features
