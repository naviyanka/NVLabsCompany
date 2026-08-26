import { RequireAuth } from '@/components/auth/RequireAuth';
import { Layout } from '@/components/layout/Layout';
import { AgentTerminalPanel } from '@/components/terminal/AgentTerminalPanel';
import { AuthProvider } from '@/contexts/AuthContext';
import { AcceptInvite } from '@/pages/AcceptInvite';
import { Activity } from '@/pages/Activity';
import { AgentDetailPage } from '@/pages/AgentDetailPage';
import { Agents } from '@/pages/Agents';
import { Approvals } from '@/pages/Approvals';
import { Budgets } from '@/pages/Budgets';
import { Dashboard } from '@/pages/Dashboard';
import { Evolution } from '@/pages/Evolution';
import { GitRepos } from '@/pages/GitRepos';
import { Goals } from '@/pages/Goals';
import { HRRoom } from '@/pages/HRRoom';
import { KnowledgeBase } from '@/pages/KnowledgeBase';
import { Login } from '@/pages/Login';
import { Meetings } from '@/pages/Meetings';
import { Memory } from '@/pages/Memory';
import { MemoryGraph } from '@/pages/MemoryGraph';
import { Notifications } from '@/pages/Notifications';
import { Organization } from '@/pages/Organization';
import { Pipelines } from '@/pages/Pipelines';
import PlazaFeed from '@/pages/PlazaFeed';
import { Settings } from '@/pages/Settings';
import { Setup } from '@/pages/Setup';
import { Skills } from '@/pages/Skills';
import { Tasks } from '@/pages/Tasks';
import { Tools } from '@/pages/Tools';
import { Workflows } from '@/pages/Workflows';
import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

// Lazy-load Office page to avoid Three.js bundle cost for users who never visit it
const LazyOffice = lazy(() => import('@/pages/Office').then((m) => ({ default: m.Office })));

function OfficeFallback() {
  return (
    <div className="h-[calc(100vh-8rem)] flex items-center justify-center bg-[#0A0A0B]">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-[#FFB020] border-t-transparent rounded-full animate-spin" />
        <span className="text-xs font-mono text-[#6B6B6E]">Booting 3D Office Simulation...</span>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Reachable without a session — these are how you get one. */}
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/invite" element={<AcceptInvite />} />

          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/overview" element={<Dashboard />} />
              <Route path="/office" element={<Suspense fallback={<OfficeFallback />}><LazyOffice /></Suspense>} />
              <Route path="/hr-room" element={<HRRoom />} />
              <Route path="/plaza" element={<PlazaFeed />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/agents/:id" element={<AgentDetailPage />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/pipelines" element={<Pipelines />} />
              <Route path="/organization" element={<Organization />} />
              <Route path="/goals" element={<Goals />} />
              <Route path="/skills" element={<Skills />} />
              <Route path="/tools" element={<Tools />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/memory-graph" element={<MemoryGraph />} />
              <Route path="/git-repos" element={<GitRepos />} />
              <Route path="/knowledge" element={<KnowledgeBase />} />
              <Route path="/knowledge-base" element={<KnowledgeBase />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/budgets" element={<Budgets />} />
              <Route path="/evolution" element={<Evolution />} />
              <Route path="/workflows" element={<Workflows />} />
              <Route path="/nodes" element={<Navigate to="/pipelines" replace />} />
              <Route path="/meetings" element={<Meetings />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/terminal" element={<AgentTerminalPanel />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
