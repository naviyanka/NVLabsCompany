import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from '@/components/layout/Layout';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<div>Dashboard</div>} />
          <Route path="/agents" element={<div>Agents</div>} />
          <Route path="/tasks" element={<div>Tasks</div>} />
          <Route path="/organization" element={<div>Organization</div>} />
          <Route path="/workflows" element={<div>Workflows</div>} />
          <Route path="/approvals" element={<div>Approvals</div>} />
          <Route path="/budgets" element={<div>Budgets</div>} />
          <Route path="/evolution" element={<div>Evolution</div>} />
          <Route path="/activity" element={<div>Activity</div>} />
          <Route path="/settings" element={<div>Settings</div>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
