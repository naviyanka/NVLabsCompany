import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from '@/components/layout/Layout';
import { Dashboard } from '@/pages/Dashboard';
import { Agents } from '@/pages/Agents';
import { AgentDetailPage } from '@/pages/AgentDetailPage';
import { Tasks } from '@/pages/Tasks';
import { Organization } from '@/pages/Organization';
import { Goals } from '@/pages/Goals';
import { Skills } from '@/pages/Skills';
import { Tools } from '@/pages/Tools';
import { Memory } from '@/pages/Memory';
import { Approvals } from '@/pages/Approvals';
import { Budgets } from '@/pages/Budgets';
import { Evolution } from '@/pages/Evolution';
import { Workflows } from '@/pages/Workflows';
import { Meetings } from '@/pages/Meetings';
import { Activity } from '@/pages/Activity';
import { Settings } from '@/pages/Settings';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/agents/:id" element={<AgentDetailPage />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/organization" element={<Organization />} />
          <Route path="/goals" element={<Goals />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/tools" element={<Tools />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/budgets" element={<Budgets />} />
          <Route path="/evolution" element={<Evolution />} />
          <Route path="/workflows" element={<Workflows />} />
          <Route path="/meetings" element={<Meetings />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
