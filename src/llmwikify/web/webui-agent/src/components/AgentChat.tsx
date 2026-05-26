import { useState, useRef, useEffect, useCallback } from 'react';
import { chatStream, ChatStreamEvent } from '../api';
import { useToast } from './Toast';

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

    const reader = chatStream(input).getReader();

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
  }, [input, loading, addToast, currentToolCalls]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
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
      <div className="p-3 border-b border-slate-700 bg-slate-800">
        <h2 className="text-sm font-semibold text-blue-400">Agent Chat</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i}>
            <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-200'
                }`}
              >
                <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
                <div className={`text-xs mt-1 ${msg.role === 'user' ? 'text-blue-200' : 'text-slate-500'}`}>
                  {formatTime(msg.timestamp)}
                </div>
              </div>
            </div>
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className="mt-2 space-y-2">
                {msg.toolCalls.map((tc, j) => (
                  <div key={j} className="max-w-[80%] ml-auto mr-0" style={{ maxWidth: '80%' }}>
                    <ToolCallCard toolCall={tc} />
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {loading && currentAssistantMsg && (
          <div className="flex justify-start">
            <div className="bg-slate-700 rounded-lg px-4 py-2 text-sm text-slate-200">
              <pre className="whitespace-pre-wrap font-sans">{currentAssistantMsg}</pre>
            </div>
          </div>
        )}

        {loading && currentToolCalls.length > 0 && (
          <div className="space-y-2">
            {currentToolCalls.map((tc, j) => (
              <ToolCallCard key={j} toolCall={tc} />
            ))}
          </div>
        )}

        {loading && !currentAssistantMsg && currentToolCalls.length === 0 && (
          <div className="flex justify-start">
            <div className="bg-slate-700 rounded-lg px-4 py-2 text-sm text-slate-400">
              Thinking...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t border-slate-700 bg-slate-800">
        <form onSubmit={(e) => { e.preventDefault(); sendMessage(); }} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask me anything about your wiki..."
            className="flex-1 bg-slate-900 border border-slate-600 rounded px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-sm text-white"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}

function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  const statusColors: Record<ToolCall['status'], string> = {
    pending: 'border-yellow-500',
    done: 'border-green-500',
    error: 'border-red-500',
  };

  return (
    <div className={`bg-slate-800 rounded border-l-4 ${statusColors[toolCall.status]} p-3`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-sm font-medium text-blue-400">{toolCall.tool}</span>
        {toolCall.status === 'pending' && (
          <span className="text-xs text-yellow-400 animate-pulse">running</span>
        )}
        {toolCall.status === 'done' && (
          <span className="text-xs text-green-400">done</span>
        )}
        {toolCall.status === 'error' && (
          <span className="text-xs text-red-400">error</span>
        )}
      </div>
      <div className="text-xs text-slate-500 font-mono">
        {JSON.stringify(toolCall.args, null, 0)}
      </div>
    </div>
  );
}