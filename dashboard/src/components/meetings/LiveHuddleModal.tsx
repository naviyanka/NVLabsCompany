import { useState, useEffect } from 'react';
import { Radio, Play, Loader2 } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { MeetingSyncItem, MeetingTranscriptEntry } from '@/types/meeting';

interface LiveHuddleModalProps {
  isOpen: boolean;
  onClose: () => void;
  onHuddleCompleted: (meeting: MeetingSyncItem) => void;
  agents: { id: string; name: string; role: string }[];
}

const SAMPLE_SCRIPTS: Record<string, MeetingTranscriptEntry[]> = {
  'Architecture Review': [
    { speaker: 'Atlas-01', role: 'Staff Architect', text: 'Squad, we are evaluating moving the agent memory cache from in-memory arrays to persistent pgvector.' },
    { speaker: 'Nova-02', role: 'Principal AI Researcher', text: 'Vector search latencies remain sub-20ms at 50,000 nodes. Benchmarks show 99.4% recall.' },
    { speaker: 'Sentinel-07', role: 'Lead Security Automation', text: 'Prepared SQL statement bindings prevent any vector payload injection. Approved.' },
    { speaker: 'Bolt-03', role: 'Senior Systems Engineer', text: 'Compacting the index runs in background without blocking the main event loop.' },
  ],
  'Daily Operations Standup': [
    { speaker: 'Atlas-01', role: 'Chief Executive Officer', text: 'Good morning autonomous team. Status update on the new workforce capability envelope.' },
    { speaker: 'Kiro-06', role: 'Frontend Engineer', text: 'Interactive 3D office floorplan rendering at 60fps with real-time agent status avatars.' },
    { speaker: 'Sage-05', role: 'AI Reasoning Engineer', text: 'Prompt optimization pipeline completed 140 mutation rounds with +4.2% accuracy gain.' },
  ],
  'Incident Triage': [
    { speaker: 'Sentinel-07', role: 'Lead Security Automation', text: 'Alert: Rate limiter triggered 12 consecutive 429 status codes on public webhook endpoint.' },
    { speaker: 'Bolt-03', role: 'Senior Systems Engineer', text: 'Isolated offending IP subnets and adjusted Redis sliding window token bucket.' },
    { speaker: 'Atlas-01', role: 'Staff Architect', text: 'Incident resolved. SLA restored within 45 seconds.' },
  ],
};

export function LiveHuddleModal({
  isOpen,
  onClose,
  onHuddleCompleted,
}: LiveHuddleModalProps) {
  const [title, setTitle] = useState('');
  const [type, setType] = useState('Architecture Review');
  const [isSimulating, setIsSimulating] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState<MeetingTranscriptEntry[]>([]);
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (isOpen) {
      setTitle(`${type}: Squad Consensus Huddle`);
    }
  }, [type, isOpen]);

  if (!isOpen) return null;

  const handleStartHuddle = () => {
    setIsSimulating(true);
    setLiveTranscript([]);
    setStepIndex(0);

    const script: MeetingTranscriptEntry[] = SAMPLE_SCRIPTS[type] || [
      { speaker: 'Atlas-01', role: 'Staff Architect', text: 'Initiating autonomous consensus huddle.' },
    ];

    let idx = 0;
    const interval = setInterval(() => {
      if (idx < script.length) {
        const entry = script[idx];
        if (entry) setLiveTranscript((prev) => [...prev, entry]);
        idx++;
        setStepIndex(idx);
      } else {
        clearInterval(interval);
        setTimeout(() => {
          finishHuddle(script);
        }, 800);
      }
    }, 1200);
  };

  const finishHuddle = async (script: MeetingTranscriptEntry[]) => {
    const attendees = Array.from(new Set(script.map((s) => s.speaker)));
    const createdMeeting: MeetingSyncItem = {
      id: `meet-${Date.now().toString(36)}`,
      title: title.trim() || `${type} Huddle`,
      type,
      status: 'completed',
      scheduled_at: new Date().toISOString(),
      duration_minutes: 15,
      attendees,
      summary: `Autonomous squad convened on ${type.toLowerCase()}. Consensus achieved with ${attendees.length} active agents.`,
      action_items: [
        `${attendees[0] || 'Atlas-01'} to publish architecture Decision Record (ADR)`,
        `${attendees[1] || 'Nova-02'} to execute benchmark suite verification`,
      ],
      transcript: script,
      consensus_score: 99,
      created_at: new Date().toISOString(),
    };

    try {
      await apiClient.post(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/meetings',
        createdMeeting
      );
    } catch {
      // Ignore if offline
    }

    onHuddleCompleted(createdMeeting);
    setIsSimulating(false);
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Convene Live Autonomous Agent Huddle">
      <div className="space-y-4 font-sans text-xs">
        {!isSimulating ? (
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                Huddle Subject / Agenda *
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Architecture Alignment & Latency Reduction Target"
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
            </div>

            <div>
              <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                Deliberation Type
              </label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
              >
                <option value="Architecture Review">Architecture Review</option>
                <option value="Daily Operations Standup">Daily Operations Standup</option>
                <option value="Incident Triage">Incident Triage</option>
              </select>
            </div>

            <div className="p-3 bg-[#101012] border border-white/[0.08] rounded space-y-1 font-mono text-[11px]">
              <span className="text-gray-400 uppercase text-[10px]">Participating Squad Agents:</span>
              <div className="flex flex-wrap gap-1.5 pt-1">
                {['Atlas-01', 'Nova-02', 'Sentinel-07', 'Bolt-03', 'Sage-05', 'Kiro-06'].map((name) => (
                  <span key={name} className="px-2 py-0.5 rounded bg-white/[0.04] border border-white/[0.08] text-[#FFB020]">
                    {name}
                  </span>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-white/[0.08]">
              <Button variant="secondary" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Play size={14} />}
                onClick={handleStartHuddle}
              >
                Start Live Deliberation
              </Button>
            </div>
          </div>
        ) : (
          /* LIVE SIMULATION FEED */
          <div className="space-y-4 font-mono">
            <div className="p-3 bg-[#101012] border border-[#FFB020]/40 rounded flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Radio className="w-4 h-4 text-[#FFB020] animate-pulse" />
                <span className="text-white font-bold text-xs">{title}</span>
              </div>
              <span className="text-[10px] text-cyan-400 flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" /> Live Deliberation Active
              </span>
            </div>

            {/* Transcript Stream */}
            <div className="p-3 bg-[#0C0C0E] border border-white/[0.08] rounded max-h-64 overflow-y-auto space-y-3">
              {liveTranscript.map((entry, idx) => (
                <div key={idx} className="space-y-0.5 animate-in fade-in-50 duration-200">
                  <div className="flex items-center gap-2">
                    <span className="text-[#FFB020] font-bold">{entry.speaker}</span>
                    <span className="text-[10px] text-gray-500">({entry.role})</span>
                  </div>
                  <p className="text-gray-200 font-sans pl-2.5 border-l-2 border-[#FFB020]/60 leading-relaxed text-xs">
                    {entry.text}
                  </p>
                </div>
              ))}
            </div>

            <div className="text-[11px] text-gray-400 text-center">
              Agent consensus calculation in progress... ({stepIndex} exchanges)
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
