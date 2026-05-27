import { useState, useRef, useEffect, useCallback } from 'react';
import { chatStream, ChatStreamEvent, api } from '../api';
import { useToast } from './Toast';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { Button } from './ui/Button';
import { MessageBubble } from './ui/MessageBubble';
import { ToolCard } from './ui/ToolCard';
import { Input } from './ui/Input';
import { Panel } from './ui/Panel';
import { SessionSidebar } from './SessionSidebar';
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
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(true);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmingLoading, setConfirmingLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { addToast } = useToast();
  const { currentWikiId } = useAgentWikiStore();

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
          <div className="w-48 flex-shrink-0 border-r border-[var(--border)] overflow-y-auto">
            <SessionSidebar
              currentSessionId={currentSessionId}
              onSelectSession={handleSelectSession}
              onNewChat={handleNewChat}
            />
          </div>
        )}

        <div className="flex flex-col flex-1 min-w-0">
          <Panel border="top">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-[var(--accent)]">Agent Chat</h2>
              <div className="flex items-center gap-2">
                {currentSessionId && (
                  <span className="text-xs text-[var(--text-secondary)]">
                    session: {currentSessionId.slice(0, 8)}
                  </span>
                )}
                <button
                  onClick={() => setShowSidebar(!showSidebar)}
                  className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
                >
                  {showSidebar ? '←' : '→'}
                </button>
              </div>
            </div>
          </Panel>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg, i) => (
              <div key={i}>
                <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    thinking={msg.thinking}
                    timestamp={formatTime(msg.timestamp)}
                  />
                </div>
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
              <div className="flex justify-start">
                <MessageBubble
                  role="assistant"
                  content={currentAssistantMsg}
                  thinking={currentThinking || undefined}
                  streaming
                />
              </div>
            )}

            {loading && !currentAssistantMsg && currentThinking && (
              <div className="flex justify-start">
                <MessageBubble
                  role="assistant"
                  content=""
                  thinking={currentThinking}
                  streaming
                />
              </div>
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
      </div>
    </div>
  );
}