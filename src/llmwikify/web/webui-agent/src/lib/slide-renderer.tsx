/**
 * PPT Generator - Slide Renderer
 * Renders slide content as React components based on layout type
 *
 * v0.6.1: Applies theme tokens via inline CSS custom properties on the
 * root slide element. All internal elements reference `var(--color-*)`,
 * `var(--font-*)`, `var(--radius-*)` etc. — one-time injection at root,
 * zero per-element color overrides needed.
 *
 * Theme tokens are adapted from html-ppt-skill
 * (https://github.com/lewislulu/html-ppt-skill, MIT, 5.4k ⭐).
 */

import React from 'react';
import { Theme, themeToStyleVars } from './ppt-themes';

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
        return <TitleSlide slide={slide} />;
      case 'section':
        return <SectionSlide slide={slide} />;
      case 'bullets':
        return <BulletsSlide slide={slide} />;
      case 'title_content':
        return <TitleContentSlide slide={slide} />;
      case 'two_column': {
        // v0.6.2.patch1: Defensive fallback — if both columns are empty but
        // bullets exist, render as BulletsSlide. Covers cached tasks and
        // edge cases where the backend rules fallback didn't apply.
        const hasLeft = (slide.left?.items?.length ?? 0) > 0;
        const hasRight = (slide.right?.items?.length ?? 0) > 0;
        if (!hasLeft && !hasRight && (slide.bullets?.length ?? 0) > 0) {
          return <BulletsSlide slide={slide} />;
        }
        return <TwoColumnSlide slide={slide} />;
      }
      case 'chart':
        return <ChartSlide slide={slide} />;
      case 'quote':
        return <QuoteSlide slide={slide} />;
      default:
        return <TitleContentSlide slide={slide} />;
    }
  };

  // Apply all theme tokens as CSS custom properties at the root element.
  // All inner elements use var(--color-*) / var(--font-*) / var(--radius-*) etc.
  const styleVars = themeToStyleVars(theme);

  return (
    <div
      className={`slide-root aspect-video w-full shadow-lg overflow-hidden ${scale}`}
      style={{
        ...styleVars,
        background: 'var(--color-bg)',
        fontFamily: 'var(--font-body)',
        color: 'var(--color-text-1)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: 'var(--shadow-lg)',
      }}
    >
      {renderContent()}
    </div>
  );
}

function TitleSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <h1
        className="text-4xl font-bold text-center mb-4"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}
      >
        {slide.title}
      </h1>
      {slide.subtitle && (
        <p className="text-xl" style={{ color: 'var(--color-text-2)' }}>
          {slide.subtitle}
        </p>
      )}
      <div
        className="w-24 h-1 mt-6"
        style={{ background: 'var(--gradient-primary)', borderRadius: 'var(--radius-sm)' }}
      />
    </div>
  );
}

function SectionSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <div
        className="w-16 h-16 rounded-full mb-6 flex items-center justify-center"
        style={{ background: 'var(--gradient-primary)', borderRadius: 'var(--radius-md)' }}
      >
        <span className="text-2xl font-bold" style={{ color: 'var(--color-bg)' }}>
          {slide.title.charAt(0)}
        </span>
      </div>
      <h2
        className="text-3xl font-bold text-center"
        style={{ color: 'var(--color-text-1)', fontFamily: 'var(--font-heading)' }}
      >
        {slide.title}
      </h2>
      {slide.subtitle && (
        <p className="text-lg mt-4" style={{ color: 'var(--color-text-2)' }}>
          {slide.subtitle}
        </p>
      )}
    </div>
  );
}

function BulletsSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6 pb-2 border-b"
        style={{
          color: 'var(--color-accent)',
          borderColor: 'var(--color-border-strong)',
          fontFamily: 'var(--font-heading)',
        }}
      >
        {slide.title}
      </h2>
      <ul className="flex-1 space-y-3">
        {slide.bullets?.map((bullet, i) => (
          <li key={i} className="flex items-start">
            <span
              className="w-2 h-2 mt-2 mr-3 flex-shrink-0"
              style={{ backgroundColor: 'var(--color-accent)', borderRadius: 'var(--radius-sm)' }}
            />
            <span className="text-lg" style={{ color: 'var(--color-text-1)' }}>
              {bullet}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TitleContentSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-4"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 flex items-center">
        <p className="text-lg leading-relaxed" style={{ color: 'var(--color-text-1)' }}>
          {slide.content}
        </p>
      </div>
    </div>
  );
}

function TwoColumnSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 grid grid-cols-2 gap-6">
        {slide.left && (
          <div
            className="p-4"
            style={{
              backgroundColor: 'var(--color-surface-2)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--color-border)',
            }}
          >
            <h3
              className="font-semibold mb-3"
              style={{ color: 'var(--color-accent)' }}
            >
              {slide.left.heading}
            </h3>
            <ul className="space-y-2">
              {slide.left.items.map((item, i) => (
                <li key={i} className="text-sm" style={{ color: 'var(--color-text-1)' }}>
                  • {item}
                </li>
              ))}
            </ul>
          </div>
        )}
        {slide.right && (
          <div
            className="p-4"
            style={{
              backgroundColor: 'var(--color-surface-2)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--color-border)',
            }}
          >
            <h3
              className="font-semibold mb-3"
              style={{ color: 'var(--color-accent-2)' }}
            >
              {slide.right.heading}
            </h3>
            <ul className="space-y-2">
              {slide.right.items.map((item, i) => (
                <li key={i} className="text-sm" style={{ color: 'var(--color-text-1)' }}>
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

function ChartSlide({ slide }: { slide: SlideContent }) {
  const maxValue = Math.max(...(slide.chart_data?.values || [1])) || 1;

  return (
    <div className="h-full flex flex-col p-8">
      <h2
        className="text-2xl font-bold mb-6"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}
      >
        {slide.title}
      </h2>
      <div className="flex-1 flex items-end justify-around gap-2">
        {slide.chart_data?.labels.map((label, i) => {
          const value = slide.chart_data?.values[i] || 0;
          const height = (value / maxValue) * 100;
          return (
            <div key={i} className="flex flex-col items-center flex-1">
              <span className="text-xs mb-1" style={{ color: 'var(--color-text-1)' }}>
                {value}
              </span>
              <div
                className="w-full"
                style={{
                  height: `${height}%`,
                  background: 'var(--gradient-primary)',
                  borderRadius: 'var(--radius-sm) var(--radius-sm) 0 0',
                }}
              />
              <span className="text-xs mt-2 text-center" style={{ color: 'var(--color-text-2)' }}>
                {label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function QuoteSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col items-center justify-center p-8">
      <div
        className="text-6xl mb-4"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}
      >
        "
      </div>
      <blockquote
        className="text-xl italic text-center max-w-2xl"
        style={{ color: 'var(--color-text-1)' }}
      >
        {slide.text}
      </blockquote>
      {slide.author && (
        <p className="mt-6 text-lg" style={{ color: 'var(--color-text-2)' }}>
          — {slide.author}
        </p>
      )}
    </div>
  );
}

export default SlideRenderer;
