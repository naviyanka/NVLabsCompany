import { useState, useEffect } from 'react';
import {
  Users,
  Clock,
  Plus,
  CheckCircle2,
  FileText,
  Radio,
  Sparkles,
  ListCheck,
  MessageSquare,
  Search,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Drawer } from '@/components/common/Drawer';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { MeetingSyncItem } from '@/types/meeting';
import { LiveHuddleModal } from '@/components/meetings/LiveHuddleModal';

const INITIAL_MEETINGS: MeetingSyncItem[] = [];

export function Meetings() {
  const [meetings, setMeetings] = useState<MeetingSyncItem[]>(INITIAL_MEETINGS);
  const [agents, setAgents] = useState<{ id: string; name: string; role: string }[]>([]);
  const [selectedMeeting, setSelectedMeeting] = useState<MeetingSyncItem | null>(null);
  const [showHuddleModal, setShowHuddleModal] = useState(false);
  const [viewMode, setViewMode] = useState<'syncs' | 'actions' | 'analytics'>('syncs');
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('all');

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const res = await apiClient.get<MeetingSyncItem[]>(
          `/api/v1/companies/${companyId}/meetings`
        );
        const items = res;
        if (items.length > 0) {
          setMeetings(items);
        }

        const agentsRes = await apiClient.get<any[]>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentItems = agentsRes;
        if (agentItems.length) setAgents(agentItems);
      } catch (err) {
        console.error('Failed to load meetings', err);
      }
    }
    loadData();
  }, []);

  const handleHuddleCompleted = (newMeeting: MeetingSyncItem) => {
    setMeetings((prev) => [newMeeting, ...prev]);
    setSelectedMeeting(newMeeting);
  };

  const filteredMeetings = meetings.filter((m) => {
    if (filterType !== 'all' && m.type.toLowerCase() !== filterType.toLowerCase()) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        m.title.toLowerCase().includes(q) ||
        m.type.toLowerCase().includes(q) ||
        (m.summary || '').toLowerCase().includes(q) ||
        m.attendees.some((a) => a.toLowerCase().includes(q))
      );
    }
    return true;
  });

  // Extract all action items across meetings
  const allActionItems = meetings.flatMap((m) =>
    (m.action_items || []).map((item) => ({
      meetingTitle: m.title,
      meetingId: m.id,
      text: item,
      date: m.scheduled_at,
    }))
  );

  return (
    <div className="space-y-6 font-sans">
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
            Agent-to-agent coordination transcripts, consensus deliberations, and automated action deliverables
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowHuddleModal(true)}
        >
          Convene Live Huddle
        </Button>
      </div>

      {/* Analytics Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Total Sync Sessions</span>
            <Users size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{meetings.length}</div>
          <p className="text-[10px] text-gray-500 mt-1">Consensus Huddles Logged</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Action Deliverables</span>
            <CheckCircle2 size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">{allActionItems.length}</div>
          <p className="text-[10px] text-gray-500 mt-1">Extracted automatically</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Avg Consensus Time</span>
            <Clock size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">12.4s</div>
          <p className="text-[10px] text-gray-500 mt-1">Instantaneous SLA alignment</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Consensus Score</span>
            <Sparkles size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">99.4%</div>
          <p className="text-[10px] text-gray-500 mt-1">Zero unresolvable conflicts</p>
        </div>
      </div>

      {/* View Mode & Filter Control Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search syncs by title, category, attendee..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Category Filters */}
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {['all', 'Architecture Review', 'Daily Operations Standup', 'Incident Triage'].map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterType(cat)}
              className={`px-2 py-1 rounded text-xs font-mono transition-colors cursor-pointer capitalize whitespace-nowrap ${
                filterType.toLowerCase() === cat.toLowerCase()
                  ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                  : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
              }`}
            >
              {cat === 'all' ? 'All Types' : cat}
            </button>
          ))}
        </div>

        {/* View Mode Tabs */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setViewMode('syncs')}
            className={`px-3 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'syncs'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
            }`}
          >
            <MessageSquare size={13} /> Sync Sessions
          </button>
          <button
            onClick={() => setViewMode('actions')}
            className={`px-3 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 ${
              viewMode === 'actions'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
            }`}
          >
            <ListCheck size={13} /> Action Deliverables ({allActionItems.length})
          </button>
        </div>
      </div>

      {/* VIEW 1: SYNC SESSIONS LIST */}
      {viewMode === 'syncs' && (
        <div className="space-y-3">
          {filteredMeetings.map((m) => (
            <Card
              key={m.id}
              className="hover:border-[#FFB020]/40 transition-colors cursor-pointer group"
              onClick={() => setSelectedMeeting(m)}
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2.5">
                    <h3 className="text-sm font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                      {m.title}
                    </h3>
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
      )}

      {/* VIEW 2: ACTION DELIVERABLES MATRIX */}
      {viewMode === 'actions' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-sm font-medium text-white font-mono uppercase">
                Synthesized Action Deliverables Matrix
              </h3>
              <p className="text-xs text-gray-500">
                Action items extracted automatically from agent huddles and consensus deliberations
              </p>
            </div>
            <span className="text-xs font-mono text-emerald-400 font-bold">
              {allActionItems.length} Deliverables Logged
            </span>
          </div>

          <div className="space-y-2 font-mono text-xs">
            {allActionItems.map((item, idx) => (
              <div
                key={idx}
                className="p-3 bg-[#141416] border border-white/[0.06] hover:border-white/[0.2] rounded-[8px] flex items-center justify-between gap-3"
              >
                <div className="flex items-center gap-2.5">
                  <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
                  <div>
                    <div className="text-white font-medium">{item.text}</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">
                      From: <span className="text-gray-300">{item.meetingTitle}</span>
                    </div>
                  </div>
                </div>

                <span className="text-[10px] text-gray-400 shrink-0">
                  {new Date(item.date).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transcript & Deliberation Drawer */}
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

      {/* Live Huddle Modal */}
      <LiveHuddleModal
        isOpen={showHuddleModal}
        onClose={() => setShowHuddleModal(false)}
        onHuddleCompleted={handleHuddleCompleted}
        agents={agents}
      />
    </div>
  );
}
