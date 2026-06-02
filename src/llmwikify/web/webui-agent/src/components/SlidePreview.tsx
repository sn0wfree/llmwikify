/**
 * PPT Generator - Slide Preview Component
 * Shows thumbnail strip and large preview of selected slide
 */

import React from 'react';
import { SlideRenderer, SlideContent } from '../lib/slide-renderer';
import { Theme } from '../lib/ppt-themes';

interface SlidePreviewProps {
  slides: SlideContent[];
  currentIndex: number;
  theme: Theme;
  onSelect: (index: number) => void;
  onPrev: () => void;
  onNext: () => void;
}

export function SlidePreview({
  slides,
  currentIndex,
  theme,
  onSelect,
  onPrev,
  onNext,
}: SlidePreviewProps) {
  const currentSlide = slides[currentIndex];

  return (
    <div className="flex flex-col h-full">
      {/* Thumbnail Strip */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-4">
        {slides.map((slide, index) => (
          <button
            key={slide.id}
            onClick={() => onSelect(index)}
            className={`flex-shrink-0 w-32 aspect-video rounded-lg overflow-hidden border-2 transition-all ${
              index === currentIndex
                ? 'border-blue-500 ring-2 ring-blue-200'
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="w-full h-full transform scale-50 origin-top-left" style={{ width: '200%', height: '200%' }}>
              <SlideRenderer slide={slide} theme={theme} isPreview={false} />
            </div>
          </button>
        ))}
      </div>

      {/* Large Preview */}
      <div className="flex-1 flex items-center justify-center bg-gray-100 rounded-lg p-4">
        {currentSlide && (
          <div className="w-full max-w-4xl">
            <SlideRenderer slide={currentSlide} theme={theme} isPreview={true} />
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between mt-4">
        <button
          onClick={onPrev}
          disabled={currentIndex === 0}
          className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          ← Previous
        </button>
        <span className="text-sm text-gray-600">
          {currentIndex + 1} / {slides.length}
        </span>
        <button
          onClick={onNext}
          disabled={currentIndex === slides.length - 1}
          className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

export default SlidePreview;
