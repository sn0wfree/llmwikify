/**
 * Global wiki state management using Zustand.
 * Manages multiple wikis, current wiki selection, and cross-wiki operations.
 */

import { create } from 'zustand';
import { api } from '../api';

export interface WikiInfo {
  wiki_id: string;
  name: string;
  type: 'local' | 'remote';
  root: string | null;
  url: string | null;
  status: 'ready' | 'loading' | 'error' | 'offline';
  page_count: number;
  is_default: boolean;
  last_accessed: string | null;
  error: string | null;
}

interface WikiState {
  // State
  wikis: WikiInfo[];
  currentWikiId: string | null;
  loading: boolean;
  error: string | null;
  isMultiWikiMode: boolean;

  // Actions
  loadWikis: () => Promise<void>;
  switchWiki: (wikiId: string) => void;
  registerWiki: (wiki: Partial<WikiInfo> & { root?: string; url?: string; api_key?: string }) => Promise<void>;
  unregisterWiki: (wikiId: string) => Promise<void>;
  scanWikis: (scanPath?: string) => Promise<void>;
  setDefaultWiki: (wikiId: string) => Promise<void>;

  // Derived getters
  currentWiki: () => WikiInfo | undefined;
  wikiIds: () => string[];
  getWikiById: (id: string) => WikiInfo | undefined;
}

export const useWikiStore = create<WikiState>((set, get) => ({
  // Initial state
  wikis: [],
  currentWikiId: null,
  loading: false,
  error: null,
  isMultiWikiMode: false,

  // Actions
  loadWikis: async () => {
    set({ loading: true, error: null });
    try {
      const response = await api.wikis.list();
      const wikis: WikiInfo[] = (response.wikis || []).map((w: Record<string, unknown>) => ({
        wiki_id: w.wiki_id as string,
        name: w.name as string,
        type: (w.type as 'local' | 'remote') || 'local',
        root: (w.root as string) || null,
        url: (w.url as string) || null,
        status: (w.status as WikiInfo['status']) || 'ready',
        page_count: (w.page_count as number) || 0,
        is_default: (w.is_default as boolean) || false,
        last_accessed: (w.last_accessed as string) || null,
        error: (w.error as string) || null,
      }));
      const defaultId = (response.default_wiki_id as string) || null;

      set({
        wikis,
        currentWikiId: defaultId || wikis[0]?.wiki_id || null,
        isMultiWikiMode: wikis.length > 1,
        loading: false,
      });
    } catch (err) {
      // If multi-wiki endpoint fails, try legacy single wiki mode
      try {
        const status = await api.wiki.status();
        const singleWiki: WikiInfo = {
          wiki_id: status.root?.split('/').pop() || 'default',
          name: status.root?.split('/').pop() || 'Wiki',
          type: 'local',
          root: status.root || null,
          url: null,
          status: 'ready',
          page_count: status.page_count || 0,
          is_default: true,
          last_accessed: null,
          error: null,
        };
        set({
          wikis: [singleWiki],
          currentWikiId: singleWiki.wiki_id,
          isMultiWikiMode: false,
          loading: false,
        });
      } catch (innerErr) {
        set({
          error: err instanceof Error ? err.message : 'Failed to load wikis',
          loading: false,
        });
      }
    }
  },

  switchWiki: (wikiId: string) => {
    const { wikis } = get();
    const wiki = wikis.find(w => w.wiki_id === wikiId);
    if (wiki) {
      set({ currentWikiId: wikiId });
    }
  },

  registerWiki: async (wikiData) => {
    set({ loading: true, error: null });
    try {
      await api.wikis.register(wikiData);
      await get().loadWikis();
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to register wiki',
        loading: false,
      });
    }
  },

  unregisterWiki: async (wikiId: string) => {
    set({ loading: true, error: null });
    try {
      await api.wikis.unregister(wikiId);
      await get().loadWikis();
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to unregister wiki',
        loading: false,
      });
    }
  },

  scanWikis: async (scanPath?: string) => {
    set({ loading: true, error: null });
    try {
      await api.wikis.scan(scanPath ? [scanPath] : undefined);
      await get().loadWikis();
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to scan wikis',
        loading: false,
      });
    }
  },

  setDefaultWiki: async (wikiId: string) => {
    set({ loading: true, error: null });
    try {
      await api.wikis.update(wikiId, { is_default: true });
      await get().loadWikis();
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to set default wiki',
        loading: false,
      });
    }
  },

  // Derived getters
  currentWiki: () => {
    const { wikis, currentWikiId } = get();
    return wikis.find(w => w.wiki_id === currentWikiId);
  },

  wikiIds: () => {
    return get().wikis.map(w => w.wiki_id);
  },

  getWikiById: (id: string) => {
    return get().wikis.find(w => w.wiki_id === id);
  },
}));
