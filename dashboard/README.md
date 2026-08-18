# NEXUS Dashboard

A React + TypeScript + Vite + Tailwind CSS dashboard for the NEXUS AI Company Operating System. Provides real-time visibility into agents, tasks, budgets, workflows, and organizational evolution.

## Technology Stack

- **React 19** - UI library
- **TypeScript 5.x** - Type safety
- **Vite 6.x** - Build tool and dev server
- **Tailwind CSS 4.x** - Utility-first styling
- **React Router v7** - Client-side routing
- **Recharts** - Charts and data visualization
- **Lucide React** - Icon system

## Getting Started

### Prerequisites

- Node.js 22 or later
- npm 10 or later

### Install Dependencies

```bash
cd dashboard
npm install
```

### Run Development Server

```bash
npm run dev
```

The dev server starts at `http://localhost:5173` with hot module replacement (HMR) enabled.

### Build for Production

```bash
npm run build
```

Output is written to `dist/`. The build produces static files that can be served by any HTTP server.

### Preview Production Build

```bash
npm run preview
```

Serves the production build locally for testing.

## Project Structure

```
dashboard/
├── public/
│   └── favicon.svg
├── src/
│   ├── api/              # API client and endpoint modules
│   ├── components/
│   │   ├── activity/     # Activity feed components
│   │   ├── agents/       # Agent management components
│   │   ├── charts/       # Data visualization (Recharts)
│   │   ├── common/       # Reusable UI primitives
│   │   ├── evolution/    # Self-evolution components
│   │   ├── governance/   # Approvals and budgets
│   │   ├── layout/       # App shell (Sidebar, Header, Layout)
│   │   ├── org/          # Organization chart components
│   │   └── tasks/        # Task management components
│   ├── hooks/            # Custom React hooks
│   ├── pages/            # Route-level page components
│   ├── types/            # TypeScript type definitions
│   ├── utils/            # Utility functions
│   ├── App.tsx           # Root component with routing
│   ├── main.tsx          # Entry point
│   └── index.css         # Global styles and Tailwind imports
├── index.html            # HTML entry point
├── package.json
├── tailwind.config.js
├── postcss.config.js
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
└── README.md
```

## Configuration

### API Base URL

The API base URL defaults to `http://localhost:8000`. It can be configured via environment variable:

```bash
VITE_API_BASE_URL=http://your-api-host:8000 npm run dev
```

### Polling

The dashboard auto-refreshes every 30 seconds. This is configurable in the Settings page.

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Overview with stats, charts, activity |
| `/agents` | Agents | Agent management with grid/list views |
| `/agents/:id` | Agent Detail | Detailed agent view with tabs |
| `/tasks` | Tasks | Task management with list/kanban views |
| `/organization` | Organization | Org chart and departments |
| `/goals` | Goals | Strategic objectives |
| `/skills` | Skills | Skills registry browser |
| `/tools` | Tools | Tool integrations |
| `/memory` | Memory | Knowledge base browser |
| `/approvals` | Approvals | Pending approval requests |
| `/budgets` | Budgets | Budget monitoring |
| `/evolution` | Evolution | Self-improvement proposals |
| `/workflows` | Workflows | Active workflow tracking |
| `/meetings` | Meetings | Meeting management |
| `/activity` | Activity | Full activity log |
| `/settings` | Settings | System configuration |

## Design System

- **Primary:** Indigo (#6366f1)
- **Success:** Emerald (#10b981)
- **Warning:** Amber (#f59e0b)
- **Danger:** Rose (#f43f5e)
- **Sidebar:** Dark (#1e1e2e)
- **Content:** Light gray (#f8fafc)

All spacing follows an 8px grid. Components use Tailwind utility classes for consistent styling.

## Development Notes

- All API calls go through `src/api/client.ts` which handles base URL, error normalization, and JSON parsing.
- Custom hooks (`useApi`, `usePolling`, `useAgents`) provide standardized data fetching with loading/error states.
- TypeScript strict mode is enabled. Avoid `any` types.
- Components use Props interfaces for type safety.
