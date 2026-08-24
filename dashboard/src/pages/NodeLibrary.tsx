import { getActiveCompanyId } from '@/config';
import { BarChart3, Boxes, Bug, Cloud, Cpu, Database, FileText, Filter, Globe, HardDrive, Image, Mail, MessageSquare, Mic, Radio, Search, Shield, ShoppingCart, Users, Wrench, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

interface NodeInput {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  description: string;
}

interface NodeOutput {
  name: string;
  type: string;
  description: string;
}

interface NodeDef {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  inputs: NodeInput[];
  outputs: NodeOutput[];
  credentials: string[];
  version: string;
}

interface CategoryInfo {
  name: string;
  count: number;
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  ai: <Cpu className="w-4 h-4" />,
  communication: <MessageSquare className="w-4 h-4" />,
  data: <Database className="w-4 h-4" />,
  devops: <Wrench className="w-4 h-4" />,
  file: <FileText className="w-4 h-4" />,
  http: <Globe className="w-4 h-4" />,
  schedule: <Zap className="w-4 h-4" />,
  trigger: <Zap className="w-4 h-4" />,
  cloud: <Cloud className="w-4 h-4" />,
  browser: <Globe className="w-4 h-4" />,
  email: <Mail className="w-4 h-4" />,
  messaging: <MessageSquare className="w-4 h-4" />,
  database: <Database className="w-4 h-4" />,
  search: <Search className="w-4 h-4" />,
  analytics: <BarChart3 className="w-4 h-4" />,
  storage: <HardDrive className="w-4 h-4" />,
  monitoring: <BarChart3 className="w-4 h-4" />,
  testing: <Bug className="w-4 h-4" />,
  documentation: <FileText className="w-4 h-4" />,
  media: <Image className="w-4 h-4" />,
  social: <Users className="w-4 h-4" />,
  crm: <Users className="w-4 h-4" />,
  ecommerce: <ShoppingCart className="w-4 h-4" />,
  voice: <Mic className="w-4 h-4" />,
  iot: <Radio className="w-4 h-4" />,
  security: <Shield className="w-4 h-4" />,
  utility: <Wrench className="w-4 h-4" />,
  productivity: <Zap className="w-4 h-4" />,
  finance: <BarChart3 className="w-4 h-4" />,
  device: <Radio className="w-4 h-4" />,
  custom: <Boxes className="w-4 h-4" />,
};

const CATEGORY_COLORS: Record<string, string> = {
  ai: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  communication: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  data: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  devops: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  file: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  http: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  schedule: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  trigger: 'bg-red-500/20 text-red-400 border-red-500/30',
  cloud: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
  browser: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  email: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  messaging: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  database: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
  search: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  analytics: 'bg-lime-500/20 text-lime-400 border-lime-500/30',
  storage: 'bg-stone-500/20 text-stone-400 border-stone-500/30',
  monitoring: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  testing: 'bg-fuchsia-500/20 text-fuchsia-400 border-fuchsia-500/30',
  documentation: 'bg-neutral-500/20 text-neutral-400 border-neutral-500/30',
  media: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  social: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  crm: 'bg-green-500/20 text-green-400 border-green-500/30',
  ecommerce: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  voice: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  iot: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  security: 'bg-red-500/20 text-red-400 border-red-500/30',
  utility: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  productivity: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  finance: 'bg-green-500/20 text-green-400 border-green-500/30',
  device: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  custom: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
};

export function NodeLibrary() {
  const [nodes, setNodes] = useState<NodeDef[]>([]);
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [totalNodes, setTotalNodes] = useState(0);
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<NodeDef | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchNodes();
    fetchCategories();
  }, []);

  const fetchNodes = async () => {
    try {
      const companyId = getActiveCompanyId();
      const res = await fetch(`/api/v1/nodes`, {
        headers: { 'X-Company-Id': companyId },
      });
      if (res.ok) {
        const data = await res.json();
        setNodes(data.items || []);
        setTotalNodes(data.total || 0);
      }
    } catch (err) {
      console.error('Failed to fetch nodes:', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const companyId = getActiveCompanyId();
      const res = await fetch(`/api/v1/nodes/categories`, {
        headers: { 'X-Company-Id': companyId },
      });
      if (res.ok) {
        const data = await res.json();
        setCategories(data.categories || []);
      }
    } catch (err) {
      console.error('Failed to fetch categories:', err);
    }
  };

  const filteredNodes = useMemo(() => {
    let result = nodes;
    if (selectedCategory) {
      result = result.filter((n) => n.category === selectedCategory);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (n) => n.name.toLowerCase().includes(q) || n.description.toLowerCase().includes(q)
      );
    }
    return result;
  }, [nodes, search, selectedCategory]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-[#FFB020] border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-mono text-[#6B6B6E]">Loading Node Library...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col gap-4 p-6 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-display font-bold text-[#F2F1EE]">Node Library</h1>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            {totalNodes} workflow nodes across {categories.length} categories
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#6B6B6E]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search nodes..."
              className="pl-9 pr-4 py-2 w-64 bg-[#141416] border border-white/[0.08] rounded-md text-sm text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]/50"
            />
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex gap-4 flex-1 min-h-0">
        {/* Category Sidebar */}
        <div className="w-56 shrink-0 overflow-y-auto border border-white/[0.06] rounded-lg bg-[#0E0E10] p-3 space-y-1">
          <button
            onClick={() => setSelectedCategory(null)}
            className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-xs transition-colors ${!selectedCategory
                ? 'bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/30'
                : 'text-[#A8A8AB] hover:bg-white/[0.04]'
              }`}
          >
            <span className="flex items-center gap-2">
              <Filter className="w-3.5 h-3.5" />
              All Nodes
            </span>
            <span className="font-mono text-[10px]">{totalNodes}</span>
          </button>
          {categories.map((cat) => (
            <button
              key={cat.name}
              onClick={() => setSelectedCategory(cat.name === selectedCategory ? null : cat.name)}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-xs transition-colors ${selectedCategory === cat.name
                  ? 'bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/30'
                  : 'text-[#A8A8AB] hover:bg-white/[0.04]'
                }`}
            >
              <span className="flex items-center gap-2 capitalize">
                {CATEGORY_ICONS[cat.name] || <Boxes className="w-3.5 h-3.5" />}
                {cat.name}
              </span>
              <span className="font-mono text-[10px]">{cat.count}</span>
            </button>
          ))}
        </div>

        {/* Node Grid */}
        <div className="flex-1 overflow-y-auto">
          {filteredNodes.length === 0 ? (
            <div className="h-full flex items-center justify-center text-[#6B6B6E] text-sm">
              No nodes found matching your criteria.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {filteredNodes.map((node) => (
                <button
                  key={node.id}
                  onClick={() => setSelectedNode(selectedNode?.id === node.id ? null : node)}
                  className={`text-left p-4 rounded-lg border transition-all ${selectedNode?.id === node.id
                      ? 'bg-[#FFB020]/5 border-[#FFB020]/40'
                      : 'bg-[#141416] border-white/[0.06] hover:border-white/[0.12] hover:bg-[#1A1A1E]'
                    }`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`w-8 h-8 rounded-md flex items-center justify-center border shrink-0 ${CATEGORY_COLORS[node.category] || 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'}`}>
                      {CATEGORY_ICONS[node.category] || <Boxes className="w-4 h-4" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-[#F2F1EE] truncate">{node.name}</div>
                      <div className="text-[11px] text-[#6B6B6E] mt-0.5 line-clamp-2">{node.description}</div>
                      <div className="flex items-center gap-2 mt-2">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border ${CATEGORY_COLORS[node.category] || 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30'}`}>
                          {node.category}
                        </span>
                        {node.credentials.length > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                            {node.credentials.length} credential{node.credentials.length > 1 ? 's' : ''}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {selectedNode?.id === node.id && (
                    <div className="mt-3 pt-3 border-t border-white/[0.06] space-y-2">
                      {node.inputs.length > 0 && (
                        <div>
                          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Inputs</div>
                          <div className="flex flex-wrap gap-1">
                            {node.inputs.map((inp) => (
                              <span key={inp.name} className="px-1.5 py-0.5 bg-white/[0.04] rounded text-[10px] text-[#A8A8AB] font-mono">
                                {inp.name}{inp.required ? '*' : ''}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {node.outputs.length > 0 && (
                        <div>
                          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Outputs</div>
                          <div className="flex flex-wrap gap-1">
                            {node.outputs.map((out) => (
                              <span key={out.name} className="px-1.5 py-0.5 bg-emerald-500/10 rounded text-[10px] text-emerald-400 font-mono">
                                {out.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {node.credentials.length > 0 && (
                        <div>
                          <div className="text-[10px] font-mono text-[#6B6B6E] uppercase mb-1">Required Credentials</div>
                          <div className="flex flex-wrap gap-1">
                            {node.credentials.map((cred) => (
                              <span key={cred} className="px-1.5 py-0.5 bg-amber-500/10 rounded text-[10px] text-amber-400 font-mono">
                                {cred}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="text-[10px] font-mono text-[#6B6B6E]">
                        v{node.version} &middot; ID: {node.id}
                      </div>
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
