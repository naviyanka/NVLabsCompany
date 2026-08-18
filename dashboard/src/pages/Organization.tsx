import { OrgChart, type OrgNode } from '@/components/org/OrgChart';
import { DepartmentCard } from '@/components/org/DepartmentCard';
import { Card } from '@/components/common/Card';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import type { Agent } from '@/types/agent';
import type { PaginatedResponse } from '@/types/common';
import { Spinner } from '@/components/common/Spinner';

const COMPANY_ID = 'default';

export function Organization() {
  const { data, loading, error } = useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const agents = data?.items ?? [];

  // Build a simple org tree from agent data
  const departments = Array.from(new Set(agents.map((a) => a.department_id).filter(Boolean)));

  const orgTree: OrgNode[] = [
    {
      id: 'ceo',
      name: 'AI Company',
      title: 'Organization Root',
      type: 'ceo',
      agentCount: agents.length,
      taskCount: 0,
      children: departments.map((deptId) => {
        const deptAgents = agents.filter((a) => a.department_id === deptId);
        return {
          id: deptId as string,
          name: `Department ${(deptId as string).slice(0, 8)}`,
          title: 'Department',
          type: 'department' as const,
          agentCount: deptAgents.length,
          taskCount: 0,
          children: deptAgents.map((a) => ({
            id: a.id,
            name: a.name,
            title: a.title,
            type: 'agent' as const,
          })),
        };
      }),
    },
  ];

  if (loading) {
    return <Spinner size="lg" className="py-12" />;
  }

  if (error) {
    return (
      <div className="text-center py-12 text-rose-600">
        <p className="font-medium">Failed to load organization</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Organization</h1>
        <p className="text-sm text-gray-500 mt-1">Company hierarchy and departments</p>
      </div>

      <Card>
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Organization Chart</h3>
        <OrgChart data={orgTree} />
      </Card>

      {departments.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Departments</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {departments.map((deptId) => {
              const deptAgents = agents.filter((a) => a.department_id === deptId);
              return (
                <DepartmentCard
                  key={deptId}
                  name={`Department ${(deptId as string).slice(0, 8)}`}
                  agentCount={deptAgents.length}
                  activeTaskCount={0}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
