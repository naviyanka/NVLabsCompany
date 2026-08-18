import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Wrench, ExternalLink } from 'lucide-react';

interface Tool {
  id: string;
  name: string;
  category: string;
  status: 'active' | 'inactive';
  description: string;
  usedBy: number;
}

const sampleTools: Tool[] = [
  { id: '1', name: 'GitHub API', category: 'Source Control', status: 'active', description: 'Repository management, PRs, and issues', usedBy: 8 },
  { id: '2', name: 'Jira Integration', category: 'Project Management', status: 'active', description: 'Ticket creation and tracking', usedBy: 5 },
  { id: '3', name: 'Slack Notifications', category: 'Communication', status: 'active', description: 'Send and receive messages', usedBy: 12 },
  { id: '4', name: 'AWS CloudWatch', category: 'Monitoring', status: 'active', description: 'System monitoring and alerting', usedBy: 3 },
  { id: '5', name: 'Database Access', category: 'Data', status: 'active', description: 'Query and update databases', usedBy: 4 },
  { id: '6', name: 'Docker Registry', category: 'DevOps', status: 'inactive', description: 'Container image management', usedBy: 2 },
];

export function Tools() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Tools & Integrations</h1>
        <p className="text-sm text-gray-500 mt-1">External tools and services available to agents</p>
      </div>

      {sampleTools.length === 0 ? (
        <EmptyState
          icon={<Wrench size={48} />}
          title="No tools configured"
          description="Add integrations to extend agent capabilities."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sampleTools.map((tool) => (
            <Card key={tool.id}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 bg-gray-100 text-gray-600 rounded-lg flex items-center justify-center">
                    <Wrench size={16} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">{tool.name}</h3>
                    <Badge variant={tool.status === 'active' ? 'success' : 'default'} size="sm">
                      {tool.status}
                    </Badge>
                  </div>
                </div>
                <ExternalLink size={14} className="text-gray-400" />
              </div>
              <p className="text-xs text-gray-500 mt-2">{tool.description}</p>
              <div className="flex items-center gap-2 mt-3 text-xs text-gray-500">
                <Badge variant="default" size="sm">{tool.category}</Badge>
                <span>{tool.usedBy} agents using</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
