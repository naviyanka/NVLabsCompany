import { useState, useEffect } from 'react';
import {
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Lock,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { EmptyState } from '@/components/common/EmptyState';
import { apiClient } from '@/api/client';

interface GovernanceApproval {
  id: string;
  title: string;
  agent_id: string;
  risk_level: 'critical' | 'high' | 'medium' | 'low';
  category: 'tool_execution' | 'budget_override' | 'prod_deploy';
  status: 'pending' | 'approved' | 'rejected';
  payload_summary: string;
  created_at: string;
}

const defaultApprovalsMock: GovernanceApproval[] = [
  {
    id: 'appr-1',
    title: 'AWS Production Kubernetes Cluster Scaling (Autoscaling Min 8 -> 16 Nodes)',
    agent_id: 'agent-bolt',
    risk_level: 'critical',
    category: 'prod_deploy',
    status: 'pending',
    payload_summary: 'Requested by Bolt-03 to handle incoming LLM inference traffic spike. Est. monthly delta: +$1,200.',
    created_at: new Date(Date.now() - 15 * 60000).toISOString(),
  },
  {
    id: 'appr-2',
    title: 'Monthly LLM Token Budget Override Request ($400 -> $750)',
    agent_id: 'agent-sage',
    risk_level: 'high',
    category: 'budget_override',
    status: 'pending',
    payload_summary: 'Requested by Sage-05 for fine-tuning prompt distillation matrix on 10,000 synthetic test benchmarks.',
    created_at: new Date(Date.now() - 45 * 60000).toISOString(),
  },
  {
    id: 'appr-3',
    title: 'Execute Database Schema Migration: Add Vector Column to memory_nodes',
    agent_id: 'agent-nova',
    risk_level: 'medium',
    category: 'tool_execution',
    status: 'approved',
    payload_summary: 'ALTER TABLE memory_nodes ADD COLUMN embedding vector(1536); Non-blocking migration script.',
    created_at: new Date(Date.now() - 3600000 * 3).toISOString(),
  },
  {
    id: 'appr-4',
    title: 'Grant Direct Shell Exec Privileges in Sandboxed Container',
    agent_id: 'agent-shield',
    risk_level: 'high',
    category: 'tool_execution',
    status: 'rejected',
    payload_summary: 'Rejected due to policy violation: direct interactive root shell execution is disabled in non-isolated containers.',
    created_at: new Date(Date.now() - 3600000 * 12).toISOString(),
  },
];

export function Approvals() {
  const [approvals, setApprovals] = useState<GovernanceApproval[]>(defaultApprovalsMock);

  useEffect(() => {
    let isMounted = true;
    async function loadApprovals() {
      try {
        const res = await apiClient.get<{ items: GovernanceApproval[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/approvals'
        );
        if (isMounted && res?.items && res.items.length > 0) {
          setApprovals(res.items);
        }
      } catch (err) {
        // Silently use defaults
      }
    }
    loadApprovals();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleDecision = async (id: string, decision: 'approved' | 'rejected') => {
    try {
      const res = await apiClient.patch<{ message: string; approval: GovernanceApproval }>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/approvals/${id}`,
        { status: decision }
      );
      if (res?.approval) {
        setApprovals((prev) => prev.map((a) => (a.id === id ? res.approval : a)));
      }
    } catch (err) {
      console.error('Failed to record approval decision', err);
    }
  };

  const pendingCount = approvals.filter((a) => a.status === 'pending').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Governance & Action Approval Gate
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Human-in-the-loop authorization for elevated permissions, high-cost operations, and shell execution
          </p>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Pending Gate Requests"
          value={`${pendingCount} Requests`}
          subValue="Requires Operator Action"
          change={pendingCount > 0 ? 'Action required' : 'All clear'}
          changeType={pendingCount > 0 ? 'negative' : 'positive'}
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <StatCard
          label="Auto-Approved Operations"
          value="1,482"
          subValue="Low-risk executions"
          change="99.4% policy compliance"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <StatCard
          label="Security Guardrails"
          value="Enforced"
          subValue="Zero-Trust IAM"
          change="Hard isolation"
          changeType="positive"
          icon={<Lock className="w-4 h-4" />}
        />
      </div>

      {/* Approvals List */}
      <div className="space-y-3">
        {approvals.length === 0 ? (
          <EmptyState
            title="No approvals pending"
            description="All autonomous agent operations are currently within authorized risk thresholds."
            icon={<CheckCircle2 size={24} />}
          />
        ) : (
          approvals.map((req) => (
            <Card key={req.id}>
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <h3 className="text-xs font-medium text-[#F2F1EE]">{req.title}</h3>
                    <Badge variant={req.risk_level === 'critical' ? 'failed' : 'in_progress'}>
                      {req.risk_level} risk
                    </Badge>
                    <Badge variant={req.status === 'approved' ? 'completed' : req.status === 'rejected' ? 'failed' : 'idle'}>
                      {req.status}
                    </Badge>
                  </div>

                  <div className="text-[11px] font-mono text-[#6B6B6E]">
                    Requesting Agent: <span className="text-[#FFB020]">{req.agent_id}</span> · Category:{' '}
                    <span className="uppercase text-[#A8A8AB]">{req.category}</span>
                  </div>

                  <div className="p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs font-mono text-[#F2F1EE] leading-relaxed">
                    {req.payload_summary}
                  </div>
                </div>

                {req.status === 'pending' ? (
                  <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
                    <Button
                      variant="secondary"
                      size="xs"
                      icon={<XCircle size={13} className="text-[#EF4444]" />}
                      onClick={() => handleDecision(req.id, 'rejected')}
                    >
                      Deny
                    </Button>
                    <Button
                      variant="primary"
                      size="xs"
                      icon={<CheckCircle2 size={13} />}
                      onClick={() => handleDecision(req.id, 'approved')}
                    >
                      Authorize
                    </Button>
                  </div>
                ) : (
                  <div className="text-xs font-mono text-[#6B6B6E] shrink-0">
                    Decision recorded
                  </div>
                )}
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
