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

interface AgentWikiState {
  wikis: WikiInfo[];
  currentWikiId: string | null;
  loading: boolean;
  error: string | null;
  isMultiWikiMode: boolean;

  loadWikis: () => Promise<void>;
  switchWiki: (wikiId: string) => void;

  currentWiki: () => WikiInfo | undefined;
  wikiIds: () => string[];
  getWikiById: (id: string) => WikiInfo | undefined;
}

export const useAgentWikiStore = create<AgentWikiState>((set, get) => ({
  wikis: [],
  currentWikiId: null,
  loading: false,
  error: null,
  isMultiWikiMode: false,

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
    } catch {
      set({
        wikis: [],
        currentWikiId: null,
        isMultiWikiMode: false,
        loading: false,
      });
    }
  },

  switchWiki: (wikiId: string) => {
    const { wikis } = get();
    const wiki = wikis.find(w => w.wiki_id === wikiId);
    if (wiki) {
      set({ currentWikiId: wikiId });
    }
  },

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