/**
 * WikiManager - Panel for managing multiple wikis.
 * Shows list of wikis, allows adding/removing, and health checks.
 */

import { useState } from 'react';
import { X, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useWikiStore, WikiInfo } from '../../stores/wikiStore';
import { ConfirmDialog } from './ConfirmDialog';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';

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
    error,
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
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);

  const handleAdd = async () => {
    const wikiId = formData.wiki_id.trim();
    const root = formData.root.trim();
    const url = formData.url.trim();

    if (!wikiId) {
      setFormError('Wiki ID is required');
      return;
    }
    if (addType === 'local' && !root) {
      setFormError('Root Path is required for local wiki');
      return;
    }
    if (addType === 'remote' && !url) {
      setFormError('Server URL is required for remote wiki');
      return;
    }

    setFormError(null);
    try {
      await registerWiki({
        wiki_id: wikiId,
        name: formData.name.trim() || wikiId,
        type: addType,
        root: addType === 'local' ? root : undefined,
        url: addType === 'remote' ? url : undefined,
        api_key: formData.api_key.trim() || undefined,
      });

      setShowAddForm(false);
      setFormData({ wiki_id: '', name: '', root: '', url: '', api_key: '' });
    } catch {
      return;
    }
  };

  const handleRemove = async (wikiId: string) => {
    setConfirmRemoveId(wikiId);
  };

  const confirmRemove = async () => {
    if (!confirmRemoveId) return;
    const id = confirmRemoveId;
    setConfirmRemoveId(null);
    try {
      await unregisterWiki(id);
    } catch {
      /* toast handled by store */
    }
  };

  const handleSetDefault = async (wikiId: string) => {
    await setDefaultWiki(wikiId);
  };

  return (
    <>
      <ConfirmDialog
        open={confirmRemoveId !== null}
        onOpenChange={(open) => { if (!open) setConfirmRemoveId(null); }}
        title={confirmRemoveId ? `Remove wiki "${confirmRemoveId}"?` : ''}
        description="The wiki will be unregistered from the manager. Files on disk are not deleted and can be re-added later."
        confirmLabel="Remove"
        cancelLabel="Cancel"
        destructive
        onConfirm={confirmRemove}
      />
      <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
        <DialogContent
          className="max-w-2xl sm:max-w-2xl max-h-[80vh] flex flex-col gap-0 p-0"
          showCloseButton={false}
        >
          <DialogHeader className="px-6 py-4 border-b border-border flex-row items-center justify-between space-y-0">
            <DialogTitle>Wiki Manager</DialogTitle>
            <button
              onClick={onClose}
              className="p-1 hover:bg-muted rounded transition-colors text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </DialogHeader>

          {/* Content */}
          <div className="p-6 overflow-y-auto max-h-[60vh]">
            {/* Error banner */}
            {(formError || error) && (
              <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded p-2 mb-4">
                {formError || error}
              </div>
            )}

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
              <div className="bg-muted/50 rounded-lg p-4">
                <h3 className="text-sm font-medium text-foreground mb-3">Add New Wiki</h3>

                {/* Type toggle */}
                <div className="flex gap-2 mb-4">
                  <button
                    onClick={() => setAddType('local')}
                    className={`px-3 py-1.5 text-sm rounded transition-colors ${
                      addType === 'local'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-foreground hover:bg-muted/70'
                    }`}
                  >
                    Local Directory
                  </button>
                  <button
                    onClick={() => setAddType('remote')}
                    className={`px-3 py-1.5 text-sm rounded transition-colors ${
                      addType === 'remote'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-foreground hover:bg-muted/70'
                    }`}
                  >
                    Remote Server
                  </button>
                </div>

                {/* Form fields */}
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Wiki ID *</label>
                    <input
                      type="text"
                      value={formData.wiki_id}
                      onChange={(e) => setFormData({ ...formData, wiki_id: e.target.value })}
                      placeholder="my-wiki"
                      className="w-full px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Display Name</label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      placeholder="My Wiki"
                      className="w-full px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                    />
                  </div>

                  {addType === 'local' ? (
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">Root Path *</label>
                      <input
                        type="text"
                        value={formData.root}
                        onChange={(e) => setFormData({ ...formData, root: e.target.value })}
                        placeholder="/path/to/wiki"
                        className="w-full px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                      />
                    </div>
                  ) : (
                    <>
                      <div>
                        <label className="block text-xs text-muted-foreground mb-1">Server URL *</label>
                        <input
                          type="text"
                          value={formData.url}
                          onChange={(e) => setFormData({ ...formData, url: e.target.value })}
                          placeholder="http://wiki-server:8765"
                          className="w-full px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted-foreground mb-1">API Key (optional)</label>
                        <input
                          type="password"
                          value={formData.api_key}
                          onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                          placeholder="sk-..."
                          className="w-full px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                        />
                      </div>
                    </>
                  )}
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-2 mt-4">
                  <button
                    onClick={() => {
                      setFormError(null);
                      setShowAddForm(false);
                    }}
                    className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleAdd}
                    disabled={!formData.wiki_id.trim() || (addType === 'local' && !formData.root.trim()) || (addType === 'remote' && !formData.url.trim()) || loading}
                    className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {loading ? 'Adding...' : 'Add Wiki'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={() => setShowAddForm(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-muted text-foreground rounded hover:bg-muted/70 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Add Wiki
                </button>
                <div className="flex gap-2 items-center flex-1">
                  <input
                    type="text"
                    value={scanPath}
                    onChange={(e) => setScanPath(e.target.value)}
                    placeholder="Scan path (optional, default: current dir)"
                    className="flex-1 px-3 py-2 bg-background border border-input rounded text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary"
                  />
                  <button
                    onClick={() => scanWikis(scanPath || undefined)}
                    disabled={loading}
                    className="flex items-center gap-2 px-4 py-2 bg-muted text-foreground rounded hover:bg-muted/70 disabled:opacity-50 transition-colors"
                  >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    Scan
                  </button>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
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
    offline: 'bg-muted-foreground',
  }[wiki.status];

  return (
    <div
      className={`p-4 rounded-lg border transition-colors ${
        isActive
          ? 'bg-primary/10 border-primary/50'
          : 'bg-muted/50 border-border hover:border-muted-foreground/50'
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${statusColor}`} />
          <div>
            <div className="font-medium text-foreground">{wiki.name}</div>
            <div className="text-xs text-muted-foreground">
              {wiki.wiki_id} · {wiki.type} · {wiki.page_count} pages
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {wiki.is_default && (
            <span className="text-xs bg-primary text-primary-foreground px-2 py-0.5 rounded">
              Default
            </span>
          )}
          <button
            onClick={onSelect}
            className={`px-3 py-1 text-xs rounded transition-colors ${
              isActive
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-foreground hover:bg-muted/70'
            }`}
          >
            {isActive ? 'Active' : 'Select'}
          </button>
          {!wiki.is_default && (
            <button
              onClick={onSetDefault}
              className="px-3 py-1 text-xs bg-muted text-foreground rounded hover:bg-muted/70 transition-colors"
            >
              Set Default
            </button>
          )}
          <button
            onClick={onRemove}
            className="p-1 text-muted-foreground hover:text-red-400 transition-colors"
            aria-label={`Remove ${wiki.wiki_id}`}
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
