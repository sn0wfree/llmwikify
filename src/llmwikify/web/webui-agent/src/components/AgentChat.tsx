import { useState, useRef, useEffect, useCallback } from 'react';
import { Cpu, Wifi, Coins, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { chatStream, ChatStreamEvent, api } from '../api';
import { useToast } from './Toast';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { Button } from './ui/Button';
import { MessageBubble } from './ui/MessageBubble';
import { ToolCard } from './ui/ToolCard';
import { Input } from './ui/Input';
import { Panel } from './ui/Panel';
import { SessionSidebar } from './SessionSidebar';
import { ToolsRail } from './ToolsRail';
import { ConfirmationModal } from './ConfirmationModal';

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
}

type ConnectionState = 'idle' | 'live' | 'error';

const STATE_TONE: Record<ConnectionState, string> = {
  idle: 'text-text-secondary',
  live: 'text-[var(--success)]',
  error: 'text-[var(--error)]',
};

const STATE_DOT: Record<ConnectionState, string> = {
  idle: 'bg-text-secondary/40',
  live: 'bg-[var(--success)]',
  error: 'bg-[var(--error)]',
};

const STATE_LABEL: Record<ConnectionState, string> = {
  idle: 'idle',
  live: 'live',
  error: 'error',
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

export function AgentChat({ onExportToPpt }: { onExportToPpt?: (type: 'research' | 'chat', id: string) => void }) {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: "Hello! I'm your wiki assistant. How can I help?", timestamp: new Date().toISOString() },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentAssistantMsg, setCurrentAssistantMsg] = useState('');
  const [currentThinking, setCurrentThinking] = useState('');
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCall[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showRail, setShowRail] = useState(true);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmingLoading, setConfirmingLoading] = useState(false);
  const [modelName, setModelName] = useState<string>('');
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle');
  const [tokenEstimate, setTokenEstimate] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { addToast } = useToast();
  const { currentWikiId } = useAgentWikiStore();

  useEffect(() => {
    let mounted = true;
    api.agent
      .getConfig()
      .then((cfg: { model?: string }) => {
        if (mounted && cfg?.model) setModelName(cfg.model);
      })
      .catch(() => {
        /* model fetch is best-effort */
      });
    return () => {
      mounted = false;
    };
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
          toolCalls: m.tool_calls as ToolCall[] | undefined,
        }));
        setMessages(loaded);
      }
    } catch { /* silent */ }
  }, []);

  const handleSelectSession = useCallback(async (sessionId: string) => {
    setCurrentSessionId(sessionId);
    await loadMessages(sessionId);
  }, [loadMessages]);

  const handleNewChat = useCallback(() => {
    setCurrentSessionId(null);
    setMessages([{ role: 'assistant', content: "Hello! I'm your wiki assistant. How can I help?", timestamp: new Date().toISOString() }]);
    setInput('');
  }, []);

  const handleApproveConfirmation = useCallback(async () => {
    if (!pendingConfirmation || !currentSessionId) return;
    setConfirmingLoading(true);
    try {
      setPendingConfirmation(null);
      setLoading(true);
      setCurrentAssistantMsg('');
      setCurrentToolCalls([]);

      const reader = api.confirmations.approveAndContinue(
        pendingConfirmation.confirmationId,
        currentSessionId,
        currentWikiId || undefined
      ).getReader();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const event = value as ChatStreamEvent;
        switch (event.type) {
          case 'message_delta':
            setCurrentAssistantMsg((prev) => prev + event.content);
            break;
          case 'thinking':
            setCurrentThinking((prev) => prev + event.content);
            break;
          case 'tool_call_start':
            setCurrentToolCalls((prev) => [
              ...prev,
              { tool: event.tool, args: event.args, status: 'streaming' },
            ]);
            break;
          case 'tool_call_end':
            setCurrentToolCalls((prev) =>
              prev.map((tc) =>
                tc.tool === event.tool ? { ...tc, result: event.result, status: 'done' } : tc
              )
            );
            break;
          case 'confirmation_required':
            setCurrentToolCalls((prev) =>
              prev.map((tc) =>
                tc.tool === 'confirmation_required' ? { ...tc, status: 'done' } : tc
              )
            );
            setPendingConfirmation({
              confirmationId: event.confirmation_id,
              tool: 'confirmation_required',
              args: {},
              impact: (event.details || {}) as Record<string, unknown>,
              group: undefined,
            });
            break;
          case 'done':
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: event.final_response, thinking: currentThinking || undefined, timestamp: new Date().toISOString(), toolCalls: currentToolCalls },
            ]);
            setCurrentAssistantMsg('');
            setCurrentThinking('');
            setCurrentToolCalls([]);
            break;
          case 'error':
            addToast('error', event.message || 'Confirmation error');
            break;
        }
      }
      addToast('success', 'Action approved and executed');
    } catch (e) {
      addToast('error', `Failed to approve: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setConfirmingLoading(false);
      setLoading(false);
    }
  }, [pendingConfirmation, currentSessionId, currentWikiId, currentToolCalls, addToast]);

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

  const sendMessage = useCallback(async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { role: 'user', content: input, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setCurrentAssistantMsg('');
    setCurrentThinking('');
    setCurrentToolCalls([]);
    setConnectionState('live');
    setTokenEstimate((t) => t + Math.ceil(input.length / 4));

    const reader = chatStream(input, currentSessionId || undefined, currentWikiId || undefined).getReader();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const event = value as ChatStreamEvent;

        switch (event.type) {
          case 'session_created':
            setCurrentSessionId(event.session_id);
            break;

          case 'message_delta':
            setCurrentAssistantMsg((prev) => prev + event.content);
            break;

          case 'thinking':
            setCurrentThinking((prev) => prev + event.content);
            break;

          case 'tool_call_start':
            setCurrentToolCalls((prev) => [
              ...prev,
              { tool: event.tool, args: event.args, status: 'streaming' },
            ]);
            break;

          case 'tool_call_end':
            setCurrentToolCalls((prev) =>
              prev.map((tc) =>
                tc.tool === event.tool ? { ...tc, result: event.result, status: 'done' } : tc
              )
            );
            break;

          case 'tool_call_error':
            setCurrentToolCalls((prev) =>
              prev.map((tc) =>
                tc.tool === event.tool ? { ...tc, error: event.error, status: 'error' } : tc
              )
            );
            break;

          case 'confirmation_required':
            setCurrentToolCalls((prev) =>
              prev.map((tc) =>
                tc.tool === 'confirmation_required' ? { ...tc, status: 'done' } : tc
              )
            );
            setPendingConfirmation({
              confirmationId: event.confirmation_id,
              tool: 'confirmation_required',
              args: {},
              impact: (event.details || {}) as Record<string, unknown>,
              group: undefined,
            });
            break;

          case 'done':
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: event.final_response, thinking: currentThinking || undefined, timestamp: new Date().toISOString(), toolCalls: currentToolCalls },
            ]);
            setCurrentAssistantMsg('');
            setCurrentThinking('');
            setCurrentToolCalls([]);
            setTokenEstimate((t) => t + Math.ceil((event.final_response.length + currentThinking.length) / 4));
            setConnectionState('idle');
            break;
        }
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : 'Unknown error';
      addToast('error', `Chat error: ${errMsg}`);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${errMsg}`, timestamp: new Date().toISOString() },
      ]);
      setCurrentAssistantMsg('');
      setCurrentToolCalls([]);
      setConnectionState('error');
    } finally {
      setLoading(false);
    }
  }, [input, loading, addToast, currentToolCalls, currentWikiId, currentSessionId]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    if (e.key === 'Escape') {
      setInput('');
    }
  };

  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString();
    } catch {
      return '';
    }
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
          />
        )}

        <div className="flex flex-col flex-1 min-w-0">
          <Panel border="top">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <h2 className="text-sm font-semibold text-[var(--accent)] shrink-0">Agent Chat</h2>
                {modelName && (
                  <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-[var(--bg-tertiary)]/40 border border-[var(--border)]/40 text-xs text-[var(--text-secondary)]">
                    <Cpu className="w-3 h-3" />
                    <span className="font-mono text-[11px] truncate max-w-[120px]" title={modelName}>
                      {modelName}
                    </span>
                  </div>
                )}
                <div
                  className={`flex items-center gap-1.5 text-xs ${STATE_TONE[connectionState]}`}
                  title={`Connection: ${STATE_LABEL[connectionState]}`}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${STATE_DOT[connectionState]}`} />
                  <Wifi className="w-3 h-3" />
                  <span className="hidden sm:inline">{STATE_LABEL[connectionState]}</span>
                </div>
                {currentSessionId && (
                  <span className="text-xs text-[var(--text-secondary)] font-mono hidden md:inline">
                    #{currentSessionId.slice(0, 8)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {tokenEstimate > 0 && (
                  <div
                    className="flex items-center gap-1 text-xs text-[var(--text-secondary)]"
                    title="Approximate token usage (chars/4)"
                  >
                    <Coins className="w-3 h-3" />
                    <span className="font-mono">
                      {tokenEstimate < 1000
                        ? tokenEstimate
                        : `${(tokenEstimate / 1000).toFixed(1)}k`}
                    </span>
                  </div>
                )}
                {currentSessionId && (
                  <button
                    onClick={() => onExportToPpt?.('chat', currentSessionId)}
                    className="text-xs text-[var(--accent)] hover:underline"
                  >
                    生成 PPT
                  </button>
                )}
                <button
                  onClick={() => setShowSidebar(!showSidebar)}
                  className="text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors p-1 rounded hover:bg-[var(--bg-tertiary)]/40 hidden md:inline-flex"
                  title={showSidebar ? 'Hide session sidebar' : 'Show session sidebar'}
                >
                  {showSidebar ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => setShowRail(!showRail)}
                  className="text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors p-1 rounded hover:bg-[var(--bg-tertiary)]/40 hidden lg:inline-flex"
                  title={showRail ? 'Hide tools rail' : 'Show tools rail'}
                >
                  {showRail ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </Panel>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg, i) => (
              <div key={i}>
                <MessageBubble
                  role={msg.role}
                  content={msg.content}
                  thinking={msg.thinking}
                  timestamp={formatTime(msg.timestamp)}
                />
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {msg.toolCalls.map((tc, j) => (
                      <div key={j} className="max-w-[82%] ml-auto mr-0">
                        <ToolCard tool={tc.tool} args={tc.args} status={tc.status} result={tc.result} error={tc.error} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {loading && currentAssistantMsg && (
              <MessageBubble
                role="assistant"
                content={currentAssistantMsg}
                thinking={currentThinking || undefined}
                streaming
              />
            )}

            {loading && !currentAssistantMsg && currentThinking && (
              <MessageBubble
                role="assistant"
                content=""
                thinking={currentThinking}
                streaming
              />
            )}

            {loading && currentToolCalls.length > 0 && (
              <div className="space-y-2">
                {currentToolCalls.map((tc, j) => (
                  <ToolCard key={j} tool={tc.tool} args={tc.args} status={tc.status} result={tc.result} error={tc.error} />
                ))}
              </div>
            )}

            {loading && !currentAssistantMsg && currentToolCalls.length === 0 && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 text-[var(--text-secondary)]">
                  <span className="text-base">🤖</span>
                  <div className="thinking-dots">
                    <span>·</span><span>·</span><span>·</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <Panel border="top">
            <form onSubmit={(e) => { e.preventDefault(); sendMessage(); }} className="flex gap-2">
              <div className="flex-1">
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask me anything about your wiki..."
                />
              </div>
              <Button type="submit" disabled={loading || !input.trim()}>
                ↑
              </Button>
            </form>
          </Panel>
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