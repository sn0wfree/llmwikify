import { useState, useRef, useEffect, useCallback } from 'react';
import { chatStream, ChatStreamEvent } from '../api';
import { useToast } from './Toast';
import { useAgentWikiStore } from '../stores/agentWikiStore';
import { Button } from './ui/Button';
import { MessageBubble } from './ui/MessageBubble';
import { ToolCard } from './ui/ToolCard';
import { Input } from './ui/Input';
import { Panel } from './ui/Panel';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
}

interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: 'pending' | 'done' | 'error';
}

export function AgentChat() {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: "Hello! I'm your wiki assistant. How can I help?", timestamp: new Date().toISOString() },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentAssistantMsg, setCurrentAssistantMsg] = useState('');
  const [currentToolCalls, setCurrentToolCalls] = useState<ToolCall[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { addToast } = useToast();
  const { currentWikiId } = useAgentWikiStore();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentAssistantMsg]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { role: 'user', content: input, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setCurrentAssistantMsg('');
    setCurrentToolCalls([]);

    const reader = chatStream(input, undefined, currentWikiId || undefined).getReader();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const event = value as ChatStreamEvent;

        switch (event.type) {
          case 'message_delta':
            setCurrentAssistantMsg((prev) => prev + event.content);
            break;

          case 'tool_call_start':
            setCurrentToolCalls((prev) => [
              ...prev,
              { tool: event.tool, args: event.args, status: 'pending' },
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
                tc.tool === event.tool ? { ...tc, result: event.error, status: 'error' } : tc
              )
            );
            break;

          case 'confirmation_required':
            setCurrentToolCalls((prev) => [
              ...prev,
              {
                tool: 'confirmation_required',
                args: { confirmation_id: event.confirmation_id },
                result: event.details,
                status: 'done',
              },
            ]);
            break;

          case 'done':
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: event.final_response, timestamp: new Date().toISOString(), toolCalls: currentToolCalls },
            ]);
            setCurrentAssistantMsg('');
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
  }, [input, loading, addToast, currentToolCalls, currentWikiId]);

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
    <div className="flex flex-col h-full max-w-[48rem] mx-auto w-full">
      <Panel border="top">
        <h2 className="text-sm font-semibold text-[var(--accent)]">Agent Chat</h2>
      </Panel>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div key={i}>
            <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <MessageBubble
                role={msg.role}
                content={msg.content}
                timestamp={formatTime(msg.timestamp)}
              />
            </div>
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className="mt-2 space-y-2">
                {msg.toolCalls.map((tc, j) => (
                  <div key={j} className="max-w-[82%] ml-auto mr-0">
                    <ToolCard tool={tc.tool} args={tc.args} status={tc.status} />
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
              streaming
            />
          </div>
        )}

        {loading && currentToolCalls.length > 0 && (
          <div className="space-y-2">
            {currentToolCalls.map((tc, j) => (
              <ToolCard key={j} tool={tc.tool} args={tc.args} status={tc.status} />
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
  );
}