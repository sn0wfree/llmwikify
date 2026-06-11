import { useState, useRef, useEffect, useCallback } from 'react';
import { Cpu, Wifi, Coins, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, StopCircle, History, ThumbsUp, ThumbsDown, Pencil, GitBranch, Paperclip, X, Settings } from 'lucide-react';
import { chatStream, ChatStreamEvent, api } from '../../api';
import { useToast } from '../wiki/Toast';
import { useWikiStore } from '../../stores/wikiStore';
import { MessageBubble } from '../ui/MessageBubble';
import { ToolCard } from '../ui/ToolCard';
import { SessionSidebar } from './SessionSidebar';
import { ToolsRail } from './ToolsRail';
import { ConfirmationModal } from './ConfirmationModal';
import { cn } from '@/lib/utils';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  tokensOutput?: number;
  messageId?: string;
}

interface ToolCall {
  call_id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  status: 'pending' | 'streaming' | 'done' | 'error';
  startedAt?: number;
  finishedAt?: number;
  duration_ms?: number;
}

function parseToolCalls(raw: unknown): ToolCall[] | undefined {
  if (raw == null) return undefined;
  if (Array.isArray(raw)) return raw as ToolCall[];
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as ToolCall[]) : undefined;
    } catch { return undefined; }
  }
  return undefined;
}

type ConnectionState = 'idle' | 'live' | 'error';

const STATE_TONE: Record<ConnectionState, string> = {
  idle: 'text-muted-foreground',
  live: 'text-green-500',
  error: 'text-destructive',
};

const STATE_DOT: Record<ConnectionState, string> = {
  idle: 'bg-muted-foreground/40',
  live: 'bg-green-500',
  error: 'bg-destructive',
};

const STATE_LABEL: Record<ConnectionState, string> = {
  idle: 'idle', live: 'live', error: 'error',
};

interface PendingConfirmation {
  confirmationId: string;
  tool: string;
  args: Record<string, unknown>;
  impact: Record<string, unknown>;
  group?: string;
}

interface DbMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  tool_calls: unknown[] | null;
  created_at: string;
  tokens_output?: number;
  reverted?: number;
}

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: "Hello! I'm your wiki assistant. How can I help?", timestamp: new Date().toISOString() },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentAssistantMsg, setCurrentAssistantMsg] = useState('');
  const [currentThinking, setCurrentThinking] = useState('');
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCall[]>([]);
  // Phase 1.4 (v0.36): mirrors of the streaming state used by
  // the ``done`` handler to avoid stale closure captures.
  const currentThinkingRef = useRef('');
  const currentToolCallsRef = useRef<ToolCall[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showRail, setShowRail] = useState(true);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmingLoading, setConfirmingLoading] = useState(false);
  const [modelName, setModelName] = useState<string>('');
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle');
  const [tokenEstimate, setTokenEstimate] = useState(0);
  // v0.40: server-side session status (idle/busy)
  const [serverStatus, setServerStatus] = useState<'idle' | 'busy'>('idle');
  // v0.40: per-message feedback
  const [feedback, setFeedback] = useState<Record<string, 'up' | 'down'>>({});
  // v0.40: edit state
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState('');
  // v0.40: file attachments
  const [attachments, setAttachments] = useState<Array<{ name: string; mime: string; data: string; preview?: string }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // v0.40: settings dialog (system prompt editor)
  const [showSettings, setShowSettings] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Phase 5.1 (v0.36): AbortController for cancelling SSE streams.
  const abortControllerRef = useRef<AbortController | null>(null);
  const { addToast } = useToast();
  const { currentWikiId } = useWikiStore();

  useEffect(() => {
    let mounted = true;
    api.agent.getConfig().then((cfg: { model?: string }) => {
      if (mounted && cfg?.model) setModelName(cfg.model);
    }).catch(() => {});
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentAssistantMsg, currentThinking]);

  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const data = await api.agent.getSessionMessages(sessionId);
      const dbMessages = data.messages as DbMessage[];
      if (dbMessages.length > 0) {
        const loaded: Message[] = dbMessages.map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          timestamp: m.created_at,
          toolCalls: parseToolCalls(m.tool_calls),
          tokensOutput: m.tokens_output,
          messageId: m.id,
        }));
        setMessages(loaded);
      }
    } catch { /* silent */ }
  }, []);

  const handleSelectSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    setTokenEstimate(0);
    await loadMessages(sessionId);
  }, [loadMessages]);

  const handleNewChat = useCallback(async () => {
    try {
      const { session_id } = await api.agent.createSession(currentWikiId || undefined);
      setCurrentSessionId(session_id);
      setSidebarRefreshKey((k) => k + 1);
    } catch {
      setCurrentSessionId(null);
    }
    setMessages([{ role: 'assistant', content: "Hello! I'm your wiki assistant. How can I help?", timestamp: new Date().toISOString() }]);
    setTokenEstimate(0);
    setInput('');
  }, [currentWikiId]);

  const handleApproveConfirmation = useCallback(async () => {
    if (!pendingConfirmation || !currentSessionId) return;
    setConfirmingLoading(true);
    setPendingConfirmation(null);
    setLoading(true);
    setCurrentAssistantMsg('');
    setCurrentToolCalls([]);
    currentThinkingRef.current = '';
    currentToolCallsRef.current = '';

    // Phase 5.1 (v0.36): create AbortController for cancellation.
    const ac = new AbortController();
    abortControllerRef.current = ac;

    // Phase 5.4 (v0.36): retry logic for confirmation flow.
    const MAX_RETRIES = 2;
    const RETRY_DELAYS = [1000, 2000];
    let attempt = 0;
    let gotFirstChunk = false;

    while (attempt <= MAX_RETRIES) {
      try {
        const reader = api.confirmations.approveAndContinue(
          pendingConfirmation.confirmationId, currentSessionId, currentWikiId || undefined, ac.signal
        ).getReader();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          gotFirstChunk = true;
          const event = value as ChatStreamEvent;
          switch (event.type) {
            case 'message_delta':
              setCurrentAssistantMsg((prev) => prev + event.content);
              break;
            case 'thinking':
              setCurrentThinking((prev) => {
                currentThinkingRef.current = prev + event.content;
                return prev + event.content;
              });
              break;
            case 'tool_call_start': {
              setCurrentToolCalls((prev) => {
                const next = [...prev, { call_id: event.call_id, tool: event.tool, args: event.args, status: 'streaming' as const, startedAt: Date.now() }];
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_end': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, result: event.result, status: 'done' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'confirmation_required':
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, status: 'done' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              setPendingConfirmation({ confirmationId: event.confirmation_id, tool: event.tool, args: event.args, impact: (event.impact || {}) as Record<string, unknown>, group: undefined });
              break;
            case 'done': {
              const thinkingSnapshot = currentThinkingRef.current;
              const toolCallsSnapshot = currentToolCallsRef.current;
              setMessages((prev) => [...prev, { role: 'assistant', content: event.final_response, thinking: thinkingSnapshot || undefined, timestamp: new Date().toISOString(), toolCalls: toolCallsSnapshot }]);
              setCurrentAssistantMsg('');
              setCurrentThinking('');
              setCurrentToolCalls([]);
              currentThinkingRef.current = '';
              currentToolCallsRef.current = [];
              break;
            }
            case 'tool_call_error':
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, error: event.error, status: 'error' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            case 'error':
              addToast('error', event.message || 'Confirmation error');
              break;
          }
        }
        addToast('success', 'Action approved and executed');
        break;
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') break;
        if (!gotFirstChunk && attempt < MAX_RETRIES) {
          const delay = RETRY_DELAYS[attempt] || 2000;
          addToast('info', `Connection lost, retrying in ${delay / 1000}s...`);
          await new Promise((r) => setTimeout(r, delay));
          attempt++;
          continue;
        }
        addToast('error', `Failed to approve: ${e instanceof Error ? e.message : 'Unknown error'}`);
        break;
      }
    }
    setConfirmingLoading(false);
    setLoading(false);
    abortControllerRef.current = null;
  }, [pendingConfirmation, currentSessionId, currentWikiId, addToast]);

  const handleRejectConfirmation = useCallback(async () => {
    if (!pendingConfirmation) return;
    setConfirmingLoading(true);
    try {
      await api.confirmations.reject(pendingConfirmation.confirmationId, currentWikiId || undefined);
      addToast('info', 'Action rejected');
      setPendingConfirmation(null);
    } catch (e) {
      addToast('error', `Failed to reject: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setConfirmingLoading(false);
    }
  }, [pendingConfirmation, currentWikiId, addToast]);

  // v0.40: simple approve (no continue) with "once" or "always" response
  const handleSimpleApprove = useCallback(async (response: 'once' | 'always') => {
    if (!pendingConfirmation) return;
    setConfirmingLoading(true);
    try {
      await api.confirmations.approve(
        pendingConfirmation.confirmationId,
        currentWikiId || undefined,
        undefined,
        response,
      );
      addToast('success', response === 'always' ? 'Always approved' : 'Approved');
      setPendingConfirmation(null);
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setConfirmingLoading(false);
    }
  }, [pendingConfirmation, currentWikiId, addToast]);

  // Phase 5.1 (v0.36): abort the current SSE stream.
  const handleStop = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setLoading(false);
    setConnectionState('idle');
    // Flush any buffered text into the message history.
    setCurrentAssistantMsg((prev) => {
      if (prev) {
        setMessages((m) => [...m, { role: 'assistant', content: prev, timestamp: new Date().toISOString() }]);
      }
      return '';
    });
    setCurrentThinking('');
    setCurrentToolCalls([]);
  }, []);

  // v0.40: abort session via server-side mechanism
  const handleAbort = useCallback(async () => {
    if (!currentSessionId) return;
    // First abort the client stream
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    // Then call server-side abort
    try {
      await api.agent.abortSession(currentSessionId);
      addToast('info', 'Session aborted');
    } catch { /* silent */ }
    setLoading(false);
    setServerStatus('idle');
    setConnectionState('idle');
  }, [currentSessionId, addToast]);

  // v0.40: revert session to a specific user message
  const handleRevert = useCallback(async (messageId: string) => {
    if (!currentSessionId || !messageId) return;
    try {
      const result = await api.agent.revertSession(currentSessionId, messageId);
      addToast('success', `Reverted ${result.reverted} message(s)`);
      setSidebarRefreshKey((k) => k + 1);
      await loadMessages(currentSessionId);
    } catch (e) {
      addToast('error', `Failed to revert: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [currentSessionId, addToast, loadMessages]);

  // v0.40: edit a user message
  const handleStartEdit = useCallback((msg: Message) => {
    if (!msg.messageId) return;
    setEditingMessageId(msg.messageId);
    setEditingContent(msg.content);
  }, []);

  const handleCancelEdit = useCallback(() => {
    setEditingMessageId(null);
    setEditingContent('');
  }, []);

  const handleSaveEdit = useCallback(async () => {
    if (!currentSessionId || !editingMessageId || !editingContent.trim()) return;
    try {
      await api.agent.editMessage(currentSessionId, editingMessageId, editingContent);
      setEditingMessageId(null);
      setEditingContent('');
      await loadMessages(currentSessionId);
      addToast('success', 'Message updated');
    } catch (e) {
      addToast('error', `Failed to edit: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [currentSessionId, editingMessageId, editingContent, addToast, loadMessages]);

  // v0.40: fork session at a specific message (uses revert + creates new session)
  const handleFork = useCallback(async (messageId: string, content: string) => {
    if (!currentSessionId || !messageId) return;
    try {
      // Revert in current session
      await api.agent.revertSession(currentSessionId, messageId);
      // Create a new session
      const { session_id } = await api.agent.createSession(currentWikiId || undefined);
      setCurrentSessionId(session_id);
      setSidebarRefreshKey((k) => k + 1);
      setMessages([{ role: 'assistant', content: "Forked conversation. Send a message to continue.", timestamp: new Date().toISOString() }]);
      setInput(content);
      addToast('success', 'Forked into new session');
    } catch (e) {
      addToast('error', `Failed to fork: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [currentSessionId, currentWikiId, addToast]);

  // v0.40: message feedback
  const handleFeedback = useCallback((msgId: string, type: 'up' | 'down') => {
    setFeedback((prev) => ({ ...prev, [msgId]: type }));
  }, []);

  // v0.40: file upload handler
  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const newAttachments: Array<{ name: string; mime: string; data: string; preview?: string }> = [];
    for (const file of files) {
      if (file.size > 10 * 1024 * 1024) {
        addToast('error', `File too large: ${file.name} (max 10MB)`);
        continue;
      }
      const data = await fileToBase64(file);
      const preview = file.type.startsWith('image/') ? data : undefined;
      newAttachments.push({ name: file.name, mime: file.type, data, preview });
    }
    setAttachments((prev) => [...prev, ...newAttachments]);
    e.target.value = ''; // Reset input
  }, [addToast]);

  const handleRemoveAttachment = useCallback((idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  // v0.40: settings dialog (system prompt)
  const openSettings = useCallback(async () => {
    try {
      const cfg = await api.agent.getConfig();
      setSystemPrompt(cfg.system_prompt || '');
    } catch { /* silent */ }
    setShowSettings(true);
  }, []);

  const saveSystemPrompt = useCallback(async () => {
    try {
      await api.agent.saveConfig({ system_prompt: systemPrompt } as any);
      addToast('success', 'System prompt saved');
      setShowSettings(false);
    } catch (e) {
      addToast('error', `Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [systemPrompt, addToast]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { role: 'user', content: input, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setCurrentAssistantMsg('');
    setCurrentThinking('');
    setCurrentToolCalls([]);
    // Phase 1.4 (v0.36): reset refs in lock-step with state.
    currentThinkingRef.current = '';
    currentToolCallsRef.current = [];
    setConnectionState('live');
    setTokenEstimate((t) => t + Math.ceil(input.length / 4));

    // Phase 5.1 (v0.36): create AbortController for cancellation.
    const ac = new AbortController();
    abortControllerRef.current = ac;

    // Phase 5.4 (v0.36): SSE auto-reconnect with exponential backoff.
    // The retry loop re-opens the stream if the first chunk was never
    // received (network error, timeout, 5xx). Once events start
    // flowing, we don't retry (partial state is already visible).
    const MAX_RETRIES = 3;
    const RETRY_DELAYS = [1000, 2000, 4000];
    let attempt = 0;
    let gotFirstChunk = false;

    while (attempt <= MAX_RETRIES) {
      try {
        const reader = chatStream(input, currentSessionId || undefined, currentWikiId || undefined, ac.signal, attachments).getReader();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          gotFirstChunk = true;
          const event = value as ChatStreamEvent;

          switch (event.type) {
            case 'session_created':
              setCurrentSessionId(event.session_id);
              setSidebarRefreshKey((k) => k + 1);
              break;
            case 'message_delta':
              setCurrentAssistantMsg((prev) => prev + event.content);
              break;
            case 'thinking':
              setCurrentThinking((prev) => {
                currentThinkingRef.current = prev + event.content;
                return prev + event.content;
              });
              break;
            case 'tool_call_start': {
              setCurrentToolCalls((prev) => {
                const next = [...prev, { call_id: event.call_id, tool: event.tool, args: event.args, status: 'streaming' as const, startedAt: Date.now() }];
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_end': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, result: event.result, status: 'done' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_error': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, error: event.error, status: 'error' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'confirmation_required':
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.call_id === event.call_id ? { ...tc, status: 'done' as const, finishedAt: Date.now(), duration_ms: event.duration_ms } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              setPendingConfirmation({ confirmationId: event.confirmation_id, tool: event.tool, args: event.args, impact: (event.impact || {}) as Record<string, unknown>, group: undefined });
              break;
            case 'done': {
              const thinkingSnapshot = currentThinkingRef.current;
              const toolCallsSnapshot = currentToolCallsRef.current;
              setMessages((prev) => [...prev, { role: 'assistant', content: event.final_response, thinking: thinkingSnapshot || undefined, timestamp: new Date().toISOString(), toolCalls: toolCallsSnapshot }]);
              setCurrentAssistantMsg('');
              setCurrentThinking('');
              setCurrentToolCalls([]);
              currentThinkingRef.current = '';
              currentToolCallsRef.current = [];
              setTokenEstimate((t) => t + Math.ceil((event.final_response.length + thinkingSnapshot.length) / 4));
              setConnectionState('idle');
              break;
            }
            case 'save_warning':
              addToast('warning', event.reason || 'Save incomplete');
              break;
            case 'error':
              addToast('error', event.message || 'Chat error');
              setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${event.message}`, timestamp: new Date().toISOString() }]);
              setCurrentAssistantMsg('');
              setCurrentToolCalls([]);
              currentToolCallsRef.current = [];
              setConnectionState('error');
              break;
          }
        }
        // Stream completed successfully — no retry needed.
        break;
      } catch (e) {
        // Phase 5.1 (v0.36): abort errors are expected.
        if (e instanceof DOMException && e.name === 'AbortError') break;
        // Phase 5.4 (v0.36): retry if no events were received yet.
        if (!gotFirstChunk && attempt < MAX_RETRIES) {
          const delay = RETRY_DELAYS[attempt] || 4000;
          setConnectionState('error');
          addToast('info', `Connection lost, retrying in ${delay / 1000}s...`);
          await new Promise((r) => setTimeout(r, delay));
          attempt++;
          continue;
        }
        // Non-retryable or events already delivered — show error.
        const errMsg = e instanceof Error ? e.message : 'Unknown error';
        addToast('error', `Chat error: ${errMsg}`);
        setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${errMsg}`, timestamp: new Date().toISOString() }]);
        setCurrentAssistantMsg('');
        setCurrentToolCalls([]);
        currentToolCallsRef.current = [];
        setConnectionState('error');
        break;
      }
    }
    setLoading(false);
    abortControllerRef.current = null;
    setAttachments([]); // v0.40: clear attachments after send
  }, [input, loading, addToast, currentWikiId, currentSessionId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    if (e.key === 'Escape') setInput('');
  };

  const formatTime = (iso: string) => {
    try { return new Date(iso).toLocaleTimeString(); } catch { return ''; }
  };

  return (
    <div className="flex flex-col h-full">
      {pendingConfirmation && (
        <ConfirmationModal
          confirmationId={pendingConfirmation.confirmationId}
          tool={pendingConfirmation.tool}
          args={pendingConfirmation.args}
          impact={pendingConfirmation.impact}
          group={pendingConfirmation.group}
          onApprove={handleApproveConfirmation}
          onReject={handleRejectConfirmation}
          loading={confirmingLoading}
        />
      )}

      {/* v0.40: Settings dialog for custom system prompt */}
      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowSettings(false)}>
          <div className="bg-card border border-border rounded-lg shadow-elevated w-full max-w-2xl max-h-[80vh] flex flex-col m-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-4 border-b border-border flex items-center justify-between">
              <h2 className="text-base font-semibold">Custom system prompt</h2>
              <button
                onClick={() => setShowSettings(false)}
                className="p-1 rounded hover:bg-muted transition-colors"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto">
              <p className="text-xs text-muted-foreground mb-2">
                This prompt is added to every chat turn. Use it to set persona, language, tone, or domain-specific instructions.
              </p>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="E.g. Always respond in Chinese. Be concise. Use markdown."
                className="w-full h-64 px-3 py-2 text-sm font-mono bg-muted/40 border border-border rounded-md outline-none focus:border-primary/50 resize-none text-foreground placeholder:text-muted-foreground"
              />
            </div>
            <div className="p-4 border-t border-border flex gap-3 justify-end">
              <button
                onClick={() => setShowSettings(false)}
                className="px-3 py-1.5 text-sm rounded-md text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                onClick={saveSystemPrompt}
                className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:brightness-110"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {showSidebar && (
          <SessionSidebar
            currentSessionId={currentSessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            refreshKey={sidebarRefreshKey}
          />
        )}

        <div className="flex flex-col flex-1 min-w-0">
          {/* Top bar — glass */}
          <div className="px-4 py-2.5 border-b border-border/50 flex items-center justify-between gap-3 glass">
            <div className="flex items-center gap-3 min-w-0">
              <h2 className="text-sm font-semibold text-foreground shrink-0">Chat</h2>
              {modelName && (
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-primary/10 border border-primary/20 text-xs text-foreground/80">
                  <Cpu className="w-3 h-3 text-primary" />
                  <span className="font-mono text-[11px] truncate max-w-[120px]" title={modelName}>{modelName}</span>
                </div>
              )}
              <div className={cn('flex items-center gap-1.5 text-xs', STATE_TONE[connectionState])} title={`Connection: ${STATE_LABEL[connectionState]}`}>
                <span className={cn(
                  'w-1.5 h-1.5 rounded-full',
                  STATE_DOT[connectionState],
                  connectionState === 'live' && 'status-dot--live',
                )} />
                <Wifi className="w-3 h-3" />
                <span className="hidden sm:inline">{STATE_LABEL[connectionState]}</span>
              </div>
              {currentSessionId && (
                <span className="text-xs text-muted-foreground font-mono hidden md:inline">#{currentSessionId.slice(0, 8)}</span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {tokenEstimate > 0 && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground px-2 py-0.5 rounded-md bg-white/[0.04]" title="Approximate token usage">
                  <Coins className="w-3 h-3" />
                  <span className="font-mono tabular-nums">{tokenEstimate < 1000 ? tokenEstimate : `${(tokenEstimate / 1000).toFixed(1)}k`}</span>
                </div>
              )}
              <button
                onClick={() => setShowSidebar(!showSidebar)}
                className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-white/[0.06] transition-colors hidden md:inline-flex"
                title={showSidebar ? 'Hide session sidebar' : 'Show session sidebar'}
                aria-label="Toggle session sidebar"
              >
                {showSidebar ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
              </button>
              <button
                onClick={() => setShowRail(!showRail)}
                className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-white/[0.06] transition-colors hidden lg:inline-flex"
                title={showRail ? 'Hide tools rail' : 'Show tools rail'}
                aria-label="Toggle tools rail"
              >
                {showRail ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
              </button>
              {/* v0.40: settings button */}
              <button
                onClick={openSettings}
                className="text-muted-foreground hover:text-foreground p-1.5 rounded-md hover:bg-white/[0.06] transition-colors"
                title="Settings (system prompt)"
                aria-label="Open settings"
              >
                <Settings className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
              {messages.length === 1 && messages[0].role === 'assistant' && !loading && (
                <WelcomeScreen
                  onPromptClick={(p) => setInput(p)}
                  wikiName={currentWikiId || undefined}
                />
              )}

              {messages.map((msg, i) => (
                <div key={i} className="animate-message-in">
                  {editingMessageId === msg.messageId ? (
                    <div className="flex justify-end gap-2.5">
                      <div className="max-w-[80%] w-full flex flex-col items-end gap-1">
                        <textarea
                          value={editingContent}
                          onChange={(e) => setEditingContent(e.target.value)}
                          className="w-full rounded-2xl rounded-tr-md px-4 py-2.5 text-sm bg-white/[0.06] border border-primary/30 outline-none resize-none text-foreground"
                          rows={Math.max(2, editingContent.split('\n').length)}
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSaveEdit(); }
                            if (e.key === 'Escape') { e.preventDefault(); handleCancelEdit(); }
                          }}
                        />
                        <div className="flex gap-2 mt-1">
                          <button
                            onClick={handleSaveEdit}
                            className="px-3 py-1 text-xs rounded-md bg-primary text-primary-foreground hover:brightness-110"
                          >
                            Save
                          </button>
                          <button
                            onClick={handleCancelEdit}
                            className="px-3 py-1 text-xs rounded-md text-muted-foreground hover:text-foreground"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <MessageBubble
                      role={msg.role}
                      content={msg.content}
                      thinking={msg.thinking}
                      timestamp={formatTime(msg.timestamp)}
                      // Phase 5.3 (v0.36): regenerate is available on
                      // ANY assistant message (not just the last).
                      // Truncates the history at the preceding user
                      // message and puts it in the input for re-send.
                      onRegenerate={msg.role === 'assistant' ? () => {
                        // Find the user message before this assistant message.
                        let precedingUserIdx = -1;
                        for (let j = i - 1; j >= 0; j--) {
                          if (messages[j].role === 'user') {
                            precedingUserIdx = j;
                            break;
                          }
                        }
                        if (precedingUserIdx >= 0) {
                          setInput(messages[precedingUserIdx].content);
                          setMessages((prev) => prev.slice(0, precedingUserIdx));
                        }
                      } : undefined}
                      onQuote={msg.role === 'assistant' ? (text) => {
                        setInput((prev) => prev ? `${prev}\n\n> ${text.split('\n').join('\n> ')}` : `> ${text.split('\n').join('\n> ')}`);
                      } : undefined}
                    />
                  )}
                  {/* v0.40: Action buttons row for each message */}
                  {msg.messageId && editingMessageId !== msg.messageId && (
                    <div className="flex items-center gap-1 px-9 mt-1 opacity-0 group-hover:animate-message-in hover:opacity-100 transition-opacity">
                      {msg.role === 'user' && (
                        <>
                          <button
                            onClick={() => handleStartEdit(msg)}
                            className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground rounded transition-colors"
                            title="Edit message"
                          >
                            <Pencil className="w-3 h-3" /> Edit
                          </button>
                          <button
                            onClick={() => msg.messageId && handleRevert(msg.messageId)}
                            className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground rounded transition-colors"
                            title="Revert to here"
                          >
                            <History className="w-3 h-3" /> Revert
                          </button>
                          <button
                            onClick={() => msg.messageId && handleFork(msg.messageId, msg.content)}
                            className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground rounded transition-colors"
                            title="Fork from here"
                          >
                            <GitBranch className="w-3 h-3" /> Fork
                          </button>
                        </>
                      )}
                      {msg.role === 'assistant' && (
                        <>
                          <button
                            onClick={() => msg.messageId && handleFeedback(msg.messageId, 'up')}
                            className={cn(
                              'p-0.5 rounded transition-colors',
                              feedback[msg.messageId] === 'up' ? 'text-success' : 'text-muted-foreground hover:text-foreground'
                            )}
                            title="Good response"
                          >
                            <ThumbsUp className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => msg.messageId && handleFeedback(msg.messageId, 'down')}
                            className={cn(
                              'p-0.5 rounded transition-colors',
                              feedback[msg.messageId] === 'down' ? 'text-destructive' : 'text-muted-foreground hover:text-foreground'
                            )}
                            title="Bad response"
                          >
                            <ThumbsDown className="w-3 h-3" />
                          </button>
                          {msg.tokensOutput && (
                            <span className="text-[10px] text-muted-foreground/70 ml-1">
                              {msg.tokensOutput} tokens
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="mt-2 space-y-2 ml-9">
                      {msg.toolCalls.map((tc, j) => (
                        <ToolCard key={j} tool={tc.tool} args={tc.args} status={tc.status} result={tc.result} error={tc.error} startedAt={tc.startedAt} finishedAt={tc.finishedAt} duration_ms={tc.duration_ms} />
                      ))}
                    </div>
                  )}
                </div>
              ))}

              {loading && currentAssistantMsg && (
                <div className="animate-message-in">
                  <MessageBubble role="assistant" content={currentAssistantMsg} thinking={currentThinking || undefined} streaming />
                </div>
              )}

              {loading && !currentAssistantMsg && currentThinking && (
                <div className="animate-message-in">
                  <MessageBubble role="assistant" content="" thinking={currentThinking} streaming />
                </div>
              )}

              {loading && currentToolCalls.length > 0 && (
                <div className="space-y-2 ml-9">
                  {currentToolCalls.map((tc, j) => (
                    <ToolCard key={j} tool={tc.tool} args={tc.args} status={tc.status} result={tc.result} error={tc.error} />
                  ))}
                </div>
              )}

              {loading && !currentAssistantMsg && currentToolCalls.length === 0 && (
                <div className="flex justify-start ml-9">
                  <div className="flex items-center gap-2 text-muted-foreground text-xs px-3 py-2 rounded-full glass-strong">
                    <span className="thinking-dots"><span /><span /><span /></span>
                    <span>Thinking…</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input area — bottom centered */}
          <div className="px-4 pb-5 pt-2">
            <form
              onSubmit={(e) => { e.preventDefault(); sendMessage(); }}
              className="max-w-3xl mx-auto"
            >
              {/* v0.40: attachment previews */}
              {attachments.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-2">
                  {attachments.map((att, idx) => (
                    <div key={idx} className="relative group/att flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted/60 border border-border/40 text-xs">
                      {att.preview ? (
                        <img src={`data:${att.mime};base64,${att.data}`} alt={att.name} className="w-8 h-8 object-cover rounded" />
                      ) : (
                        <Paperclip className="w-4 h-4 text-muted-foreground" />
                      )}
                      <span className="truncate max-w-[120px]">{att.name}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveAttachment(idx)}
                        className="p-0.5 rounded hover:bg-muted-foreground/20 transition-colors"
                        aria-label="Remove attachment"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="glow-border relative flex items-end gap-2 p-2 rounded-2xl glass-strong shadow-elevated">
                {/* v0.40: file upload button */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept="image/*,.pdf,.txt,.md,.json,.py,.js,.ts,.tsx"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={loading}
                  className="shrink-0 p-2 text-muted-foreground hover:text-foreground disabled:opacity-30 rounded-md transition-colors"
                  title="Attach files"
                  aria-label="Attach files"
                >
                  <Paperclip className="w-4 h-4" />
                </button>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Message llmwikify…"
                  rows={1}
                  className={cn(
                    'flex-1 resize-none bg-transparent border-0 outline-none',
                    'px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground',
                    'max-h-32 min-h-[40px] leading-relaxed',
                  )}
                  style={{
                    height: 'auto',
                    minHeight: '40px',
                  }}
                  onInput={(e) => {
                    const target = e.target as HTMLTextAreaElement;
                    target.style.height = 'auto';
                    target.style.height = `${Math.min(target.scrollHeight, 128)}px`;
                  }}
                />
                {loading ? (
                  <button
                    type="button"
                    onClick={handleAbort}
                    className={cn(
                      'shrink-0 w-9 h-9 rounded-xl flex items-center justify-center',
                      'bg-destructive text-destructive-foreground',
                      'transition-all duration-200 shadow-soft',
                      'hover:brightness-110 hover:shadow-glow',
                    )}
                    aria-label="Stop response"
                    title="Stop response"
                  >
                    <StopCircle className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className={cn(
                      'shrink-0 w-9 h-9 rounded-xl flex items-center justify-center',
                      'bg-gradient-to-br from-primary to-accent text-primary-foreground',
                      'transition-all duration-200 shadow-soft',
                      'hover:brightness-110 hover:shadow-glow',
                      'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:brightness-100 disabled:hover:shadow-soft',
                    )}
                    aria-label="Send message"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M12 19V5M5 12l7-7 7 7" />
                    </svg>
                  </button>
                )}
              </div>
              <div className="mt-1.5 text-center text-[10px] text-muted-foreground/70">
                Press <kbd className="px-1 py-0.5 rounded bg-white/[0.06] text-foreground/80 font-mono text-[9px]">Enter</kbd> to send · <kbd className="px-1 py-0.5 rounded bg-white/[0.06] text-foreground/80 font-mono text-[9px]">Shift+Enter</kbd> for newline
              </div>
            </form>
          </div>
        </div>

        {showRail && (
          <ToolsRail
            messages={messages}
            currentToolCalls={currentToolCalls}
            modelName={modelName}
            connectionState={connectionState}
            sessionId={currentSessionId}
            tokenEstimate={tokenEstimate}
          />
        )}
      </div>
    </div>
  );
}

interface WelcomeScreenProps {
  onPromptClick: (prompt: string) => void;
  wikiName?: string;
}

const STARTER_PROMPTS = [
  {
    icon: '🔍',
    title: 'Search the wiki',
    description: 'Find pages by topic, tag, or content',
    prompt: 'Search my wiki for pages about ',
  },
  {
    icon: '📝',
    title: 'Summarize a page',
    description: 'Get a quick overview of any page',
    prompt: 'Summarize the page ',
  },
  {
    icon: '🧠',
    title: 'Research a topic',
    description: 'Multi-source deep research with citations',
    prompt: 'Research ',
  },
  {
    icon: '✨',
    title: 'Write new content',
    description: 'Create a new wiki page from scratch',
    prompt: 'Help me write a new wiki page about ',
  },
];

function WelcomeScreen({ onPromptClick }: WelcomeScreenProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] py-8 animate-slide-up">
      <div className="relative mb-6">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-accent flex items-center justify-center shadow-glow">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-primary-foreground"
          >
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <div className="absolute -inset-2 rounded-3xl bg-gradient-to-br from-primary/30 to-accent/0 blur-2xl -z-10" />
      </div>
      <h1 className="text-2xl font-semibold text-foreground tracking-tight mb-1">
        How can I help you today?
      </h1>
      <p className="text-sm text-muted-foreground mb-8">
        Start a conversation or pick a quick action below.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-2xl">
        {STARTER_PROMPTS.map((p, i) => (
          <button
            key={i}
            onClick={() => onPromptClick(p.prompt)}
            className={cn(
              'group text-left p-4 rounded-xl glass',
              'hover:bg-white/[0.04] hover:border-primary/30 hover:shadow-soft',
              'transition-all duration-200',
            )}
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className="text-xl mb-2">{p.icon}</div>
            <div className="text-sm font-medium text-foreground mb-0.5 group-hover:text-primary transition-colors">
              {p.title}
            </div>
            <div className="text-xs text-muted-foreground">
              {p.description}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// v0.40: helper to convert File to base64
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip "data:xxx;base64," prefix
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
