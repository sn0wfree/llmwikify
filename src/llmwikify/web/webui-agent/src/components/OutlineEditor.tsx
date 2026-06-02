/**
 * PPT Generator - Outline Editor Component
 * Allows users to edit the generated outline before content generation
 */

import React from 'react';
import { Outline, OutlinePage } from '../lib/ppt-api';

interface OutlineEditorProps {
  outline: Outline;
  onUpdate: (outline: Outline) => void;
  onGenerate: () => void;
  onRegenerate?: () => void;
  isLoading?: boolean;
}

const CONTENT_TYPE_LABELS: Record<string, string> = {
  intro: 'Introduction',
  section: 'Section',
  bullets: 'Bullets',
  comparison: 'Comparison',
  data: 'Data/Chart',
  quote: 'Quote',
  summary: 'Summary',
};

const CONTENT_TYPE_COLORS: Record<string, string> = {
  intro: 'bg-blue-100 text-blue-800',
  section: 'bg-purple-100 text-purple-800',
  bullets: 'bg-green-100 text-green-800',
  comparison: 'bg-yellow-100 text-yellow-800',
  data: 'bg-red-100 text-red-800',
  quote: 'bg-indigo-100 text-indigo-800',
  summary: 'bg-gray-100 text-gray-800',
};

export function OutlineEditor({ outline, onUpdate, onGenerate, onRegenerate, isLoading }: OutlineEditorProps) {
  const handleTitleChange = (value: string) => {
    onUpdate({ ...outline, title: value });
  };

  const handleSubtitleChange = (value: string) => {
    onUpdate({ ...outline, subtitle: value });
  };

  const handlePageChange = (index: number, field: keyof OutlinePage, value: string) => {
    const newPages = [...outline.pages];
    newPages[index] = { ...newPages[index], [field]: value };
    onUpdate({ ...outline, pages: newPages });
  };

  const handleContentTypeChange = (index: number, value: string) => {
    handlePageChange(index, 'content_type', value);
  };

  const addPage = () => {
    const newPage: OutlinePage = {
      page: outline.pages.length + 1,
      content_type: 'bullets',
      title: 'New Slide',
      description: '',
    };
    onUpdate({ ...outline, pages: [...outline.pages, newPage] });
  };

  const removePage = (index: number) => {
    if (outline.pages.length <= 1) return;
    const newPages = outline.pages
      .filter((_, i) => i !== index)
      .map((p, i) => ({ ...p, page: i + 1 }));
    onUpdate({ ...outline, pages: newPages });
  };

  const movePage = (index: number, direction: 'up' | 'down') => {
    const newIndex = direction === 'up' ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= outline.pages.length) return;
    
    const newPages = [...outline.pages];
    const temp = newPages[index];
    newPages[index] = newPages[newIndex];
    newPages[newIndex] = temp;
    
    // Re-number pages with new objects
    const renumbered = newPages.map((p, i) => ({ ...p, page: i + 1 }));
    onUpdate({ ...outline, pages: renumbered });
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h3 className="text-lg font-semibold mb-4">Outline Editor</h3>
      
      {/* Title & Subtitle */}
      <div className="mb-6 space-y-3">
        <input
          type="text"
          value={outline.title}
          onChange={(e) => handleTitleChange(e.target.value)}
          placeholder="Presentation Title"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-lg font-semibold"
        />
        <input
          type="text"
          value={outline.subtitle || ''}
          onChange={(e) => handleSubtitleChange(e.target.value)}
          placeholder="Subtitle (optional)"
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      
      {/* Pages */}
      <div className="space-y-3">
        {outline.pages.map((page, index) => (
          <div
            key={index}
            className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg border border-gray-200"
          >
            {/* Page Number */}
            <div className="w-8 h-8 flex items-center justify-center bg-blue-500 text-white rounded-full text-sm font-semibold flex-shrink-0">
              {page.page}
            </div>
            
            {/* Content */}
            <div className="flex-1 space-y-2">
              <input
                type="text"
                value={page.title}
                onChange={(e) => handlePageChange(index, 'title', e.target.value)}
                placeholder="Slide Title"
                className="w-full px-2 py-1 border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <input
                type="text"
                value={page.description}
                onChange={(e) => handlePageChange(index, 'description', e.target.value)}
                placeholder="Description"
                className="w-full px-2 py-1 text-sm text-gray-600 border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <select
                value={page.content_type}
                onChange={(e) => handleContentTypeChange(index, e.target.value)}
                className={`px-2 py-1 text-xs rounded-full ${CONTENT_TYPE_COLORS[page.content_type] || 'bg-gray-100'}`}
              >
                {Object.entries(CONTENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            
            {/* Actions */}
            <div className="flex flex-col gap-1">
              <button
                onClick={() => movePage(index, 'up')}
                disabled={index === 0}
                className="w-6 h-6 flex items-center justify-center text-gray-500 hover:text-gray-700 disabled:opacity-30"
              >
                ▲
              </button>
              <button
                onClick={() => movePage(index, 'down')}
                disabled={index === outline.pages.length - 1}
                className="w-6 h-6 flex items-center justify-center text-gray-500 hover:text-gray-700 disabled:opacity-30"
              >
                ▼
              </button>
              <button
                onClick={() => removePage(index)}
                disabled={outline.pages.length <= 1}
                className="w-6 h-6 flex items-center justify-center text-red-500 hover:text-red-700 disabled:opacity-30"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
      
      {/* Actions */}
      <div className="mt-4 flex gap-3">
        <button
          onClick={addPage}
          className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200"
        >
          + Add Slide
        </button>
        {onRegenerate && (
          <button
            onClick={onRegenerate}
            disabled={isLoading}
            className="px-4 py-2 text-sm bg-yellow-100 text-yellow-700 rounded-md hover:bg-yellow-200 disabled:opacity-50"
          >
            重新生成大纲
          </button>
        )}
        <button
          onClick={onGenerate}
          disabled={isLoading || outline.pages.length === 0}
          className="px-4 py-2 text-sm bg-blue-500 text-white rounded-md hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? 'Generating...' : 'Generate Content'}
        </button>
      </div>
    </div>
  );
}

export default OutlineEditor;
