import { useState, useRef, useEffect, useCallback } from 'react';
import { Cpu, Wifi, Coins, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, StopCircle } from 'lucide-react';
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
}

interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  status: 'pending' | 'streaming' | 'done' | 'error';
  startedAt?: number;
  finishedAt?: number;
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
                const next = [...prev, { tool: event.tool, args: event.args, status: 'streaming' as const, startedAt: Date.now() }];
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_end': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, result: event.result, status: 'done' as const, finishedAt: Date.now() } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'confirmation_required':
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, status: 'done' as const, finishedAt: Date.now() } : tc);
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
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, error: event.error, status: 'error' as const, finishedAt: Date.now() } : tc);
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
        const reader = chatStream(input, currentSessionId || undefined, currentWikiId || undefined, ac.signal).getReader();

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
                const next = [...prev, { tool: event.tool, args: event.args, status: 'streaming' as const, startedAt: Date.now() }];
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_end': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, result: event.result, status: 'done' as const, finishedAt: Date.now() } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'tool_call_error': {
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, error: event.error, status: 'error' as const, finishedAt: Date.now() } : tc);
                currentToolCallsRef.current = next;
                return next;
              });
              break;
            }
            case 'confirmation_required':
              setCurrentToolCalls((prev) => {
                const next = prev.map((tc) => tc.tool === event.tool ? { ...tc, status: 'done' as const, finishedAt: Date.now() } : tc);
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
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="mt-2 space-y-2 ml-9">
                      {msg.toolCalls.map((tc, j) => (
                        <ToolCard key={j} tool={tc.tool} args={tc.args} status={tc.status} result={tc.result} error={tc.error} startedAt={tc.startedAt} finishedAt={tc.finishedAt} />
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
              <div className="glow-border relative flex items-end gap-2 p-2 rounded-2xl glass-strong shadow-elevated">
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
                    onClick={handleStop}
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
