import { useState, useEffect } from 'react';
import {
  Users,
  Clock,
  Plus,
  CheckCircle2,
  FileText,
  Radio,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { apiClient } from '@/api/client';

interface MeetingSync {
  id: string;
  title: string;
  type: string;
  status: 'scheduled' | 'in_progress' | 'completed';
  scheduled_at: string;
  attendees: string[];
  summary?: string;
  action_items?: string[];
  transcript?: { speaker: string; text: string }[];
}

export function Meetings() {
  const [meetings, setMeetings] = useState<MeetingSync[]>([]);
  const [selectedMeeting, setSelectedMeeting] = useState<MeetingSync | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState('Standup');

  useEffect(() => {
    async function loadMeetings() {
      try {
        const res = await apiClient.get<{ items: MeetingSync[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/meetings'
        );
        if (res?.items) setMeetings(res.items);
      } catch (err) {
        console.error('Failed to load meetings', err);
      }
    }
    loadMeetings();
  }, []);

  const handleConvene = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const created = await apiClient.post<MeetingSync>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/meetings',
        {
          title: newTitle,
          type: newType,
          status: 'completed',
          attendees: ['Atlas-01', 'Nova-02', 'Sage-05', 'Shield-07'],
          summary: 'Squad aligned on API latency reduction target and merged PR #402.',
          action_items: [
            'Nova-02 to deploy cache warm-up cron',
            'Shield-07 to audit IAM token TTL',
          ],
          transcript: [
            { speaker: 'Atlas-01', text: 'Good morning squad. Today our focus is sub-50ms query response.' },
            { speaker: 'Nova-02', text: 'Redis indexing is finished. Benchmarking shows 32ms p99.' },
            { speaker: 'Shield-07', text: 'Security checks passed with zero vulnerabilities.' },
          ],
        }
      );
      setMeetings((prev) => [created, ...prev]);
      setShowCreateModal(false);
      setNewTitle('');
    } catch (err) {
      console.error('Failed to convene sync', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Radio className="w-5 h-5 text-[#FFB020] animate-pulse" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Autonomous Squad Syncs & Huddles
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Agent-to-agent coordination transcripts, consensus deliberations, and action items
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowCreateModal(true)}
        >
          Convene Huddle
        </Button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Total Sync Sessions"
          value={meetings.length}
          subValue="Consensus Huddles"
          change="Automated recording"
          changeType="neutral"
          icon={<Users className="w-4 h-4" />}
        />
        <StatCard
          label="Synthesized Action Items"
          value="18 Logged"
          subValue="Cross-Agent Tasks"
          change="100% automated extraction"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <StatCard
          label="Deliberation SLA"
          value="12s"
          subValue="Avg Consensus Time"
          change="Instantaneous alignment"
          changeType="positive"
          icon={<Clock className="w-4 h-4" />}
        />
      </div>

      {/* Meetings List */}
      <div className="space-y-3">
        {meetings.map((m) => (
          <Card
            key={m.id}
            className="hover:border-white/[0.2] transition-colors cursor-pointer"
            onClick={() => setSelectedMeeting(m)}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2.5">
                  <h3 className="text-sm font-medium text-[#F2F1EE]">{m.title}</h3>
                  <Badge variant={m.status === 'completed' ? 'completed' : 'in_progress'}>
                    {m.status}
                  </Badge>
                </div>
                <div className="text-xs font-mono text-[#6B6B6E]">
                  Type: <span className="text-[#A8A8AB]">{m.type}</span> · Attendees:{' '}
                  <span className="text-[#FFB020]">{m.attendees?.join(', ') || 'All Squads'}</span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-xs font-mono text-[#6B6B6E]">
                  {new Date(m.scheduled_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
                <Button variant="secondary" size="xs" icon={<FileText size={12} />}>
                  Inspect Transcript
                </Button>
              </div>
            </div>

            {m.summary && (
              <p className="text-xs text-[#9C9C9F] mt-3 font-sans pt-2 border-t border-white/[0.04] leading-relaxed">
                {m.summary}
              </p>
            )}
          </Card>
        ))}
      </div>

      {/* Transcript Drawer */}
      <Drawer
        isOpen={!!selectedMeeting}
        onClose={() => setSelectedMeeting(null)}
        title={selectedMeeting?.title || 'Meeting Details'}
        subtitle={`Session #${selectedMeeting?.id} · Type: ${selectedMeeting?.type}`}
      >
        {selectedMeeting && (
          <div className="space-y-5">
            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                Executive Synthesis
              </label>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE] leading-relaxed">
                {selectedMeeting.summary || 'Consensus reached on task allocation.'}
              </div>
            </div>

            {selectedMeeting.action_items && (
              <div>
                <label className="text-[10px] font-mono text-[#22C55E] uppercase block mb-1">
                  Synthesized Action Deliverables
                </label>
                <div className="space-y-1.5">
                  {selectedMeeting.action_items.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs font-mono text-[#22C55E] flex items-center gap-2"
                    >
                      <CheckCircle2 size={13} className="shrink-0" />
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                Deliberation Transcript
              </label>
              <div className="space-y-2 p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] max-h-72 overflow-y-auto">
                {(selectedMeeting.transcript || [
                  { speaker: 'Atlas-01', text: 'All operational parameters verified.' },
                ]).map((t, i) => (
                  <div key={i} className="text-xs font-mono space-y-0.5">
                    <span className="text-[#FFB020] font-medium">{t.speaker}:</span>
                    <p className="text-[#F2F1EE] font-sans pl-2 border-l border-white/[0.08]">{t.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      {/* Convene Modal */}
      <Modal isOpen={showCreateModal} onClose={() => setShowCreateModal(false)} title="Convene Squad Sync">
        <form onSubmit={handleConvene} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Sync Title / Subject
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="e.g. Architecture Alignment & Latency Target"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Sync Category
            </label>
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Standup">Daily Operations Standup</option>
              <option value="Architecture Review">Architecture Review</option>
              <option value="Incident Triage">Incident Triage</option>
              <option value="Retrospective">Retrospective</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowCreateModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Initiate Deliberation
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
