/**
 * PPT Generator - Main Component
 * Handles the complete workflow: input → outline → content → preview → export
 */

import React, { useState, useEffect, useRef } from 'react';
import { Outline, Presentation, SlideContent, generateOutline, generatePresentation, generateFromResearch, generateFromChat } from '../lib/ppt-api';
import { getTheme, Theme } from '../lib/ppt-themes';
import { exportToPptx } from '../lib/ppt-export';
import { OutlineEditor } from './OutlineEditor';
import { SlidePreview } from './SlidePreview';
import { ThemeSelector } from './ThemeSelector';
import { PptSource } from '../App';

type Step = 'input' | 'outline' | 'preview';

interface PPTGeneratorProps {
  source?: PptSource | null;
  onSourceConsumed?: () => void;
}

export function PPTGenerator({ source, onSourceConsumed }: PPTGeneratorProps) {
  // State
  const [step, setStep] = useState<Step>('input');
  const [topic, setTopic] = useState('');
  const [numSlides, setNumSlides] = useState(8);
  const [language, setLanguage] = useState('zh');
  const [themeName, setThemeName] = useState('professional');
  const [outline, setOutline] = useState<Outline | null>(null);
  const [presentation, setPresentation] = useState<Presentation | null>(null);
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSourceRef = useRef<string | null>(null);

  const theme = getTheme(themeName);

  // Handle source prop for research/chat import
  useEffect(() => {
    if (!source) return;
    
    const sourceKey = `${source.type}:${source.id}`;
    if (lastSourceRef.current === sourceKey) return;
    lastSourceRef.current = sourceKey;
    
    if (source.type === 'research') {
      handleFromResearch(source.id);
    } else if (source.type === 'chat') {
      handleFromChat(source.id);
    }
    
    onSourceConsumed?.();
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  // Generate outline from research
  const handleFromResearch = async (researchId: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await generateFromResearch(researchId, themeName, language);
      setOutline(response.outline);
      setStep('outline');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load from research');
    } finally {
      setIsLoading(false);
    }
  };

  // Generate outline from chat
  const handleFromChat = async (chatId: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await generateFromChat(chatId, themeName, language);
      setOutline(response.outline);
      setStep('outline');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load from chat');
    } finally {
      setIsLoading(false);
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

  // Step 2: Generate Content
  const handleGenerateContent = async () => {
    if (!outline) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await generatePresentation(outline, themeName, language);
      setPresentation(response.presentation);
      setCurrentSlideIndex(0);
      setStep('preview');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate content');
    } finally {
      setIsLoading(false);
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
    setStep('input');
    setOutline(null);
    setPresentation(null);
    setCurrentSlideIndex(0);
    setError(null);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold">PPT Generator</h1>
          {step !== 'input' && (
            <button
              onClick={handleReset}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              ← New Presentation
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

      {/* Error */}
      {error && (
        <div className="p-3 bg-red-100 text-red-700 text-sm">{error}</div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {/* Step 1: Input */}
        {step === 'input' && (
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
        {step === 'outline' && outline && (
          <div className="max-w-3xl mx-auto">
            <OutlineEditor
              outline={outline}
              onUpdate={setOutline}
              onGenerate={handleGenerateContent}
              isLoading={isLoading}
            />
          </div>
        )}

        {/* Step 3: Preview */}
        {step === 'preview' && presentation && (
          <div className="h-full">
            <SlidePreview
              slides={presentation.slides}
              currentIndex={currentSlideIndex}
              theme={theme}
              onSelect={setCurrentSlideIndex}
              onPrev={handlePrev}
              onNext={handleNext}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default PPTGenerator;
