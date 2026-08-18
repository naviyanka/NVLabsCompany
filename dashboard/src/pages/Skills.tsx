import { useState } from 'react';
import { Card } from '@/components/common/Card';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { Zap, Search } from 'lucide-react';

interface Skill {
  id: string;
  name: string;
  category: string;
  agentCount: number;
  description: string;
}

const sampleSkills: Skill[] = [
  { id: '1', name: 'Code Review', category: 'Engineering', agentCount: 5, description: 'Analyze code for quality, security, and best practices' },
  { id: '2', name: 'Architecture Design', category: 'Engineering', agentCount: 2, description: 'Design system architecture and technical solutions' },
  { id: '3', name: 'Testing', category: 'QA', agentCount: 3, description: 'Write and execute automated tests' },
  { id: '4', name: 'Documentation', category: 'Technical Writing', agentCount: 4, description: 'Create and maintain technical documentation' },
  { id: '5', name: 'Data Analysis', category: 'Analytics', agentCount: 2, description: 'Analyze data patterns and generate insights' },
  { id: '6', name: 'Project Management', category: 'Management', agentCount: 1, description: 'Coordinate tasks, timelines, and resources' },
];

export function Skills() {
  const [search, setSearch] = useState('');

  const filteredSkills = sampleSkills.filter(
    (s) => s.name.toLowerCase().includes(search.toLowerCase()) || s.category.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Skills Registry</h1>
        <p className="text-sm text-gray-500 mt-1">Browse available capabilities across the organization</p>
      </div>

      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Search skills..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>

      {filteredSkills.length === 0 ? (
        <EmptyState
          icon={<Zap size={48} />}
          title="No skills found"
          description="No skills match your search."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredSkills.map((skill) => (
            <Card key={skill.id}>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-primary-100 text-primary-600 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Zap size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-gray-900">{skill.name}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{skill.description}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <Badge variant="default" size="sm">{skill.category}</Badge>
                    <span className="text-xs text-gray-500">{skill.agentCount} agents</span>
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
