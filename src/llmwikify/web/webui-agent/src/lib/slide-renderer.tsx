/**
 * PPT Generator - Slide Renderer
 * Renders slide content as React components based on layout type
 */

import React from 'react';
import { Theme } from './ppt-themes';

export interface SlideContent {
  id: string;
  layout: string;
  title: string;
  subtitle?: string;
  content?: string;
  bullets?: string[];
  left?: { heading: string; items: string[] };
  right?: { heading: string; items: string[] };
  chart_type?: string;
  chart_data?: { labels: string[]; values: number[] };
  text?: string;
  author?: string;
  image?: string;
}

interface SlideRendererProps {
  slide: SlideContent;
  theme: Theme;
  isPreview?: boolean;
}

export function SlideRenderer({ slide, theme, isPreview = true }: SlideRendererProps) {
  const scale = isPreview ? 'scale-100' : 'scale-75';

  const renderContent = () => {
    switch (slide.layout) {
      case 'title':
        return <TitleSlide slide={slide} theme={theme} />;
      case 'section':
        return <SectionSlide slide={slide} theme={theme} />;
      case 'bullets':
        return <BulletsSlide slide={slide} theme={theme} />;
      case 'title_content':
        return <TitleContentSlide slide={slide} theme={theme} />;
      case 'two_column':
        return <TwoColumnSlide slide={slide} theme={theme} />;
      case 'chart':
        return <ChartSlide slide={slide} theme={theme} />;
      case 'quote':
        return <QuoteSlide slide={slide} theme={theme} />;
      default:
        return <TitleContentSlide slide={slide} theme={theme} />;
    }
  };

  return (
    <div
      className={`aspect-video w-full bg-white shadow-lg rounded-lg overflow-hidden ${scale}`}
      style={{ backgroundColor: theme.colors.background }}
    >
      {renderContent()}
    </div>
  );
}

function TitleSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <h1
        className="text-4xl font-bold text-center mb-4"
        style={{ color: theme.colors.primary }}
      >
        {slide.title}
      </h1>
      {slide.subtitle && (
        <p className="text-xl" style={{ color: theme.colors.secondary }}>
          {slide.subtitle}
        </p>
      )}
      <div
        className="w-24 h-1 mt-6"
        style={{ backgroundColor: theme.colors.accent }}
      />
    </div>
  );
}

function SectionSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <div
        className="w-16 h-16 rounded-full mb-6 flex items-center justify-center"
        style={{ backgroundColor: theme.colors.primary }}
      >
        <span className="text-2xl text-white font-bold">
          {slide.title.charAt(0)}
        </span>
      </div>
      <h2
        className="text-3xl font-bold text-center"
        style={{ color: theme.colors.text }}
      >
        {slide.title}
      </h2>
      {slide.subtitle && (
        <p className="text-lg mt-4" style={{ color: theme.colors.secondary }}>
          {slide.subtitle}
        </p>
      )}
    </div>
  );
}

function BulletsSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6 pb-2 border-b"
        style={{ color: theme.colors.primary, borderColor: theme.colors.accent }}
      >
        {slide.title}
      </h2>
      <ul className="flex-1 space-y-3">
        {slide.bullets?.map((bullet, i) => (
          <li key={i} className="flex items-start">
            <span
              className="w-2 h-2 rounded-full mt-2 mr-3 flex-shrink-0"
              style={{ backgroundColor: theme.colors.accent }}
            />
            <span className="text-lg" style={{ color: theme.colors.text }}>
              {bullet}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TitleContentSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-4"
        style={{ color: theme.colors.primary }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 flex items-center">
        <p className="text-lg leading-relaxed" style={{ color: theme.colors.text }}>
          {slide.content}
        </p>
      </div>
    </div>
  );
}

function TwoColumnSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6"
        style={{ color: theme.colors.primary }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 grid grid-cols-2 gap-6">
        {slide.left && (
          <div className="p-4 rounded-lg" style={{ backgroundColor: `${theme.colors.primary}10` }}>
            <h3 className="font-semibold mb-3" style={{ color: theme.colors.primary }}>
              {slide.left.heading}
            </h3>
            <ul className="space-y-2">
              {slide.left.items.map((item, i) => (
                <li key={i} className="text-sm" style={{ color: theme.colors.text }}>
                  • {item}
                </li>
              ))}
            </ul>
          </div>
        )}
        {slide.right && (
          <div className="p-4 rounded-lg" style={{ backgroundColor: `${theme.colors.accent}10` }}>
            <h3 className="font-semibold mb-3" style={{ color: theme.colors.accent }}>
              {slide.right.heading}
            </h3>
            <ul className="space-y-2">
              {slide.right.items.map((item, i) => (
                <li key={i} className="text-sm" style={{ color: theme.colors.text }}>
                  • {item}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function ChartSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  const maxValue = Math.max(...(slide.chart_data?.values || [1])) || 1;

  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6"
        style={{ color: theme.colors.primary }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 flex items-end justify-around gap-2">
        {slide.chart_data?.labels.map((label, i) => {
          const value = slide.chart_data?.values[i] || 0;
          const height = (value / maxValue) * 100;
          return (
            <div key={i} className="flex flex-col items-center flex-1">
              <span className="text-xs mb-1" style={{ color: theme.colors.text }}>
                {value}
              </span>
              <div
                className="w-full rounded-t"
                style={{
                  height: `${height}%`,
                  backgroundColor: i % 2 === 0 ? theme.colors.primary : theme.colors.accent,
                }}
              />
              <span className="text-xs mt-2 text-center" style={{ color: theme.colors.secondary }}>
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function QuoteSlide({ slide, theme }: { slide: SlideContent; theme: Theme }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <div
        className="text-6xl mb-4"
        style={{ color: theme.colors.accent }}
      >
        "
      </div>
      <blockquote
        className="text-xl italic text-center max-w-2xl"
        style={{ color: theme.colors.text }}
      >
        {slide.text}
      </blockquote>
      {slide.author && (
        <p className="mt-6 text-lg" style={{ color: theme.colors.secondary }}>
          — {slide.author}
        </p>
      )}
    </div>
  );
}

export default SlideRenderer;
