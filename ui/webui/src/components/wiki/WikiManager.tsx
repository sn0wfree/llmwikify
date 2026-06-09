/**
 * WikiManager - Panel for managing multiple wikis.
 * Shows list of wikis, allows adding/removing, and health checks.
 */

import { useState } from 'react';
import { useWikiStore, WikiInfo } from '../../stores/wikiStore';

interface WikiManagerProps {
  onClose: () => void;
}

export function WikiManager({ onClose }: WikiManagerProps) {
  const {
    wikis,
    currentWikiId,
    switchWiki,
    registerWiki,
    unregisterWiki,
    scanWikis,
    setDefaultWiki,
    loading,
  } = useWikiStore();

  const [showAddForm, setShowAddForm] = useState(false);
  const [addType, setAddType] = useState<'local' | 'remote'>('local');
  const [scanPath, setScanPath] = useState('');
  const [formData, setFormData] = useState({
    wiki_id: '',
    name: '',
    root: '',
    url: '',
    api_key: '',
  });

  const handleAdd = async () => {
    if (!formData.wiki_id) return;

    await registerWiki({
      wiki_id: formData.wiki_id,
      name: formData.name || formData.wiki_id,
      type: addType,
      root: addType === 'local' ? formData.root : undefined,
      url: addType === 'remote' ? formData.url : undefined,
      api_key: formData.api_key || undefined,
    });

    setShowAddForm(false);
    setFormData({ wiki_id: '', name: '', root: '', url: '', api_key: '' });
  };

  const handleRemove = async (wikiId: string) => {
    if (confirm(`Remove wiki "${wikiId}"?`)) {
      await unregisterWiki(wikiId);
    }
  };

  const handleSetDefault = async (wikiId: string) => {
    await setDefaultWiki(wikiId);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-200">Wiki Manager</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-700 rounded transition-colors"
          >
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {/* Wiki list */}
          <div className="space-y-3 mb-6">
            {wikis.map((wiki) => (
              <WikiCard
                key={wiki.wiki_id}
                wiki={wiki}
                isActive={wiki.wiki_id === currentWikiId}
                onSelect={() => switchWiki(wiki.wiki_id)}
                onSetDefault={() => handleSetDefault(wiki.wiki_id)}
                onRemove={() => handleRemove(wiki.wiki_id)}
              />
            ))}
          </div>

          {/* Add form */}
          {showAddForm ? (
            <div className="bg-slate-700/50 rounded-lg p-4">
              <h3 className="text-sm font-medium text-slate-300 mb-3">Add New Wiki</h3>

              {/* Type toggle */}
              <div className="flex gap-2 mb-4">
                <button
                  onClick={() => setAddType('local')}
                  className={`px-3 py-1.5 text-sm rounded transition-colors ${
                    addType === 'local'
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-600 text-slate-300 hover:bg-slate-500'
                  }`}
                >
                  Local Directory
                </button>
                <button
                  onClick={() => setAddType('remote')}
                  className={`px-3 py-1.5 text-sm rounded transition-colors ${
                    addType === 'remote'
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-600 text-slate-300 hover:bg-slate-500'
                  }`}
                >
                  Remote Server
                </button>
              </div>

              {/* Form fields */}
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Wiki ID *</label>
                  <input
                    type="text"
                    value={formData.wiki_id}
                    onChange={(e) => setFormData({ ...formData, wiki_id: e.target.value })}
                    placeholder="my-wiki"
                    className="w-full px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Display Name</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="My Wiki"
                    className="w-full px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
                  />
                </div>

                {addType === 'local' ? (
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Root Path *</label>
                    <input
                      type="text"
                      value={formData.root}
                      onChange={(e) => setFormData({ ...formData, root: e.target.value })}
                      placeholder="/path/to/wiki"
                      className="w-full px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                ) : (
                  <>
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Server URL *</label>
                      <input
                        type="text"
                        value={formData.url}
                        onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                        placeholder="http://wiki-server:8765"
                        className="w-full px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">API Key (optional)</label>
                      <input
                        type="password"
                        value={formData.api_key}
                        onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                        placeholder="sk-..."
                        className="w-full px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  </>
                )}
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-2 mt-4">
                <button
                  onClick={() => setShowAddForm(false)}
                  className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAdd}
                  disabled={!formData.wiki_id || loading}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? 'Adding...' : 'Add Wiki'}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <button
                onClick={() => setShowAddForm(true)}
                className="flex items-center gap-2 px-4 py-2 bg-slate-700 text-slate-300 rounded hover:bg-slate-600 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                Add Wiki
              </button>
              <div className="flex gap-2 items-center">
              <input
                type="text"
                value={scanPath}
                onChange={(e) => setScanPath(e.target.value)}
                placeholder="Scan path (optional, default: current dir)"
                className="flex-1 px-3 py-2 bg-slate-600 border border-slate-500 rounded text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500"
              />
              <button
                onClick={() => scanWikis(scanPath || undefined)}
                disabled={loading}
                className="flex items-center gap-2 px-4 py-2 bg-slate-700 text-slate-300 rounded hover:bg-slate-600 disabled:opacity-50 transition-colors"
              >
                <svg className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Scan
              </button>
            </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function WikiCard({
  wiki,
  isActive,
  onSelect,
  onSetDefault,
  onRemove,
}: {
  wiki: WikiInfo;
  isActive: boolean;
  onSelect: () => void;
  onSetDefault: () => void;
  onRemove: () => void;
}) {
  const statusColor = {
    ready: 'bg-green-500',
    loading: 'bg-yellow-500',
    error: 'bg-red-500',
    offline: 'bg-slate-500',
  }[wiki.status];

  return (
    <div
      className={`p-4 rounded-lg border transition-colors ${
        isActive
          ? 'bg-blue-600/10 border-blue-500/50'
          : 'bg-slate-700/50 border-slate-600 hover:border-slate-500'
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${statusColor}`} />
          <div>
            <div className="font-medium text-slate-200">{wiki.name}</div>
            <div className="text-xs text-slate-400">
              {wiki.wiki_id} · {wiki.type} · {wiki.page_count} pages
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {wiki.is_default && (
            <span className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded">
              Default
            </span>
          )}
          <button
            onClick={onSelect}
            className={`px-3 py-1 text-xs rounded transition-colors ${
              isActive
                ? 'bg-blue-600 text-white'
                : 'bg-slate-600 text-slate-300 hover:bg-slate-500'
            }`}
          >
            {isActive ? 'Active' : 'Select'}
          </button>
          {!wiki.is_default && (
            <button
              onClick={onSetDefault}
              className="px-3 py-1 text-xs bg-slate-600 text-slate-300 rounded hover:bg-slate-500 transition-colors"
            >
              Set Default
            </button>
          )}
          <button
            onClick={onRemove}
            className="p-1 text-slate-400 hover:text-red-400 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
