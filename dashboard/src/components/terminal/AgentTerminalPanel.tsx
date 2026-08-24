/**
 * AgentTerminalPanel — Real-time multi-agent output streaming via WebSocket.
 *
 * Connects to the WebSocket at /ws/{clientId}, subscribes to agent:* channels,
 * and displays streaming stdout from all running agents in a split-pane view.
 */

import { useState, useEffect, useRef } from 'react';
import { Terminal, Trash2 } from 'lucide-react';

interface TerminalLine {
  id: string;
  agentId: string;
  line: string;
  timestamp: string;
}

interface AgentTerminalPanelProps {
  agentIds?: string[];
  maxLines?: number;
}

export function AgentTerminalPanel({ agentIds, maxLines = 500 }: AgentTerminalPanelProps) {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const clientId = `terminal-${Date.now().toString(36)}`;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${clientId}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      // Subscribe to agent channels
      if (agentIds && agentIds.length > 0) {
        agentIds.forEach((id) => {
          ws.send(JSON.stringify({ action: 'subscribe', channel: `agent:${id.slice(0, 8)}` }));
        });
      } else {
        // Subscribe to a wildcard-like pattern — subscribe to common prefix
        ws.send(JSON.stringify({ action: 'subscribe', channel: 'agent:broadcast' }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'agent_output') {
          const newLine: TerminalLine = {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            agentId: data.session_id?.slice(0, 8) || 'unknown',
            line: data.line || '',
            timestamp: new Date().toISOString(),
          };
          setLines((prev) => {
            const updated = [...prev, newLine];
            return updated.length > maxLines ? updated.slice(-maxLines) : updated;
          });
        }
      } catch {
        // Non-JSON message — ignore
      }
    };

    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [agentIds?.join(','), maxLines]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines]);

  const filteredLines = filter
    ? lines.filter((l) => l.agentId === filter)
    : lines;

  const uniqueAgents = [...new Set(lines.map((l) => l.agentId))];

  return (
    <div className="flex flex-col h-full bg-[#0A0A0B] border border-white/[0.08] rounded-[10px] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#101012] border-b border-white/[0.08]">
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-[#FFB020]" />
          <span className="text-xs font-mono font-medium text-[#F2F1EE]">Agent Terminal</span>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-[10px] font-mono text-[#6B6B6E]">
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Agent filter tabs */}
          <button
            onClick={() => setFilter(null)}
            className={`px-2 py-0.5 text-[10px] font-mono rounded ${!filter ? 'bg-[#FFB020]/20 text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'}`}
          >
            All
          </button>
          {uniqueAgents.slice(0, 5).map((id) => (
            <button
              key={id}
              onClick={() => setFilter(id)}
              className={`px-2 py-0.5 text-[10px] font-mono rounded ${filter === id ? 'bg-[#FFB020]/20 text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'}`}
            >
              {id}
            </button>
          ))}

          <button
            onClick={() => setLines([])}
            className="p-1 text-[#6B6B6E] hover:text-[#F2F1EE] transition-colors"
            title="Clear terminal"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {/* Terminal output */}
      <div className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed">
        {filteredLines.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[#6B6B6E] text-xs">
            {connected
              ? 'Waiting for agent output... Run a task or chat to see live output here.'
              : 'WebSocket disconnected. Check if the backend is running.'}
          </div>
        ) : (
          filteredLines.map((l) => (
            <div key={l.id} className="flex gap-2 hover:bg-white/[0.02] py-0.5">
              <span className="text-[#FFB020] shrink-0 w-16">[{l.agentId}]</span>
              <span className="text-[#A8A8AB] whitespace-pre-wrap break-all">{l.line}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
