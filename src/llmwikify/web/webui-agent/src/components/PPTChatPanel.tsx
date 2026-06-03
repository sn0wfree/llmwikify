/**
 * PPTChatPanel - Interactive slide editing via chat
 *
 * Features:
 * - Chat with LLM to modify slides
 * - Quick action buttons (delete, move, duplicate, theme, undo)
 * - Slide context indicator
 * - Streaming response display
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Trash2, Copy, ArrowUpDown, Palette, Undo2,
  Send, X, ChevronDown, Loader2, MessageSquare,
} from 'lucide-react';
import { MessageBubble } from './ui/MessageBubble';
import { Presentation, SlideContent } from '../lib/ppt-themes';
import { pptChatStream, PPTChatStreamEvent, getPptChatMessages, getPptChatSessionByTask } from '../lib/ppt-api';

interface PPTChatPanelProps {
  taskId: string;
  presentation: Presentation;
  currentSlideIndex: number;
  onPresentationUpdate: (presentation: Presentation) => void;
  onSlideSelect: (index: number) => void;
  isOpen: boolean;
  onToggle: () => void;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  timestamp: string;
}

// ─── Quick action definitions ─────────────────────────────

interface QuickAction {
  icon: React.ReactNode;
  label: string;
  getMessage: (slideIndex: number, slideCount: number) => string;
}

const QUICK_ACTIONS: QuickAction[] = [
  {
    icon: <Trash2 size={14} />,
    label: '删除',
    getMessage: (i) => `删除第${i + 1}页`,
  },
  {
    icon: <Copy size={14} />,
    label: '复制',
    getMessage: (i) => `复制第${i + 1}页`,
  },
  {
    icon: <ArrowUpDown size={14} />,
    label: '前移',
    getMessage: (i) => i > 0 ? `移动第${i + 1}页到第${i}页` : '已在第一页',
  },
  {
    icon: <Undo2 size={14} />,
    label: '撤销',
    getMessage: () => '撤销',
  },
];

// ─── Theme options for quick switch ───────────────────────

const THEME_OPTIONS = [
  { id: 'minimal-white', label: '极简白' },
  { id: 'dracula', label: 'Dracula' },
  { id: 'corporate-clean', label: '商务' },
  { id: 'cyberpunk-neon', label: '赛博' },
  { id: 'xiaohongshu-white', label: '小红书' },
  { id: 'bauhaus', label: '包豪斯' },
];

// ─── Chat suggestions ─────────────────────────────────────

const SUGGESTIONS = [
  '把这页改成饼图',
  '加一页总结',
  '换一个深色主题',
  '把标题改短一点',
  '这页用什么图表好？',
  '加一页SWOT分析',
];

// ─── Main Component ───────────────────────────────────────

export function PPTChatPanel({
  taskId,
  presentation,
  currentSlideIndex,
  onPresentationUpdate,
  onSlideSelect,
  isOpen,
  onToggle,
}: PPTChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentThinking, setCurrentThinking] = useState('');
  const [currentDelta, setCurrentDelta] = useState('');
  const [showThemeMenu, setShowThemeMenu] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load chat history on mount (for offline recovery / page refresh)
  useEffect(() => {
    if (!taskId || !isOpen) return;

    const loadHistory = async () => {
      const storedSessionId = localStorage.getItem(`ppt-chat-session-${taskId}`);
      if (!storedSessionId) return;

      try {
        const { messages: history } = await getPptChatMessages(storedSessionId);
        if (history.length > 0) {
          setSessionId(storedSessionId);
          setMessages(history.map(m => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            timestamp: m.created_at,
          })));
        }
      } catch {
        // Session invalid (server restart, DB cleanup, etc.)
        localStorage.removeItem(`ppt-chat-session-${taskId}`);
      }
    };

    loadHistory();
  }, [taskId, isOpen]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(scrollToBottom, [messages, currentDelta]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  const sendMessage = useCallback(async (text?: string) => {
    const msg = text || input.trim();
    if (!msg || isLoading) return;

    const userMessage: ChatMessage = {
      role: 'user',
      content: msg,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    if (!text) setInput('');
    setIsLoading(true);
    setCurrentThinking('');
    setCurrentDelta('');

    try {
      const reader = await pptChatStream({
        message: msg,
        task_id: taskId,
        current_slide_index: currentSlideIndex,
        session_id: sessionId || undefined,
      });

      abortRef.current = new AbortController();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const data = JSON.parse(line.slice(5).trim());
              handleStreamEvent(data);
            } catch {
              // Skip unparseable events
            }
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `Error: ${err}`, timestamp: new Date().toISOString() },
        ]);
      }
    } finally {
      setIsLoading(false);
      setCurrentThinking('');
      setCurrentDelta('');
      abortRef.current = null;
    }
  }, [input, isLoading, taskId, currentSlideIndex, sessionId]);

  const handleStreamEvent = (event: Record<string, unknown>) => {
    switch (event.type) {
      case 'session_created':
        setSessionId(event.session_id as string);
        // Persist session for offline recovery
        if (taskId) {
          localStorage.setItem(`ppt-chat-session-${taskId}`, event.session_id as string);
        }
        break;
      case 'thinking':
        setCurrentThinking((prev) => prev + (event.content as string));
        break;
      case 'message_delta':
        setCurrentDelta((prev) => prev + (event.content as string));
        break;
      case 'tool_start':
        setCurrentDelta((prev) => prev + `\n[${event.tool}]...`);
        break;
      case 'tool_end':
        setCurrentDelta((prev) => prev.replace(/\[.*\]\.\.\./, ''));
        break;
      case 'done':
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: (event.message as string) || 'Done',
            thinking: currentThinking || undefined,
            timestamp: new Date().toISOString(),
          },
        ]);
        if (event.updated_presentation) {
          onPresentationUpdate(event.updated_presentation as Presentation);
        }
        break;
      case 'error':
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `Error: ${event.error}`,
            timestamp: new Date().toISOString(),
          },
        ]);
        break;
    }
  };

  const currentSlide = presentation.slides[currentSlideIndex];

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="fixed bottom-6 right-6 bg-blue-600 text-white rounded-full p-4 shadow-lg hover:bg-blue-700 transition-colors z-50"
        title="PPT Chat"
      >
        <MessageSquare size={24} />
      </button>
    );
  }

  return (
    <div className="w-96 border-l border-slate-700 bg-slate-900 flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-slate-700 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare size={16} className="text-blue-400" />
          <span className="text-sm font-medium text-slate-200">PPT Chat</span>
          <span className="text-xs text-slate-500">
            {currentSlideIndex + 1}/{presentation.slides.length}
          </span>
        </div>
        <button onClick={onToggle} className="text-slate-400 hover:text-slate-200">
          <X size={16} />
        </button>
      </div>

      {/* Quick Actions Bar */}
      <div className="px-3 py-2 border-b border-slate-700 flex items-center gap-1 shrink-0">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            onClick={() => sendMessage(action.getMessage(currentSlideIndex, presentation.slides.length))}
            disabled={isLoading}
            className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 bg-slate-800 rounded hover:bg-slate-700 hover:text-slate-200 disabled:opacity-50 transition-colors"
            title={action.label}
          >
            {action.icon}
            {action.label}
          </button>
        ))}

        {/* Theme dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowThemeMenu(!showThemeMenu)}
            disabled={isLoading}
            className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 bg-slate-800 rounded hover:bg-slate-700 hover:text-slate-200 disabled:opacity-50 transition-colors"
          >
            <Palette size={14} />
            主题
            <ChevronDown size={12} />
          </button>
          {showThemeMenu && (
            <div className="absolute top-full left-0 mt-1 bg-slate-800 border border-slate-600 rounded-lg shadow-xl z-10 py-1 w-32">
              {THEME_OPTIONS.map((theme) => (
                <button
                  key={theme.id}
                  onClick={() => {
                    sendMessage(`切换主题为 ${theme.id}`);
                    setShowThemeMenu(false);
                  }}
                  className="w-full text-left px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
                >
                  {theme.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Current slide context */}
      {currentSlide && (
        <div className="px-3 py-2 border-b border-slate-700 bg-slate-800/50 shrink-0">
          <div className="text-xs text-slate-500">当前幻灯片</div>
          <div className="text-sm text-slate-300 truncate">{currentSlide.title}</div>
          <div className="text-xs text-slate-600">{currentSlide.layout}</div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="text-center text-slate-500 text-sm mt-8">
            <p className="mb-3">用自然语言修改幻灯片</p>
            <div className="flex flex-wrap gap-1 justify-center">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendMessage(s)}
                  className="text-xs bg-slate-800 text-slate-400 px-2 py-1 rounded hover:bg-slate-700 hover:text-slate-300 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            role={msg.role}
            content={msg.content}
            thinking={msg.thinking}
            timestamp={msg.timestamp}
          />
        ))}

        {/* Streaming indicators */}
        {isLoading && currentThinking && (
          <div className="text-xs text-slate-500 italic pl-2 border-l-2 border-slate-700">
            {currentThinking.slice(-200)}
          </div>
        )}
        {isLoading && currentDelta && (
          <MessageBubble role="assistant" content={currentDelta} streaming />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-slate-700 shrink-0">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder="修改幻灯片..."
            className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 transition-colors"
            disabled={isLoading}
          />
          <button
            onClick={() => sendMessage()}
            disabled={isLoading || !input.trim()}
            className="bg-blue-600 text-white rounded-lg px-3 py-2 hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
      </div>
    </div>
  );
}
