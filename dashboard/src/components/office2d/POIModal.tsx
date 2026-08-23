import { useState } from 'react';
import type { InteractivePOI } from './types';
import { Modal } from '@/components/common/Modal';
import { retroAudio } from '@/utils/retroAudio';
import {
  Coffee,
  Gamepad2,
  Droplets,
  FileText,
  Server,
  Sparkles,
  BookOpen,
  ShoppingBag,
  Zap,
  CheckCircle2,
} from 'lucide-react';

interface POIModalProps {
  poi: InteractivePOI | null;
  onClose: () => void;
  onActionTrigger?: (actionType: string) => void;
}

export function POIModal({ poi, onClose, onActionTrigger }: POIModalProps) {
  const [arcadeScore, setArcadeScore] = useState(98420);
  const [arcadeStreak, setArcadeStreak] = useState(0);
  const [whiteboardNotes, setWhiteboardNotes] = useState([
    'Sprint 14: Finalize 2D OpenOffice Pixel Engine',
    'Auth: Token refresh zero-downtime rotation',
    'Infra: Scale H100 inference pods with vLLM',
    'HR: Performance reviews for Agent Alpha & Beta',
  ]);
  const [newNote, setNewNote] = useState('');
  const [brewing, setBrewing] = useState(false);

  if (!poi) return null;

  const handleBrewCoffee = () => {
    setBrewing(true);
    retroAudio.playCoffeeBrew();
    setTimeout(() => {
      setBrewing(false);
      retroAudio.playChime();
      onActionTrigger?.('coffee_boost');
    }, 1200);
  };

  const handlePlayArcade = () => {
    retroAudio.playArcadeBeep();
    const gain = Math.floor(Math.random() * 500 + 200);
    setArcadeScore((prev) => prev + gain);
    setArcadeStreak((prev) => prev + 1);
  };

  const handleAddNote = () => {
    if (!newNote.trim()) return;
    setWhiteboardNotes((prev) => [...prev, newNote.trim()]);
    setNewNote('');
    retroAudio.playChime();
  };

  return (
    <Modal
      isOpen={!!poi}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <span className="text-xl">{poi.icon}</span>
          <span className="text-base font-semibold text-white">{poi.name}</span>
        </div>
      }
      size="md"
    >
      <div className="space-y-4">
        <p className="text-xs text-[#9C9C9F]">{poi.description}</p>

        {/* 1. Espresso Machine */}
        {poi.type === 'coffee_machine' && (
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-mono text-[#FFB020] uppercase font-bold">
                  Dark Roast Extract
                </span>
                <p className="text-xs text-[#6B6B6E]">
                  Brewing dispenses double shots to all active roaming agents.
                </p>
              </div>
              <Coffee className="w-6 h-6 text-[#FFB020]" />
            </div>
            <button
              onClick={handleBrewCoffee}
              disabled={brewing}
              className="w-full py-2.5 px-4 rounded-lg bg-[#FFB020] text-black text-xs font-mono font-bold flex items-center justify-center gap-2 hover:bg-[#FFC043] transition-colors disabled:opacity-50"
            >
              {brewing ? (
                <>
                  <div className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
                  Brewing Fresh Espresso...
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" />
                  Brew Double Shot (+40% Energy & Speed)
                </>
              )}
            </button>
          </div>
        )}

        {/* 2. Retro Arcade Machine */}
        {poi.type === 'arcade' && (
          <div className="p-4 rounded-xl bg-[#1E1B4B]/40 border border-[#8B5CF6]/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-[#C084FC]">RETRO SCORE:</span>
              <span className="text-lg font-mono font-bold text-[#38BDF8]">
                {arcadeScore.toLocaleString()} PTS
              </span>
            </div>
            <p className="text-xs text-[#9C9C9F]">
              Press the fire button to blast space asteroids and boost agent morale!
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={handlePlayArcade}
                className="flex-1 py-3 px-4 rounded-lg bg-[#EC4899] text-white text-xs font-mono font-bold flex items-center justify-center gap-2 hover:bg-[#F43F5E] active:scale-95 transition-all shadow-lg shadow-[#EC4899]/20"
              >
                <Gamepad2 className="w-4 h-4" />
                BLAST ASTEROID (Streak: {arcadeStreak})
              </button>
            </div>
          </div>
        )}

        {/* 3. Water Cooler */}
        {poi.type === 'water_cooler' && (
          <div className="p-4 rounded-xl bg-[#0284C7]/10 border border-[#38BDF8]/20 space-y-3">
            <div className="flex items-center gap-2 text-xs font-mono text-[#38BDF8]">
              <Droplets className="w-4 h-4" />
              <span>OFFICE CHATTER & GOSSIP</span>
            </div>
            <div className="p-3 rounded-lg bg-black/40 text-xs text-[#E2E8F0] italic space-y-1">
              <p>"Did you see Agent Beta's PR for the canvas shaders? Zero drops at 60fps."</p>
              <p className="text-[10px] text-[#6B6B6E] not-italic">— Overheard by the Cooler</p>
            </div>
            <button
              onClick={() => {
                retroAudio.playWaterCooler();
                onActionTrigger?.('hydrate');
              }}
              className="w-full py-2 px-3 rounded-lg bg-[#0284C7] text-white text-xs font-mono font-bold hover:bg-[#0369A1] transition-colors"
            >
              Drink Crisp Ice Water
            </button>
          </div>
        )}

        {/* 4. Whiteboard */}
        {poi.type === 'whiteboard' && (
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-[#38BDF8]">SPRINT ARCHITECTURE STICKIES</span>
              <FileText className="w-4 h-4 text-[#38BDF8]" />
            </div>
            <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
              {whiteboardNotes.map((note, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 p-2 rounded bg-white/[0.04] border border-white/[0.06] text-xs text-[#E2E8F0]"
                >
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981] mt-0.5 shrink-0" />
                  <span>{note}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddNote()}
                placeholder="Write new architecture stickie..."
                className="flex-1 bg-black/50 border border-white/[0.12] rounded-lg px-3 py-1.5 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
              />
              <button
                onClick={handleAddNote}
                className="px-3 py-1.5 rounded-lg bg-[#FFB020] text-black text-xs font-mono font-bold hover:bg-[#FFC043]"
              >
                Post
              </button>
            </div>
          </div>
        )}

        {/* 5. Server Cluster */}
        {poi.type === 'server_rack' && (
          <div className="p-4 rounded-xl bg-[#06B6D4]/10 border border-[#06B6D4]/20 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-[#06B6D4]" />
                <span className="text-xs font-mono text-[#06B6D4] font-bold">
                  8x H100 INFERENCE CLUSTER
                </span>
              </div>
              <span className="text-[11px] font-mono text-[#10B981]">ONLINE (99.98%)</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="p-2 rounded bg-black/50 border border-white/[0.06] text-center">
                <span className="text-[10px] text-[#6B6B6E] block font-mono">TFLOPS</span>
                <span className="text-xs font-mono font-bold text-white">124.8 TF</span>
              </div>
              <div className="p-2 rounded bg-black/50 border border-white/[0.06] text-center">
                <span className="text-[10px] text-[#6B6B6E] block font-mono">VRAM</span>
                <span className="text-xs font-mono font-bold text-white">640 GB</span>
              </div>
              <div className="p-2 rounded bg-black/50 border border-white/[0.06] text-center">
                <span className="text-[10px] text-[#6B6B6E] block font-mono">TEMP</span>
                <span className="text-xs font-mono font-bold text-[#10B981]">48°C</span>
              </div>
            </div>
          </div>
        )}

        {/* 6. Zen Fountain */}
        {poi.type === 'fountain' && (
          <div className="p-4 rounded-xl bg-[#10B981]/10 border border-[#10B981]/20 space-y-3">
            <div className="flex items-center gap-2 text-xs font-mono text-[#34D399]">
              <Sparkles className="w-4 h-4" />
              <span>ZEN REFLECTION & TRANQUILITY</span>
            </div>
            <p className="text-xs text-[#D1D5DB]">
              Listening to the gentle trickling of bamboo water cleanses token cache and restores
              creative clarity.
            </p>
            <button
              onClick={() => {
                retroAudio.playChime();
                onActionTrigger?.('zen_meditate');
              }}
              className="w-full py-2 px-3 rounded-lg bg-[#059669] text-white text-xs font-mono font-bold hover:bg-[#047857] transition-colors"
            >
              Start 30s Mindful Reflection
            </button>
          </div>
        )}

        {/* 7. Bookshelf */}
        {poi.type === 'bookshelf' && (
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2">
            <div className="flex items-center gap-2 text-xs font-mono text-[#FFB020]">
              <BookOpen className="w-4 h-4" />
              <span>SYSTEM PAPERS</span>
            </div>
            <ul className="text-xs text-[#9C9C9F] space-y-1 list-disc list-inside">
              <li>"Attention Is All You Need" (Vaswani et al.)</li>
              <li>"FlashAttention-3: Fast and Accurate Attention"</li>
              <li>"Designing Data-Intensive Applications" (Kleppmann)</li>
            </ul>
          </div>
        )}

        {/* 8. Vending Machine */}
        {poi.type === 'vending_machine' && (
          <div className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2">
            <div className="flex items-center gap-2 text-xs font-mono text-[#818CF8]">
              <ShoppingBag className="w-4 h-4" />
              <span>ORGANIC SNACK MATRIX</span>
            </div>
            <p className="text-xs text-[#9C9C9F]">
              Dark chocolate roasted almonds and matcha protein snacks ready for dispatch.
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}
