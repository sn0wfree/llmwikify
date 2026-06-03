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
  // Extended layout fields (v0.7)
  swot?: { strengths: string[]; weaknesses: string[]; opportunities: string[]; threats: string[] };
  table_headers?: string[];
  table_rows?: string[][];
  events?: { date: string; title: string; description?: string }[];
  kpi_items?: { label: string; value: string; trend?: string }[];
  central_topic?: string;
  branches?: { name: string; children?: { name: string }[] }[];
  steps?: { title: string; description?: string }[];
  images?: { url: string; caption?: string }[];
  html?: string;
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
      case 'swot':
        return <SwotSlide slide={slide} />;
      case 'table':
        return <TableSlide slide={slide} />;
      case 'timeline':
        return <TimelineSlide slide={slide} />;
      case 'kpi_grid':
        return <KpiGridSlide slide={slide} />;
      case 'mindmap':
        return <MindmapSlide slide={slide} />;
      case 'process':
        return <ProcessSlide slide={slide} />;
      case 'gallery':
        return <GallerySlide slide={slide} />;
      case 'image_text':
        return <ImageTextSlide slide={slide} />;
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

const SWOT_COLORS = {
  strengths: { bg: '#dcfce7', border: '#86efac', text: '#166534', label: 'S 优势' },
  weaknesses: { bg: '#fee2e2', border: '#fca5a5', text: '#991b1b', label: 'W 劣势' },
  opportunities: { bg: '#dbeafe', border: '#93c5fd', text: '#1e40af', label: 'O 机会' },
  threats: { bg: '#ffedd5', border: '#fdba74', text: '#9a3412', label: 'T 威胁' },
};

function SwotSlide({ slide }: { slide: SlideContent }) {
  const swot = slide.swot || { strengths: [], weaknesses: [], opportunities: [], threats: [] };
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-3">
        {(Object.keys(SWOT_COLORS) as Array<keyof typeof SWOT_COLORS>).map((key) => {
          const cfg = SWOT_COLORS[key];
          const items = swot[key] || [];
          return (
            <div key={key} className="p-3 rounded-lg" style={{ backgroundColor: cfg.bg, border: `1px solid ${cfg.border}` }}>
              <h3 className="font-bold text-sm mb-2" style={{ color: cfg.text }}>{cfg.label}</h3>
              <ul className="space-y-1">
                {items.map((item: string, i: number) => (
                  <li key={i} className="text-xs" style={{ color: cfg.text }}>• {item}</li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TableSlide({ slide }: { slide: SlideContent }) {
  const headers = slide.table_headers || [];
  const rows = slide.table_rows || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {headers.map((h: string, i: number) => (
                <th key={i} className="px-3 py-2 text-left font-semibold" style={{ backgroundColor: 'var(--color-accent)', color: 'var(--color-bg)', borderBottom: '2px solid var(--color-border-strong)' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row: string[], ri: number) => (
              <tr key={ri} style={{ backgroundColor: ri % 2 === 0 ? 'var(--color-surface)' : 'var(--color-surface-2)' }}>
                {row.map((cell: string, ci: number) => (
                  <td key={ci} className="px-3 py-2" style={{ color: 'var(--color-text-1)', borderBottom: '1px solid var(--color-border)' }}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TimelineSlide({ slide }: { slide: SlideContent }) {
  const events = slide.events || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 relative pl-6">
        <div className="absolute left-2 top-0 bottom-0 w-0.5" style={{ backgroundColor: 'var(--color-accent)' }} />
        {events.map((ev: { date: string; title: string; description?: string }, i: number) => (
          <div key={i} className="relative mb-4 pl-4">
            <div className="absolute -left-4 top-1 w-3 h-3 rounded-full" style={{ backgroundColor: 'var(--color-accent)' }} />
            <div className="text-xs font-semibold" style={{ color: 'var(--color-accent)' }}>{ev.date}</div>
            <div className="font-medium text-sm" style={{ color: 'var(--color-text-1)' }}>{ev.title}</div>
            {ev.description && <div className="text-xs mt-1" style={{ color: 'var(--color-text-2)' }}>{ev.description}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function KpiGridSlide({ slide }: { slide: SlideContent }) {
  const items = slide.kpi_items || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 grid grid-cols-2 gap-4">
        {items.map((kpi: { label: string; value: string; trend?: string }, i: number) => (
          <div key={i} className="flex flex-col items-center justify-center p-4 rounded-lg" style={{ backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)' }}>
            <div className="text-3xl font-bold" style={{ color: 'var(--color-accent)' }}>{kpi.value}</div>
            <div className="text-sm mt-1" style={{ color: 'var(--color-text-2)' }}>{kpi.label}</div>
            {kpi.trend && <div className="text-xs mt-1" style={{ color: kpi.trend.startsWith('+') ? '#16a34a' : kpi.trend.startsWith('-') ? '#dc2626' : 'var(--color-text-3)' }}>{kpi.trend}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function MindmapSlide({ slide }: { slide: SlideContent }) {
  const branches = slide.branches || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 flex items-center justify-center">
        <div className="relative">
          <div className="px-6 py-3 rounded-full font-bold text-lg" style={{ background: 'var(--gradient-primary)', color: 'var(--color-bg)' }}>
            {slide.central_topic || slide.title}
          </div>
          <div className="absolute top-1/2 left-full ml-4 -translate-y-1/2 flex flex-col gap-2">
            {branches.map((branch: { name: string; children?: { name: string }[] }, i: number) => (
              <div key={i} className="flex items-center gap-2">
                <div className="w-8 h-0.5" style={{ backgroundColor: 'var(--color-accent)' }} />
                <div className="px-3 py-1 rounded text-sm" style={{ backgroundColor: 'var(--color-surface-2)', color: 'var(--color-text-1)', border: '1px solid var(--color-border)' }}>
                  {branch.name}
                </div>
                {branch.children && (
                  <div className="flex flex-col gap-1 ml-2">
                    {branch.children.map((child: { name: string }, ci: number) => (
                      <div key={ci} className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: 'var(--color-surface)', color: 'var(--color-text-2)' }}>
                        {child.name}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ProcessSlide({ slide }: { slide: SlideContent }) {
  const steps = slide.steps || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-2">
          {steps.map((step: { title: string; description?: string }, i: number) => (
            <React.Fragment key={i}>
              <div className="flex flex-col items-center">
                <div className="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm" style={{ background: 'var(--gradient-primary)', color: 'var(--color-bg)' }}>
                  {i + 1}
                </div>
                <div className="text-xs font-medium mt-2 text-center max-w-[80px]" style={{ color: 'var(--color-text-1)' }}>
                  {step.title}
                </div>
                {step.description && (
                  <div className="text-[10px] mt-1 text-center max-w-[80px]" style={{ color: 'var(--color-text-2)' }}>
                    {step.description}
                  </div>
                )}
              </div>
              {i < steps.length - 1 && (
                <div className="text-lg mb-6" style={{ color: 'var(--color-accent)' }}>→</div>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  );
}

function GallerySlide({ slide }: { slide: SlideContent }) {
  const images = slide.images || [];
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 grid grid-cols-2 gap-3">
        {images.map((img: { url: string; caption?: string }, i: number) => (
          <div key={i} className="flex flex-col rounded-lg overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
            <div className="flex-1 bg-cover bg-center" style={{ backgroundImage: `url(${img.url})`, backgroundColor: 'var(--color-surface-2)', minHeight: '60px' }} />
            {img.caption && <div className="text-xs p-2 text-center" style={{ color: 'var(--color-text-2)' }}>{img.caption}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function ImageTextSlide({ slide }: { slide: SlideContent }) {
  return (
    <div className="h-full flex flex-col p-6">
      <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-heading)' }}>
        {slide.title}
      </h2>
      <div className="flex-1 flex gap-4">
        <div className="w-2/5 rounded-lg bg-cover bg-center" style={{ backgroundImage: `url(${slide.image})`, backgroundColor: 'var(--color-surface-2)', border: '1px solid var(--color-border)', minHeight: '80px' }} />
        <div className="w-3/5 flex items-center">
          <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-1)' }}>
            {slide.content}
          </p>
        </div>
      </div>
    </div>
  );
}

export default SlideRenderer;
