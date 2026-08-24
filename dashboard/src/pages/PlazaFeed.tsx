import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Send,
  Tag,
  ThumbsUp,
  MessageSquare,
  Pin,
  Rocket,
  Brain,
  AlertTriangle,
  Download,
  Filter,
  CheckCircle2,
  Code2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { getActiveCompanyId } from '@/config';

interface Comment {
  id: string;
  author_agent_id: string;
  author_name: string;
  author_role: string;
  content: string;
  created_at: string;
}

interface Reactions {
  likes: number;
  deployed: number;
  insight: number;
  blocker: number;
}

interface SOPArtifact {
  project_name: string;
  architecture_style: string;
  mermaid_diagram?: string;
  user_stories?: string[];
}

interface Post {
  id: string;
  company_id: string;
  author_agent_id: string;
  author_name: string;
  author_role: string;
  title: string;
  content: string;
  category: 'update' | 'discovery' | 'blocker' | 'achievement' | 'sop_artifact';
  tags: string[];
  is_pinned?: boolean;
  focus_item?: string;
  trigger_type?: string;
  sop_artifact?: SOPArtifact;
  likes: number;
  reactions?: Reactions;
  comments: Comment[];
  created_at: string;
}

const AGENT_ROSTER = [
  { id: 'all', name: 'All Agents & Operators' },
  { id: 'agent-navi-ceo', name: 'Navi (CEO & Principal Orchestrator)' },
  { id: 'agent-pixel', name: 'Pixel (Frontend Specialist)' },
  { id: 'agent-forge', name: 'Forge (Backend Systems Lead)' },
  { id: 'agent-shield', name: 'Shield (QA & Security Auditor)' },
];

export default function PlazaFeed() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  
  // Composer state
  const [newTitle, setNewTitle] = useState('');
  const [newContent, setNewContent] = useState('');
  const [newCategory, setNewCategory] = useState<Post['category']>('update');
  const [newFocusItem, setNewFocusItem] = useState('');
  const [newTriggerType, setNewTriggerType] = useState('none');
  const [newTags, setNewTags] = useState('');
  const [isPinned, setIsPinned] = useState(false);
  const [showComposer, setShowComposer] = useState(true);

  // Accordion state for SOP artifacts & comments
  const [expandedSOPs, setExpandedSOPs] = useState<Record<string, boolean>>({});
  const [commentInputs, setCommentInputs] = useState<Record<string, string>>({});

  // Local reaction toggle state per post
  const [myReactions, setMyReactions] = useState<Record<string, Record<string, boolean>>>(() => {
    try {
      const raw = localStorage.getItem('nexus_plaza_my_reactions');
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('nexus_plaza_my_reactions', JSON.stringify(myReactions));
    } catch {
      // ignore
    }
  }, [myReactions]);

  const companyId = getActiveCompanyId();

  const fetchPosts = async () => {
    try {
      setLoading(true);
      const url = selectedCategory === 'all'
        ? `/api/v1/companies/${companyId}/plaza`
        : `/api/v1/companies/${companyId}/plaza?category=${selectedCategory}`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setPosts(data.posts || []);
      }
    } catch (err) {
      console.error('Failed to fetch plaza posts', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPosts();
  }, [selectedCategory]);

  const handleCreatePost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;

    const parsedTags = newTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      const res = await fetch(`/api/v1/companies/${companyId}/plaza`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_agent_id: 'agent-navi-ceo',
          author_name: 'Navi',
          author_role: 'CEO & Principal System Orchestrator',
          title: newTitle.trim(),
          content: newContent.trim(),
          category: newCategory,
          is_pinned: isPinned,
          focus_item: newFocusItem.trim() || null,
          trigger_type: newTriggerType !== 'none' ? newTriggerType : null,
          tags: parsedTags.length > 0 ? parsedTags : ['operator', newCategory],
        }),
      });

      if (res.ok) {
        setNewTitle('');
        setNewContent('');
        setNewFocusItem('');
        setNewTags('');
        setIsPinned(false);
        fetchPosts();
      }
    } catch (err) {
      console.error('Failed to publish post', err);
    }
  };

  const handleReact = async (postId: string, reactionType: 'likes' | 'deployed' | 'insight' | 'blocker') => {
    const isCurrentlyActive = Boolean(myReactions[postId]?.[reactionType]);
    const action = isCurrentlyActive ? 'remove' : 'add';

    try {
      const res = await fetch(`/api/v1/companies/${companyId}/plaza/${postId}/react`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reactionType, action, toggled: isCurrentlyActive }),
      });
      if (res.ok) {
        const data = await res.json();
        setPosts((prev) =>
          prev.map((p) =>
            p.id === postId
              ? { ...p, reactions: data.reactions, likes: data.reactions.likes }
              : p
          )
        );

        setMyReactions((prev) => ({
          ...prev,
          [postId]: {
            ...(prev[postId] || {}),
            [reactionType]: !isCurrentlyActive,
          },
        }));
      }
    } catch (err) {
      console.error('Failed to react to post', err);
    }
  };

  const handleAddComment = async (postId: string) => {
    const text = commentInputs[postId];
    if (!text || !text.trim()) return;

    try {
      const res = await fetch(`/api/v1/companies/${companyId}/plaza/${postId}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_agent_id: 'agent-navi-ceo',
          author_name: 'Navi',
          author_role: 'CEO & Principal System Orchestrator',
          content: text.trim(),
        }),
      });

      if (res.ok) {
        const updatedPost = await res.json();
        setPosts((prev) => prev.map((p) => (p.id === postId ? updatedPost : p)));
        setCommentInputs((prev) => ({ ...prev, [postId]: '' }));
      }
    } catch (err) {
      console.error('Failed to add comment', err);
    }
  };

  const exportKnowledgeStream = (format: 'json' | 'markdown') => {
    if (format === 'json') {
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(posts, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `plaza_knowledge_export_${Date.now()}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    } else {
      let md = `# 🏛️ Company Plaza Knowledge Context Export\nExported: ${new Date().toISOString()}\n\n`;
      posts.forEach((p) => {
        md += `## [${p.category.toUpperCase()}] ${p.title}\n`;
        md += `**Author**: ${p.author_name} (${p.author_role})\n`;
        md += `**Date**: ${p.created_at}\n\n`;
        md += `${p.content}\n\n`;
        if (p.focus_item) md += `*Focus*: ${p.focus_item}\n`;
        if (p.tags && p.tags.length > 0) md += `*Tags*: ${p.tags.join(', ')}\n`;
        md += `---\n\n`;
      });
      const dataStr = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(md);
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `plaza_knowledge_export_${Date.now()}.md`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    }
  };

  const toggleSOP = (id: string) => {
    setExpandedSOPs((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Filter posts by category and selected agent author
  const filteredPosts = posts.filter((post) => {
    if (selectedAgent !== 'all' && post.author_agent_id !== selectedAgent) return false;
    return true;
  });

  const pinnedPost = posts.find((p) => p.is_pinned);

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-[#EEEEF0] p-6 space-y-6 max-w-6xl mx-auto">
      {/* ──────────────── Top Navigation & Header Bar ──────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
        <div className="flex items-center space-x-3.5">
          <div className="w-10 h-10 rounded-lg bg-[#FFB020]/10 border border-[#FFB020]/30 flex items-center justify-center text-[#FFB020]">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-bold tracking-tight text-white">The Plaza</h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#141416] border border-white/[0.1] text-[#FFB020]">
                CLAWITH KNOWLEDGE FEED
              </span>
            </div>
            <p className="text-xs font-mono text-[#6B6B6E]">
              Asynchronous Multi-Agent Social Stream, Focus Triggers & Architectural SOP Artifacts
            </p>
          </div>
        </div>

        {/* Action Controls & Export */}
        <div className="flex items-center space-x-2.5">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => exportKnowledgeStream('markdown')}
            className="text-xs font-mono border-white/[0.1] hover:bg-white/[0.05]"
          >
            <Download className="w-3.5 h-3.5 mr-1.5 text-[#6B6B6E]" />
            Export Context
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowComposer(!showComposer)}
            className="bg-[#FFB020] hover:bg-[#F59E0B] text-black font-semibold text-xs"
          >
            <Send className="w-3.5 h-3.5 mr-1.5" />
            {showComposer ? 'Hide Broadcast' : 'Compose Post'}
          </Button>
        </div>
      </div>

      {/* ──────────────── Pinned CEO Directive Banner ──────────────── */}
      {pinnedPost && (
        <Card className="border-[#FFB020]/40 bg-[#141416]/90 relative overflow-hidden">
          <div className="absolute top-0 right-0 px-3 py-1 bg-[#FFB020]/10 border-l border-b border-[#FFB020]/30 rounded-bl text-[10px] font-mono text-[#FFB020] flex items-center space-x-1">
            <Pin className="w-3 h-3 text-[#FFB020]" />
            <span>PINNED CEO DIRECTIVE</span>
          </div>

          <div className="p-5 space-y-2.5">
            <div className="flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-[#FFB020] animate-pulse" />
              <span className="text-xs font-mono text-[#FFB020] uppercase tracking-wider font-semibold">
                {pinnedPost.author_name} ({pinnedPost.author_role})
              </span>
              <span className="text-xs text-[#6B6B6E] font-mono">
                • {new Date(pinnedPost.created_at).toLocaleString()}
              </span>
            </div>

            <h2 className="text-base font-bold text-white">{pinnedPost.title}</h2>
            <p className="text-xs text-[#EEEEF0]/90 leading-relaxed font-sans">{pinnedPost.content}</p>

            <div className="pt-2 flex items-center justify-between text-xs text-[#6B6B6E] font-mono">
              <div className="flex items-center space-x-3">
                <span className="px-2 py-0.5 rounded bg-white/[0.05] text-white/80 text-[10px]">
                  Tag: #{pinnedPost.tags?.[0] || 'system'}
                </span>
                <span>{pinnedPost.comments?.length || 0} Directives Logged</span>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* ──────────────── Broadcast Composer Box ──────────────── */}
      {showComposer && (
        <Card className="bg-[#141416] border-white/[0.08] p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div className="flex items-center space-x-2">
              <Brain className="w-4 h-4 text-[#FFB020]" />
              <span className="text-xs font-mono text-white font-semibold uppercase tracking-wider">
                Broadcast Knowledge or Milestone
              </span>
            </div>

            <div className="flex items-center space-x-3 text-xs">
              <label className="flex items-center space-x-1.5 text-[#6B6B6E] cursor-pointer hover:text-white">
                <input
                  type="checkbox"
                  checked={isPinned}
                  onChange={(e) => setIsPinned(e.target.checked)}
                  className="rounded bg-[#0A0A0B] border-white/[0.2] text-[#FFB020] focus:ring-0"
                />
                <span className="font-mono text-[11px]">Pin as CEO Directive</span>
              </label>

              <select
                value={newCategory}
                onChange={(e: any) => setNewCategory(e.target.value)}
                className="bg-[#0A0A0B] border border-white/[0.1] text-xs text-white rounded px-2.5 py-1 focus:outline-none focus:border-[#FFB020] font-mono"
              >
                <option value="update">Update</option>
                <option value="discovery">Discovery</option>
                <option value="achievement">Achievement</option>
                <option value="blocker">Blocker</option>
                <option value="sop_artifact">SOP Artifact</option>
              </select>
            </div>
          </div>

          <div className="space-y-3">
            <input
              type="text"
              placeholder="Post title or milestone headline..."
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              className="w-full bg-[#0A0A0B] border border-white/[0.1] rounded-lg px-3.5 py-2 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] font-mono"
            />

            <textarea
              placeholder="Share architectural discoveries, focus item progress, or SOP execution packages with the workforce..."
              rows={3}
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              className="w-full bg-[#0A0A0B] border border-white/[0.1] rounded-lg px-3.5 py-2.5 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] resize-none"
            />

            {/* Extra Metadata Inputs */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                  Bound Focus Item (Clawith)
                </label>
                <input
                  type="text"
                  placeholder="e.g. [x] Sub-10ms SSE Audit"
                  value={newFocusItem}
                  onChange={(e) => setNewFocusItem(e.target.value)}
                  className="w-full bg-[#0A0A0B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
                />
              </div>

              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                  Trigger Engine
                </label>
                <select
                  value={newTriggerType}
                  onChange={(e) => setNewTriggerType(e.target.value)}
                  className="w-full bg-[#0A0A0B] border border-white/[0.1] text-xs text-white rounded px-2.5 py-1.5 focus:outline-none focus:border-[#FFB020] font-mono"
                >
                  <option value="none">None (Manual Post)</option>
                  <option value="cron">Cron Schedule</option>
                  <option value="webhook">Webhook Listener</option>
                  <option value="poll">Interval Poll</option>
                  <option value="on_message">Message Listener</option>
                </select>
              </div>

              <div>
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                  Tags (Comma separated)
                </label>
                <input
                  type="text"
                  placeholder="architecture, fastapi, sse"
                  value={newTags}
                  onChange={(e) => setNewTags(e.target.value)}
                  className="w-full bg-[#0A0A0B] border border-white/[0.1] rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
                />
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2 border-t border-white/[0.06]">
            <Button
              onClick={handleCreatePost}
              variant="primary"
              size="sm"
              className="bg-[#FFB020] hover:bg-[#F59E0B] text-black font-semibold text-xs"
            >
              <Send className="w-3.5 h-3.5 mr-1.5" />
              Publish Post
            </Button>
          </div>
        </Card>
      )}

      {/* ──────────────── Filter Toolbar ──────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#141416] p-3 rounded-lg border border-white/[0.08]">
        {/* Category Pills */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 sm:pb-0">
          {['all', 'update', 'discovery', 'achievement', 'blocker', 'sop_artifact'].map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`px-3 py-1 rounded text-xs font-mono capitalize transition-colors ${
                selectedCategory === cat
                  ? 'bg-[#FFB020]/20 text-[#FFB020] border border-[#FFB020]/40 font-semibold'
                  : 'bg-[#0A0A0B] text-[#6B6B6E] hover:text-white border border-white/[0.05]'
              }`}
            >
              {cat.replace('_', ' ')}
            </button>
          ))}
        </div>

        {/* Agent Roster Dropdown */}
        <div className="flex items-center space-x-2">
          <Filter className="w-3.5 h-3.5 text-[#6B6B6E]" />
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="bg-[#0A0A0B] border border-white/[0.1] text-xs text-white rounded px-2.5 py-1 focus:outline-none focus:border-[#FFB020] font-mono"
          >
            {AGENT_ROSTER.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ──────────────── Plaza Feed Post List ──────────────── */}
      {loading ? (
        <div className="text-center py-16 text-xs font-mono text-[#6B6B6E]">
          Loading Plaza Knowledge Stream...
        </div>
      ) : filteredPosts.length === 0 ? (
        <div className="text-center py-16 text-xs font-mono text-[#6B6B6E]">
          No posts matching the selected filters.
        </div>
      ) : (
        <div className="space-y-4">
          {filteredPosts.map((post) => {
            const reactions = post.reactions || {
              likes: post.likes || 0,
              deployed: 0,
              insight: 0,
              blocker: 0,
            };

            return (
              <Card key={post.id} className="bg-[#141416] border-white/[0.08] hover:border-white/[0.15] transition-colors p-5 space-y-3.5">
                {/* Author Header */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="w-9 h-9 rounded-lg bg-[#FFB020]/10 border border-[#FFB020]/20 flex items-center justify-center font-mono font-bold text-[#FFB020] text-sm">
                      {post.author_name.charAt(0)}
                    </div>
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-semibold text-white text-sm">{post.author_name}</span>
                        <span className="text-[11px] font-mono text-[#6B6B6E]">({post.author_role})</span>
                      </div>
                      <span className="text-[10px] font-mono text-[#6B6B6E]">
                        {new Date(post.created_at).toLocaleString()}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    {post.trigger_type && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-purple-500/10 text-purple-400 border border-purple-500/20">
                        TRIGGER: {post.trigger_type.toUpperCase()}
                      </span>
                    )}

                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase border ${
                        post.category === 'achievement'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                          : post.category === 'blocker'
                          ? 'bg-red-500/10 text-red-400 border-red-500/30'
                          : post.category === 'discovery'
                          ? 'bg-purple-500/10 text-purple-400 border-purple-500/30'
                          : post.category === 'sop_artifact'
                          ? 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30'
                          : 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                      }`}
                    >
                      {post.category.replace('_', ' ')}
                    </span>
                  </div>
                </div>

                {/* Title & Body */}
                <div className="space-y-1.5">
                  <h3 className="text-sm font-bold text-white tracking-wide">{post.title}</h3>
                  <p className="text-xs text-[#EEEEF0]/90 leading-relaxed font-sans whitespace-pre-line">
                    {post.content}
                  </p>
                </div>

                {/* Focus Item Badge (Clawith Inspired) */}
                {post.focus_item && (
                  <div className="p-2 bg-[#0A0A0B] rounded border border-white/[0.06] flex items-center space-x-2 text-xs font-mono">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-[#6B6B6E]">Focus Marker:</span>
                    <span className="text-emerald-300 font-semibold">{post.focus_item}</span>
                  </div>
                )}

                {/* MetaGPT SOP Artifact Viewer */}
                {post.sop_artifact && (
                  <div className="border border-white/[0.08] rounded-lg bg-[#0A0A0B] overflow-hidden">
                    <button
                      onClick={() => toggleSOP(post.id)}
                      className="w-full px-3.5 py-2 flex items-center justify-between text-xs font-mono text-[#FFB020] bg-white/[0.02] hover:bg-white/[0.04]"
                    >
                      <div className="flex items-center space-x-2">
                        <Code2 className="w-3.5 h-3.5" />
                        <span>MetaGPT SOP Architecture Artifact ({post.sop_artifact.project_name})</span>
                      </div>
                      {expandedSOPs[post.id] ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>

                    {expandedSOPs[post.id] && (
                      <div className="p-3.5 space-y-2 border-t border-white/[0.06] text-xs font-mono">
                        <div>
                          <span className="text-[#6B6B6E]">Style:</span>{' '}
                          <span className="text-white">{post.sop_artifact.architecture_style}</span>
                        </div>
                        {post.sop_artifact.mermaid_diagram && (
                          <pre className="p-3 bg-black/60 rounded border border-white/[0.08] text-[11px] text-emerald-400 overflow-x-auto">
                            {post.sop_artifact.mermaid_diagram}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Tag Pills */}
                {post.tags && post.tags.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {post.tags.map((t, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 bg-[#0A0A0B] text-[#6B6B6E] border border-white/[0.06] rounded text-[10px] font-mono flex items-center space-x-1"
                      >
                        <Tag className="w-2.5 h-2.5" />
                        <span>#{t}</span>
                      </span>
                    ))}
                  </div>
                )}

                {/* ──────────────── Multi-Reaction Toolbar ──────────────── */}
                <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between text-xs font-mono text-[#6B6B6E]">
                  <div className="flex items-center space-x-2">
                    {/* Likes Toggle */}
                    <button
                      onClick={() => handleReact(post.id, 'likes')}
                      className={`px-2.5 py-1 rounded text-[11px] flex items-center space-x-1.5 transition-all ${
                        myReactions[post.id]?.likes
                          ? 'bg-[#FFB020]/20 text-[#FFB020] border border-[#FFB020]/60 shadow-[0_0_10px_rgba(255,176,32,0.25)] font-bold'
                          : 'bg-[#0A0A0B] border border-white/[0.06] hover:border-[#FFB020]/40 hover:text-white'
                      }`}
                    >
                      <ThumbsUp className="w-3.5 h-3.5 text-[#FFB020]" />
                      <span>{reactions.likes}</span>
                    </button>

                    {/* Deployed Toggle */}
                    <button
                      onClick={() => handleReact(post.id, 'deployed')}
                      className={`px-2.5 py-1 rounded text-[11px] flex items-center space-x-1.5 transition-all ${
                        myReactions[post.id]?.deployed
                          ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/60 shadow-[0_0_10px_rgba(16,185,129,0.25)] font-bold'
                          : 'bg-[#0A0A0B] border border-white/[0.06] hover:border-emerald-500/40 hover:text-white'
                      }`}
                    >
                      <Rocket className="w-3.5 h-3.5 text-emerald-400" />
                      <span>{reactions.deployed}</span>
                    </button>

                    {/* Insight Toggle */}
                    <button
                      onClick={() => handleReact(post.id, 'insight')}
                      className={`px-2.5 py-1 rounded text-[11px] flex items-center space-x-1.5 transition-all ${
                        myReactions[post.id]?.insight
                          ? 'bg-purple-500/20 text-purple-400 border border-purple-500/60 shadow-[0_0_10px_rgba(168,85,247,0.25)] font-bold'
                          : 'bg-[#0A0A0B] border border-white/[0.06] hover:border-purple-500/40 hover:text-white'
                      }`}
                    >
                      <Brain className="w-3.5 h-3.5 text-purple-400" />
                      <span>{reactions.insight}</span>
                    </button>

                    {/* Blocker Toggle */}
                    <button
                      onClick={() => handleReact(post.id, 'blocker')}
                      className={`px-2.5 py-1 rounded text-[11px] flex items-center space-x-1.5 transition-all ${
                        myReactions[post.id]?.blocker
                          ? 'bg-red-500/20 text-red-400 border border-red-500/60 shadow-[0_0_10px_rgba(239,68,68,0.25)] font-bold'
                          : 'bg-[#0A0A0B] border border-white/[0.06] hover:border-red-500/40 hover:text-white'
                      }`}
                    >
                      <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                      <span>{reactions.blocker}</span>
                    </button>
                  </div>

                  <div className="flex items-center space-x-1.5 text-xs text-[#6B6B6E]">
                    <MessageSquare className="w-3.5 h-3.5" />
                    <span>{post.comments?.length || 0} Comments</span>
                  </div>
                </div>

                {/* Threaded Comments List */}
                {post.comments && post.comments.length > 0 && (
                  <div className="space-y-2 pt-2 pl-3 border-l border-[#FFB020]/30">
                    {post.comments.map((cmt) => (
                      <div key={cmt.id} className="bg-[#0A0A0B] rounded p-2.5 border border-white/[0.05] space-y-1">
                        <div className="flex items-center justify-between text-[11px] font-mono">
                          <span className="font-semibold text-[#FFB020]">{cmt.author_name}</span>
                          <span className="text-[#6B6B6E]">{new Date(cmt.created_at).toLocaleTimeString()}</span>
                        </div>
                        <p className="text-xs text-[#EEEEF0] font-sans">{cmt.content}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Comment Form Input */}
                <div className="flex items-center space-x-2 pt-1">
                  <input
                    type="text"
                    placeholder="Write a response as Navi (CEO)..."
                    value={commentInputs[post.id] || ''}
                    onChange={(e) => setCommentInputs({ ...commentInputs, [post.id]: e.target.value })}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddComment(post.id)}
                    className="flex-1 bg-[#0A0A0B] border border-white/[0.1] rounded px-3 py-1.5 text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] font-mono"
                  />
                  <Button
                    onClick={() => handleAddComment(post.id)}
                    variant="secondary"
                    size="sm"
                    className="text-xs font-mono border-white/[0.1] hover:bg-white/[0.05]"
                  >
                    Reply
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
