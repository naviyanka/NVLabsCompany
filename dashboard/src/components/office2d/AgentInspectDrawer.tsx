import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Agent2D } from './types';
import { Drawer } from '@/components/common/Drawer';
import { Badge } from '@/components/common/Badge';
import { retroAudio } from '@/utils/retroAudio';
import {
  Cpu,
  Coffee,
  Video,
  Play,
  ExternalLink,
  MessageSquare,
  Compass,
  Users,
} from 'lucide-react';

interface AgentInspectDrawerProps {
  agent: Agent2D | null;
  allAgents?: Agent2D[];
  onClose: () => void;
  onSendToDesk: (agentId: string) => void;
  onSendToBreakroom: (agentId: string) => void;
  onSendToMeeting: (agentId: string) => void;
  onSendToRoam: (agentId: string) => void;
  onVisitColleague?: (agentId: string, colleagueId: string) => void;
  onAssignTask: (agentId: string, taskTitle: string) => void;
}

export function AgentInspectDrawer({
  agent,
  allAgents = [],
  onClose,
  onSendToDesk,
  onSendToBreakroom,
  onSendToMeeting,
  onSendToRoam,
  onVisitColleague,
  onAssignTask,
}: AgentInspectDrawerProps) {
  const navigate = useNavigate();
  const [newTaskInput, setNewTaskInput] = useState('');
  const [selectedColleagueId, setSelectedColleagueId] = useState('');
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState<{ sender: string; text: string }[]>([]);

  if (!agent) return null;

  const handleAssign = () => {
    if (!newTaskInput.trim()) return;
    onAssignTask(agent.id, newTaskInput.trim());
    setNewTaskInput('');
    retroAudio.playChime();
  };

  const handlePairWithColleague = () => {
    if (!selectedColleagueId || !onVisitColleague) return;
    onVisitColleague(agent.id, selectedColleagueId);
    retroAudio.playFootstep();
    setSelectedColleagueId('');
  };

  const handleSendMessage = () => {
    if (!chatMessage.trim()) return;
    retroAudio.playChime();
    const userMsg = chatMessage.trim();
    setChatHistory((prev) => [...prev, { sender: 'You', text: userMsg }]);
    setChatMessage('');

    setTimeout(() => {
      setChatHistory((prev) => [
        ...prev,
        {
          sender: agent.name,
          text: `Acknowledged: "${userMsg}". Optimizing subroutines and proceeding with execution.`,
        },
      ]);
    }, 600);
  };

  return (
    <Drawer
      isOpen={!!agent}
      onClose={onClose}
      title={
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-white/[0.06] border border-white/[0.1] flex items-center justify-center text-lg">
            {agent.sprite.accessory === 'labcoat'
              ? '🔬'
              : agent.sprite.accessory === 'armor'
              ? '🛡️'
              : agent.sprite.accessory === 'headphones'
              ? '🎧'
              : '⚡'}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-white font-mono">{agent.name}</span>
              <Badge
                variant={
                  agent.status === 'working'
                    ? 'success'
                    : agent.status === 'review'
                    ? 'amber'
                    : agent.status === 'idle'
                    ? 'warning'
                    : 'neutral'
                }
              >
                {agent.status}
              </Badge>
            </div>
            <span className="text-xs text-[#9C9C9F]">{agent.role}</span>
          </div>
        </div>
      }
      size="md"
    >
      <div className="space-y-5">
        {/* 2D State & Location Card */}
        <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#6B6B6E] font-mono">FLOOR STATUS</span>
            <span className="text-[#FFB020] font-mono font-bold capitalize">
              {agent.state2D.replace(/_/g, ' ')}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#6B6B6E] font-mono">MODEL BACKEND</span>
            <span className="text-white font-mono">{agent.model}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#6B6B6E] font-mono">ENERGY LEVEL</span>
            <div className="flex items-center gap-2">
              <div className="w-24 h-2 rounded-full bg-white/[0.08] overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-[#10B981] to-[#34D399]"
                  style={{ width: `${agent.energy}%` }}
                />
              </div>
              <span className="text-[#10B981] font-mono font-bold">{agent.energy}%</span>
            </div>
          </div>
        </div>

        {/* Current Task & Progress */}
        <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-[#38BDF8] font-bold">CURRENT ACTIVE TASK</span>
            <span className="text-xs font-mono text-white">{Math.round(agent.taskProgress)}%</span>
          </div>
          <p className="text-xs text-[#E2E8F0] font-medium leading-relaxed">
            {agent.currentTask || 'No active task assigned. Currently roaming the office.'}
          </p>

          <div className="w-full h-2 rounded-full bg-white/[0.08] overflow-hidden">
            <div
              className="h-full bg-[#38BDF8] transition-all duration-300"
              style={{ width: `${agent.taskProgress}%` }}
            />
          </div>

          {/* Quick Task Assign Input */}
          <div className="pt-1 flex gap-2">
            <input
              type="text"
              value={newTaskInput}
              onChange={(e) => setNewTaskInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAssign()}
              placeholder="Assign new task to agent..."
              className="flex-1 bg-black/50 border border-white/[0.12] rounded-lg px-3 py-1.5 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
            <button
              onClick={handleAssign}
              className="px-3 py-1.5 rounded-lg bg-[#FFB020] text-black text-xs font-mono font-bold hover:bg-[#FFC043] transition-colors flex items-center gap-1"
            >
              <Play className="w-3 h-3 fill-current" />
              Dispatch
            </button>
          </div>
        </div>

        {/* Quick Floor Dispatch Actions */}
        <div className="space-y-2">
          <span className="text-xs font-mono text-[#6B6B6E] uppercase tracking-wider block">
            FLOOR DISPATCH COMMANDS
          </span>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => onSendToDesk(agent.id)}
              className="p-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] hover:border-[#FFB020]/40 text-left text-xs text-[#E2E8F0] flex items-center gap-2 hover:bg-white/[0.08] transition-all"
            >
              <Cpu className="w-4 h-4 text-[#FFB020]" />
              <div>
                <span className="font-bold block">Send to Desk</span>
                <span className="text-[10px] text-[#6B6B6E]">Resume typing</span>
              </div>
            </button>

            <button
              onClick={() => onSendToBreakroom(agent.id)}
              className="p-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] hover:border-[#F59E0B]/40 text-left text-xs text-[#E2E8F0] flex items-center gap-2 hover:bg-white/[0.08] transition-all"
            >
              <Coffee className="w-4 h-4 text-[#F59E0B]" />
              <div>
                <span className="font-bold block">Coffee Break</span>
                <span className="text-[10px] text-[#6B6B6E]">Lounge / Arcade</span>
              </div>
            </button>

            <button
              onClick={() => onSendToMeeting(agent.id)}
              className="p-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] hover:border-[#A855F7]/40 text-left text-xs text-[#E2E8F0] flex items-center gap-2 hover:bg-white/[0.08] transition-all"
            >
              <Video className="w-4 h-4 text-[#A855F7]" />
              <div>
                <span className="font-bold block">War Room Sync</span>
                <span className="text-[10px] text-[#6B6B6E]">Join meeting</span>
              </div>
            </button>

            <button
              onClick={() => onSendToRoam(agent.id)}
              className="p-2.5 rounded-lg bg-white/[0.04] border border-white/[0.08] hover:border-[#38BDF8]/40 text-left text-xs text-[#E2E8F0] flex items-center gap-2 hover:bg-white/[0.08] transition-all"
            >
              <Compass className="w-4 h-4 text-[#38BDF8]" />
              <div>
                <span className="font-bold block">Free Roam</span>
                <span className="text-[10px] text-[#6B6B6E]">Wander office</span>
              </div>
            </button>
          </div>

          {/* Desk-to-Desk Pair Navigation via A* */}
          {onVisitColleague && allAgents.filter((a) => a.id !== agent.id).length > 0 && (
            <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.06] flex items-center gap-2 mt-2">
              <Users className="w-4 h-4 text-[#10B981] shrink-0" />
              <select
                value={selectedColleagueId}
                onChange={(e) => setSelectedColleagueId(e.target.value)}
                className="flex-1 bg-black/60 border border-white/[0.12] rounded-md px-2 py-1 text-xs text-white focus:outline-none focus:border-[#10B981]"
              >
                <option value="">Pair at Colleague Desk (A* Path)...</option>
                {allAgents
                  .filter((a) => a.id !== agent.id)
                  .map((other) => (
                    <option key={other.id} value={other.id}>
                      {other.name} ({other.deskId}) - {other.role}
                    </option>
                  ))}
              </select>
              <button
                disabled={!selectedColleagueId}
                onClick={handlePairWithColleague}
                className="px-2.5 py-1 rounded-md bg-[#10B981] hover:bg-[#059669] disabled:opacity-40 disabled:cursor-not-allowed text-black font-mono font-bold text-xs transition-colors shrink-0"
              >
                Navigate
              </button>
            </div>
          )}
        </div>

        {/* Telemetry Metrics */}
        <div className="grid grid-cols-3 gap-2">
          <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] text-center">
            <span className="text-[10px] font-mono text-[#6B6B6E] block">CPU UTIL</span>
            <span className="text-sm font-mono font-bold text-white">{agent.cpu}%</span>
          </div>
          <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] text-center">
            <span className="text-[10px] font-mono text-[#6B6B6E] block">MEMORY</span>
            <span className="text-sm font-mono font-bold text-white">{agent.memory}%</span>
          </div>
          <div className="p-3 rounded-lg bg-black/40 border border-white/[0.06] text-center">
            <span className="text-[10px] font-mono text-[#6B6B6E] block">TOKENS</span>
            <span className="text-sm font-mono font-bold text-[#FFB020]">
              {(agent.tokensUsed / 1000).toFixed(0)}k
            </span>
          </div>
        </div>

        {/* Real-Time Agent Direct Chat */}
        <div className="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2.5">
          <div className="flex items-center gap-2 text-xs font-mono text-[#38BDF8]">
            <MessageSquare className="w-3.5 h-3.5" />
            <span>DIRECT AGENT CHANNEL</span>
          </div>

          {chatHistory.length > 0 && (
            <div className="max-h-28 overflow-y-auto space-y-1.5 p-2 rounded bg-black/40 text-xs">
              {chatHistory.map((c, i) => (
                <div key={i} className="text-xs">
                  <span
                    className={`font-mono font-bold ${
                      c.sender === 'You' ? 'text-[#FFB020]' : 'text-[#38BDF8]'
                    }`}
                  >
                    {c.sender}:
                  </span>{' '}
                  <span className="text-[#D1D5DB]">{c.text}</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <input
              type="text"
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              placeholder={`Send instruction to ${agent.name}...`}
              className="flex-1 bg-black/50 border border-white/[0.12] rounded-lg px-3 py-1.5 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
            <button
              onClick={handleSendMessage}
              className="px-3 py-1.5 rounded-lg bg-white/[0.08] hover:bg-white/[0.15] text-white text-xs font-mono font-bold transition-colors"
            >
              Send
            </button>
          </div>
        </div>

        {/* View Full Profile link */}
        <button
          onClick={() => navigate(`/agents/${agent.id}`)}
          className="w-full py-2.5 px-4 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.1] text-xs font-mono font-bold text-white flex items-center justify-center gap-2 transition-colors"
        >
          <ExternalLink className="w-4 h-4 text-[#FFB020]" />
          Open Full Workforce Profile
        </button>
      </div>
    </Drawer>
  );
}
