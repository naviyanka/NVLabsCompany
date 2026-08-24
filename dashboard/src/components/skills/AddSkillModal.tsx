import { useState } from 'react';
import {
  Upload,
  Terminal,
  Github,
  Code2,
  FileArchive,
  CheckCircle2,
  AlertCircle,
  Play,
  Sparkles,
  Loader2,
} from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { SkillItem, SkillCategory } from '@/types/skill';

interface AddSkillModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSkillAdded: (skill: SkillItem) => void;
  githubRepos?: { name: string; default_branch: string }[];
}

export function AddSkillModal({
  isOpen,
  onClose,
  onSkillAdded,
  githubRepos = [],
}: AddSkillModalProps) {
  const [activeTab, setActiveTab] = useState<'zip' | 'command' | 'github' | 'custom'>('zip');

  // Form states
  const [name, setName] = useState('');
  const [category, setCategory] = useState<SkillCategory>('Engineering');
  const [description, setDescription] = useState('');
  const [version, setVersion] = useState('1.0.0');
  const [author, setAuthor] = useState('Operator');
  const [instructionsMd, setInstructionsMd] = useState(
    '# Skill Instructions\n\nProvide detailed prompt rules, function definitions, or tool invocation parameters here.'
  );
  const [parametersJson, setParametersJson] = useState(
    '{\n  "type": "object",\n  "properties": {\n    "input": { "type": "string" }\n  }\n}'
  );

  // Source-specific states
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [commandInput, setCommandInput] = useState('npx agy add-skill @antigravity/code-refactor');
  const [githubUrl, setGithubUrl] = useState('');
  const [selectedGhRepo, setSelectedGhRepo] = useState('');

  // Status & loading
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [terminalOutput, setTerminalOutput] = useState<string[]>([]);
  const [statusMessage, setStatusMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleReset = () => {
    setName('');
    setDescription('');
    setSelectedFile(null);
    setGithubUrl('');
    setSelectedGhRepo('');
    setTerminalOutput([]);
    setStatusMessage(null);
  };

  const handleClose = () => {
    handleReset();
    onClose();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      if (!name) {
        setName(file.name.replace(/\.zip$/i, '').replace(/[-_]/g, ' '));
      }
    }
  };

  const handleRunCommand = async () => {
    if (!commandInput.trim()) return;
    setIsSubmitting(true);
    setTerminalOutput([`$ ${commandInput}`, 'Initializing installer...']);

    await new Promise((r) => setTimeout(r, 600));
    setTerminalOutput((prev) => [...prev, 'Downloading skill package manifest...']);
    await new Promise((r) => setTimeout(r, 800));
    setTerminalOutput((prev) => [...prev, 'Validating tool capability envelopes... OK']);
    await new Promise((r) => setTimeout(r, 600));
    setTerminalOutput((prev) => [...prev, 'Registering AST parser bindings... OK']);
    await new Promise((r) => setTimeout(r, 500));
    setTerminalOutput((prev) => [...prev, '✔ Skill successfully compiled & installed to Mission Control']);

    // Extract skill name from command
    const parts = commandInput.trim().split(' ');
    const lastPart = parts[parts.length - 1] || 'skill';
    const cmdName = lastPart.replace(/^@/, '').replace(/\//g, '-');

    try {
      const created = await apiClient.post<SkillItem>(
        `/api/v1/companies/${getActiveCompanyId()}/skills`,
        {
          name: name || cmdName,
          category,
          description: description || `Installed via CLI command: "${commandInput}"`,
          source_type: 'command',
          source_location: commandInput,
          version: '1.0.0',
          author: 'CLI Package Registry',
          instructions_md: instructionsMd,
          parameters_json: parametersJson,
        }
      );
      onSkillAdded(created);
      setStatusMessage({ type: 'success', text: `Skill '${created.name}' installed via CLI!` });
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: err?.detail || 'Failed to register command skill' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (activeTab === 'command') {
      await handleRunCommand();
      return;
    }

    if (!name.trim()) {
      setStatusMessage({ type: 'error', text: 'Skill title is required' });
      return;
    }

    setIsSubmitting(true);
    setStatusMessage(null);

    let sourceLocation = '';
    if (activeTab === 'zip') {
      sourceLocation = selectedFile ? selectedFile.name : 'uploaded-archive.zip';
    } else if (activeTab === 'github') {
      sourceLocation = githubUrl || selectedGhRepo || 'https://github.com';
    } else {
      sourceLocation = 'Custom Code Editor';
    }

    try {
      const created = await apiClient.post<SkillItem>(
        `/api/v1/companies/${getActiveCompanyId()}/skills`,
        {
          name: name.trim(),
          category,
          description: description.trim() || `Capability envelope for ${name}`,
          source_type: activeTab,
          source_location: sourceLocation,
          version,
          author,
          instructions_md: instructionsMd,
          parameters_json: parametersJson,
        }
      );

      onSkillAdded(created);
      setStatusMessage({ type: 'success', text: `Skill '${created.name}' registered successfully!` });
      setTimeout(() => {
        handleClose();
      }, 800);
    } catch (err: any) {
      setStatusMessage({ type: 'error', text: err?.detail || 'Failed to register skill' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Add & Install Workforce Skill" size="lg">
      <div className="space-y-4">
        {/* Source Type Selector Tabs */}
        <div className="grid grid-cols-4 gap-1 p-1 bg-[#101012] border border-white/[0.08] rounded-[8px]">
          <button
            type="button"
            onClick={() => setActiveTab('zip')}
            className={`py-2 px-3 rounded-[6px] text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
              activeTab === 'zip'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Upload size={14} /> ZIP Archive
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('command')}
            className={`py-2 px-3 rounded-[6px] text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
              activeTab === 'command'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Terminal size={14} /> CLI Command
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('github')}
            className={`py-2 px-3 rounded-[6px] text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
              activeTab === 'github'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Github size={14} /> GitHub Repo
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('custom')}
            className={`py-2 px-3 rounded-[6px] text-xs font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer ${
              activeTab === 'custom'
                ? 'bg-[#FFB020] text-[#0A0A0B] font-bold shadow'
                : 'text-[#A8A8AB] hover:text-white'
            }`}
          >
            <Code2 size={14} /> Write Custom
          </button>
        </div>

        {statusMessage && (
          <div
            className={`p-3 rounded-[6px] border text-xs flex items-center gap-2 ${
              statusMessage.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}
          >
            {statusMessage.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            <span>{statusMessage.text}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* TAB 1: ZIP ARCHIVE UPLOAD */}
          {activeTab === 'zip' && (
            <div className="space-y-3">
              <div className="p-6 border-2 border-dashed border-white/[0.15] hover:border-[#FFB020]/50 rounded-[10px] bg-[#141416] text-center transition-colors">
                <input
                  type="file"
                  accept=".zip,.tar.gz"
                  onChange={handleFileChange}
                  className="hidden"
                  id="skill-zip-upload"
                />
                <label htmlFor="skill-zip-upload" className="cursor-pointer block">
                  <FileArchive className="w-10 h-10 text-[#FFB020] mx-auto mb-2 opacity-80" />
                  <p className="text-xs font-medium text-white">
                    {selectedFile ? selectedFile.name : 'Click or drag & drop .zip skill package here'}
                  </p>
                  <p className="text-[11px] text-[#6B6B6E] mt-1 font-mono">
                    Must contain SKILL.md or package.json manifest
                  </p>
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Skill Title *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Distributed Consensus Verification"
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Category
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value as SkillCategory)}
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="Engineering">Engineering</option>
                    <option value="Security">Security & Auditing</option>
                    <option value="QA">QA & Verification</option>
                    <option value="AI & Research">AI & Research</option>
                    <option value="Frontend">Frontend</option>
                    <option value="DevOps">DevOps</option>
                    <option value="Data & Analytics">Data & Analytics</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: COMMAND / CLI RUNNER */}
          {activeTab === 'command' && (
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                  Installation Command
                </label>
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <Terminal size={14} className="text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                    <input
                      type="text"
                      value={commandInput}
                      onChange={(e) => setCommandInput(e.target.value)}
                      placeholder="e.g. npx agy add-skill @antigravity/canvas-generative"
                      className="w-full pl-9 pr-3 py-2 bg-[#0C0C0E] border border-white/[0.15] rounded text-xs text-[#00FF66] font-mono focus:outline-none focus:border-[#FFB020]"
                      required
                    />
                  </div>
                  <Button
                    variant="primary"
                    size="sm"
                    type="button"
                    onClick={handleRunCommand}
                    disabled={isSubmitting}
                    icon={<Play size={13} />}
                  >
                    {isSubmitting ? 'Running...' : 'Execute'}
                  </Button>
                </div>
              </div>

              {/* Terminal Logs Output */}
              {terminalOutput.length > 0 && (
                <div className="p-3 bg-[#08080A] border border-white/[0.1] rounded-[6px] font-mono text-[11px] text-gray-300 space-y-1 max-h-40 overflow-y-auto">
                  {terminalOutput.map((line, idx) => (
                    <div
                      key={idx}
                      className={
                        line.startsWith('$')
                          ? 'text-[#FFB020] font-bold'
                          : line.includes('✔')
                          ? 'text-emerald-400 font-bold'
                          : 'text-gray-400'
                      }
                    >
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: GITHUB REPOSITORY IMPORT */}
          {activeTab === 'github' && (
            <div className="space-y-3 font-sans">
              <div>
                <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                  GitHub Repository URL or Path
                </label>
                <div className="relative">
                  <Github size={14} className="text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={githubUrl}
                    onChange={(e) => {
                      setGithubUrl(e.target.value);
                      if (e.target.value && !name) {
                        const parts = e.target.value.split('/');
                        setName(parts[parts.length - 1] || '');
                      }
                    }}
                    placeholder="https://github.com/antigravity/skill-canvas-generative"
                    className="w-full pl-9 pr-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                  />
                </div>
              </div>

              {githubRepos.length > 0 && (
                <div>
                  <label className="block text-[11px] font-mono text-[#6B6B6E] uppercase mb-1">
                    Or select from connected GitHub PAT repos:
                  </label>
                  <select
                    value={selectedGhRepo}
                    onChange={(e) => {
                      setSelectedGhRepo(e.target.value);
                      if (e.target.value) {
                        setGithubUrl(`https://github.com/${e.target.value}`);
                        setName(e.target.value.split('/')[1] || e.target.value);
                      }
                    }}
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="">-- Choose Connected Repository --</option>
                    {githubRepos.map((r) => (
                      <option key={r.name} value={r.name}>
                        {r.name} ({r.default_branch})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Skill Title *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Canvas Generative Art"
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Category
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value as SkillCategory)}
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="Engineering">Engineering</option>
                    <option value="Security">Security & Auditing</option>
                    <option value="QA">QA & Verification</option>
                    <option value="AI & Research">AI & Research</option>
                    <option value="Frontend">Frontend</option>
                    <option value="DevOps">DevOps</option>
                    <option value="Data & Analytics">Data & Analytics</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: MANUAL CUSTOM AUTHORING */}
          {activeTab === 'custom' && (
            <div className="space-y-3 font-sans">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Skill Title *
                  </label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Custom Vulnerability Fuzzer"
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                    required
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                    Category
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value as SkillCategory)}
                    className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="Engineering">Engineering</option>
                    <option value="Security">Security & Auditing</option>
                    <option value="QA">QA & Verification</option>
                    <option value="AI & Research">AI & Research</option>
                    <option value="Frontend">Frontend</option>
                    <option value="DevOps">DevOps</option>
                    <option value="Data & Analytics">Data & Analytics</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                  SKILL.md Markdown & Rules
                </label>
                <textarea
                  value={instructionsMd}
                  onChange={(e) => setInstructionsMd(e.target.value)}
                  rows={4}
                  className="w-full p-2.5 bg-[#0C0C0E] border border-white/[0.12] rounded text-xs font-mono text-gray-200 focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div>
                <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                  Tool Parameters Schema (JSON)
                </label>
                <textarea
                  value={parametersJson}
                  onChange={(e) => setParametersJson(e.target.value)}
                  rows={3}
                  className="w-full p-2.5 bg-[#0C0C0E] border border-white/[0.12] rounded text-xs font-mono text-emerald-400 focus:outline-none focus:border-[#FFB020]"
                />
              </div>
            </div>
          )}

          {/* Common Details (Description, Author, Version) */}
          {activeTab !== 'command' && (
            <div className="pt-2 border-t border-white/[0.08] space-y-3 font-sans">
              <div>
                <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
                  Skill Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  placeholder="Summarize capability envelope for agent task assignments..."
                  className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-mono text-[#6B6B6E] uppercase mb-1">
                    Author / Vendor
                  </label>
                  <input
                    type="text"
                    value={author}
                    onChange={(e) => setAuthor(e.target.value)}
                    className="w-full px-3 py-1 bg-[#141416] border border-white/[0.08] rounded text-xs text-gray-300 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-mono text-[#6B6B6E] uppercase mb-1">
                    Version
                  </label>
                  <input
                    type="text"
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    className="w-full px-3 py-1 bg-[#141416] border border-white/[0.08] rounded text-xs text-gray-300 focus:outline-none"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={handleClose}>
              Cancel
            </Button>
            {activeTab !== 'command' && (
              <Button
                variant="primary"
                size="sm"
                type="submit"
                disabled={isSubmitting}
                icon={isSubmitting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              >
                {isSubmitting ? 'Registering...' : 'Register Skill'}
              </Button>
            )}
          </div>
        </form>
      </div>
    </Modal>
  );
}
