/**
 * PPT Generator - Main Component
 * Handles the complete workflow: input → outline → content → preview → export
 *
 * v0.5: Integrated with task persistence + sidebar recovery.
 * - URL hash (#/ppt/task/{id}) is the single source of truth for "current task"
 * - PPTSidebar embedded in left panel (mirrors SessionSidebar pattern in chat)
 * - On taskId change: fetch task state, restore presentation OR reconnect SSE
 * - SSE auto-reconnects with backoff to survive frps 60s timeout
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Outline, Presentation, SlideContent,
  generateOutline, generatePresentationAsync, streamPresentation,
  generateFromResearch, generateFromChat,
  getTask, TaskStatus,
} from '../lib/ppt-api';
import { getTheme, Theme } from '../lib/ppt-themes';
import { exportToPptx } from '../lib/ppt-export';
import { OutlineEditor } from './OutlineEditor';
import { SlidePreview } from './SlidePreview';
import { ThemeSelector } from './ThemeSelector';
import { PPTSidebar } from './PPTSidebar';
import { PPTChatPanel } from './PPTChatPanel';
import { useUrlTask } from '../lib/useUrlTask';
import { PptSource } from '../App';

type Step = 'input' | 'outline' | 'preview';

interface PPTGeneratorProps {
  source?: PptSource | null;
  onSourceConsumed?: () => void;
  onExit?: () => void;
}

function getOutlineCacheKey(type: string, id: string): string {
  return `ppt_outline_${type}_${id}`;
}

function loadCachedOutline(type: string, id: string): Outline | null {
  try {
    const raw = localStorage.getItem(getOutlineCacheKey(type, id));
    if (!raw) return null;
    return JSON.parse(raw) as Outline;
  } catch {
    return null;
  }
}

function saveOutlineCache(type: string, id: string, outline: Outline): void {
  try {
    localStorage.setItem(getOutlineCacheKey(type, id), JSON.stringify(outline));
  } catch { /* quota exceeded, ignore */ }
}

function clearOutlineCache(type: string, id: string): void {
  localStorage.removeItem(getOutlineCacheKey(type, id));
}

export function PPTGenerator({ source, onSourceConsumed, onExit }: PPTGeneratorProps) {
  // v0.5: taskId from URL hash (single source of truth for current task)
  const [taskId, setTaskId] = useUrlTask();

  // State
  const [step, setStep] = useState<Step>('input');
  const [topic, setTopic] = useState('');
  const [numSlides, setNumSlides] = useState(8);
  const [language, setLanguage] = useState('zh');
  const [themeName, setThemeName] = useState('minimal-white');
  const [outline, setOutline] = useState<Outline | null>(null);
  const [presentation, setPresentation] = useState<Presentation | null>(null);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingFromSource, setIsGeneratingFromSource] = useState(false);
  const [generatingSlide, setGeneratingSlide] = useState<number | null>(null);
  const [totalSlides, setTotalSlides] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [cachedSource, setCachedSource] = useState<{ type: string; id: string } | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState<number>(0);
  const [pptChatOpen, setPptChatOpen] = useState(false);
  const lastSourceRef = useRef<string | null>(null);
  const sseControllerRef = useRef<AbortController | null>(null);
  // Track which taskId we already attached SSE to (avoid double-attach)
  const attachedTaskRef = useRef<string | null>(null);

  const theme = getTheme(themeName);

  // ─── v0.5: Task recovery on taskId change ─────────────────────
  // Triggered when URL hash changes (e.g. user clicks sidebar item,
  // browser back/forward, or fresh page load).
  useEffect(() => {
    // Cleanup previous SSE stream
    if (sseControllerRef.current) {
      sseControllerRef.current.abort();
      sseControllerRef.current = null;
    }
    attachedTaskRef.current = null;

    if (!taskId) {
      // No task selected — show input step (don't reset other state;
      // the user might be navigating away and back)
      return;
    }

    setIsLoading(true);
    setError(null);
    getTask(taskId).then((task) => {
      if (task.status === 'done' && task.presentation) {
        setPresentation(task.presentation.presentation);
        setCurrentSlideIndex(0);
        setStep('preview');
        setIsLoading(false);
        setGeneratingSlide(null);
      } else if (task.status === 'running') {
        // Re-attach to live SSE stream
        attachSse(taskId, totalSlidesForRecovery(task));
      } else if (task.status === 'error') {
        setError(task.error || '任务失败');
        setIsLoading(false);
        setGeneratingSlide(null);
      } else if (task.status === 'pending') {
        setError('任务排队中，请稍候...');
        setIsLoading(false);
      }
    }).catch((e) => {
      setError(`无法加载任务: ${e instanceof Error ? e.message : String(e)}`);
      setIsLoading(false);
      setGeneratingSlide(null);
    });

    return () => {
      if (sseControllerRef.current) {
        sseControllerRef.current.abort();
        sseControllerRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // Total slide count for SSE recovery — derive from presentation
  // length if available, otherwise from outline
  function totalSlidesForRecovery(task: any): number {
    if (task.presentation?.presentation?.slides) {
      return task.presentation.presentation.slides.length;
    }
    return outline?.pages.length || 0;
  }

  // Shared SSE attach used by both fresh-generation and recovery
  const attachSse = useCallback((id: string, total: number) => {
    if (attachedTaskRef.current === id) return;
    attachedTaskRef.current = id;
    setTotalSlides(total);
    setGeneratingSlide(0);

    sseControllerRef.current = streamPresentation(id, {
      onSlideStart: (event) => {
        setGeneratingSlide(event.index + 1);
        setTotalSlides(event.total);
      },
      onSlideDone: (event) => {
        setGeneratingSlide(event.index + 1);
        setTotalSlides(event.total);
      },
      onSlideError: (event) => {
        console.warn(`Slide ${event.index + 1} error:`, event.error);
      },
      onReconnecting: (attempt, delayMs) => {
        setReconnectAttempt(attempt);
        setError(`连接中断，${Math.round(delayMs / 1000)}s 后重连 (第 ${attempt} 次)...`);
      },
      onDone: (event) => {
        setPresentation(event.presentation.presentation);
        setCurrentSlideIndex(0);
        setStep('preview');
        setIsLoading(false);
        setGeneratingSlide(null);
        setReconnectAttempt(0);
        setError(null);
      },
      onError: (event) => {
        setError(event.error || 'Generation failed');
        setIsLoading(false);
        setGeneratingSlide(null);
        setReconnectAttempt(0);
      },
    }) as unknown as AbortController;
  }, []);

  // Handle source prop for research/chat import
  useEffect(() => {
    if (!source) return;

    const sourceKey = `${source.type}:${source.id}`;
    if (lastSourceRef.current === sourceKey) return;
    lastSourceRef.current = sourceKey;

    setCachedSource({ type: source.type, id: source.id });

    if (source.type === 'research') {
      handleFromResearch(source.id, false);
    } else if (source.type === 'chat') {
      handleFromChat(source.id, false);
    }

    onSourceConsumed?.();
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  // Generate outline from research
  const handleFromResearch = async (researchId: string, forceRegenerate: boolean) => {
    setIsGeneratingFromSource(true);
    setError(null);

    try {
      if (!forceRegenerate) {
        const cached = loadCachedOutline('research', researchId);
        if (cached) {
          setOutline(cached);
          setStep('outline');
          setIsGeneratingFromSource(false);
          return;
        }
      }

      const response = await generateFromResearch(researchId, themeName, language);
      saveOutlineCache('research', researchId, response.outline);
      setOutline(response.outline);
      setStep('outline');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load from research');
    } finally {
      setIsGeneratingFromSource(false);
    }
  };

  // Generate outline from chat
  const handleFromChat = async (chatId: string, forceRegenerate: boolean) => {
    setIsGeneratingFromSource(true);
    setError(null);

    try {
      if (!forceRegenerate) {
        const cached = loadCachedOutline('chat', chatId);
        if (cached) {
          setOutline(cached);
          setStep('outline');
          setIsGeneratingFromSource(false);
          return;
        }
      }

      const response = await generateFromChat(chatId, themeName, language);
      saveOutlineCache('chat', chatId, response.outline);
      setOutline(response.outline);
      setStep('outline');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load from chat');
    } finally {
      setIsGeneratingFromSource(false);
    }
  };

  // Regenerate outline from source (bypass cache)
  const handleRegenerateFromSource = () => {
    if (!cachedSource) return;
    clearOutlineCache(cachedSource.type, cachedSource.id);
    if (cachedSource.type === 'research') {
      handleFromResearch(cachedSource.id, true);
    } else if (cachedSource.type === 'chat') {
      handleFromChat(cachedSource.id, true);
    }
  };

  // Step 1: Generate Outline
  const handleGenerateOutline = async () => {
    if (!topic.trim()) {
      setError('Please enter a topic');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await generateOutline(topic, numSlides, language);
      setOutline(response.outline);
      setStep('outline');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate outline');
    } finally {
      setIsLoading(false);
    }
  };

  // Step 2: Generate Content (Async with SSE streaming)
  const handleGenerateContent = async () => {
    if (!outline) return;

    setIsLoading(true);
    setError(null);
    setGeneratingSlide(0);
    setTotalSlides(outline.pages.length);

    try {
      // Determine source type for backend task tracking
      const sourceType = cachedSource?.type as 'research' | 'chat' | undefined;
      const sourceId = cachedSource?.id;

      // Start async generation — returns task_id immediately (< 1s)
      const { task_id } = await generatePresentationAsync(
        outline, themeName, language, sourceType, sourceId,
      );

      // v0.5: Set URL hash → triggers useEffect to attach SSE (single owner)
      setTaskId(task_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate content');
      setIsLoading(false);
      setGeneratingSlide(null);
    }
  };

  // Export to PPTX
  const handleExport = async () => {
    if (!presentation) return;

    setIsLoading(true);
    try {
      await exportToPptx(presentation);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export');
    } finally {
      setIsLoading(false);
    }
  };

  // Navigation
  const handlePrev = () => {
    setCurrentSlideIndex((prev) => Math.max(0, prev - 1));
  };

  const handleNext = () => {
    if (presentation) {
      setCurrentSlideIndex((prev) => Math.min(presentation.slides.length - 1, prev + 1));
    }
  };

  // Reset
  const handleReset = () => {
    // Cancel any running SSE stream
    sseControllerRef.current?.abort();
    sseControllerRef.current = null;
    attachedTaskRef.current = null;

    // v0.5: clear URL hash so sidebar deselects
    setTaskId(null);

    setStep('input');
    setOutline(null);
    setPresentation(null);
    setCurrentSlideIndex(0);
    setError(null);
    setCachedSource(null);
    setGeneratingSlide(null);
    setTotalSlides(0);
    setReconnectAttempt(0);
  };

  return (
    <div className="h-full flex">
      {/* v0.5: Left sidebar — task history */}
      <div className="w-56 flex-shrink-0 border-r border-[var(--border)] overflow-y-auto bg-[var(--bg-secondary)]">
        <PPTSidebar />
      </div>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-4">
          {onExit && (
            <button
              onClick={onExit}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              ← 退出
            </button>
          )}
          <h1 className="text-xl font-bold">PPT Generator</h1>
          {step !== 'input' && (
            <button
              onClick={handleReset}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              New Presentation
            </button>
          )}
        </div>
        <div className="flex items-center gap-3">
          <ThemeSelector selectedTheme={themeName} onSelect={setThemeName} />
          {step === 'preview' && (
            <button
              onClick={handleExport}
              disabled={isLoading}
              className="px-4 py-2 bg-green-500 text-white rounded-md hover:bg-green-600 disabled:opacity-50"
            >
              {isLoading ? 'Exporting...' : 'Export .pptx'}
            </button>
          )}
        </div>
      </div>

      {/* Error / reconnect notice */}
      {error && (
        <div className={`p-3 text-sm ${
          reconnectAttempt > 0
            ? 'bg-yellow-100 text-yellow-800'
            : 'bg-red-100 text-red-700'
        }`}>
          {error}
          {reconnectAttempt > 0 && (
            <div className="mt-1 text-xs opacity-70">任务仍在服务器运行，可继续等待或从侧边栏手动重连</div>
          )}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {/* Loading from source */}
        {isGeneratingFromSource && (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <div className="w-10 h-10 border-4 border-blue-200 border-t-blue-500 rounded-full animate-spin" />
            <p className="text-sm text-gray-500">
              {cachedSource?.type === 'research' ? '正在从 Research 生成大纲...' : '正在从 Chat 生成大纲...'}
            </p>
          </div>
        )}

        {/* Loading recovered task from URL hash */}
        {!isGeneratingFromSource && isLoading && taskId && !outline && !presentation && (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <div className="w-10 h-10 border-4 border-blue-200 border-t-blue-500 rounded-full animate-spin" />
            <p className="text-sm text-gray-500">正在恢复任务 {taskId}...</p>
          </div>
        )}

        {/* Step 1: Input */}
        {!isGeneratingFromSource && step === 'input' && (
          <div className="max-w-xl mx-auto">
            <div className="bg-white rounded-lg shadow-md p-6">
              <h2 className="text-lg font-semibold mb-4">Create Presentation</h2>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Topic
                  </label>
                  <input
                    type="text"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g., Quantum Computing Future"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Number of Slides
                    </label>
                    <input
                      type="number"
                      value={numSlides}
                      onChange={(e) => setNumSlides(Number(e.target.value))}
                      min={3}
                      max={20}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Language
                    </label>
                    <select
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="zh">Chinese</option>
                      <option value="en">English</option>
                    </select>
                  </div>
                </div>
                <button
                  onClick={handleGenerateOutline}
                  disabled={isLoading || !topic.trim()}
                  className="w-full px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50"
                >
                  {isLoading ? 'Generating...' : 'Generate Outline'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Step 2: Outline */}
        {!isGeneratingFromSource && step === 'outline' && outline && (
          <div className="max-w-3xl mx-auto">
            {/* Progress bar when generating */}
            {isLoading && generatingSlide !== null && (
              <div className="mb-4 p-4 bg-blue-50 rounded-lg">
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-5 h-5 border-2 border-blue-300 border-t-blue-500 rounded-full animate-spin" />
                  <span className="text-sm font-medium text-blue-700">
                    正在生成第 {generatingSlide}/{totalSlides} 页...
                  </span>
                </div>
                <div className="w-full bg-blue-200 rounded-full h-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${(generatingSlide / totalSlides) * 100}%` }}
                  />
                </div>
              </div>
            )}
            <OutlineEditor
              outline={outline}
              onUpdate={setOutline}
              onGenerate={handleGenerateContent}
              onRegenerate={cachedSource ? handleRegenerateFromSource : undefined}
              isLoading={isLoading}
            />
          </div>
        )}

        {/* Step 3: Preview */}
        {!isGeneratingFromSource && step === 'preview' && presentation && (
          <div className="h-full flex">
            <div className="flex-1 min-w-0">
              <SlidePreview
                slides={presentation.slides}
                currentIndex={currentSlideIndex}
                theme={theme}
                onSelect={setCurrentSlideIndex}
                onPrev={handlePrev}
                onNext={handleNext}
              />
            </div>
            <PPTChatPanel
              taskId={taskId || ''}
              presentation={presentation}
              currentSlideIndex={currentSlideIndex}
              onPresentationUpdate={(pres) => setPresentation(pres)}
              onSlideSelect={setCurrentSlideIndex}
              isOpen={pptChatOpen}
              onToggle={() => setPptChatOpen(!pptChatOpen)}
            />
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

export default PPTGenerator;
