/**
 * PPT Generator - Export to PPTX using PptxGenJS
 */

import PptxGenJS from 'pptxgenjs';
import { Theme } from './ppt-themes';
import { SlideContent } from './slide-renderer';

export interface PresentationData {
  title: string;
  subtitle?: string;
  theme: Theme;
  slides: SlideContent[];
}

/**
 * Lighten a hex color by mixing with white
 */
function lightenColor(hex: string, factor: number = 0.85): string {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  
  const lr = Math.round(r + (255 - r) * factor);
  const lg = Math.round(g + (255 - g) * factor);
  const lb = Math.round(b + (255 - b) * factor);
  
  return `${lr.toString(16).padStart(2, '0')}${lg.toString(16).padStart(2, '0')}${lb.toString(16).padStart(2, '0')}`;
}

export async function exportToPptx(presentation: PresentationData): Promise<void> {
  const pptx = new PptxGenJS();
  
  // Set presentation properties
  pptx.title = presentation.title;
  pptx.author = 'LLMWikify';
  pptx.subject = presentation.subtitle || presentation.title;
  
  // Set theme colors
  const theme = presentation.theme;
  
  // Add slides
  for (const slide of presentation.slides) {
    const pptSlide = pptx.addSlide();
    
    // Set slide background
    pptSlide.background = { color: theme.colors.background.replace('#', '') };
    
    // Render based on layout type
    switch (slide.layout) {
      case 'title':
        renderTitleSlide(pptSlide, slide, theme);
        break;
      case 'section':
        renderSectionSlide(pptSlide, slide, theme);
        break;
      case 'bullets':
        renderBulletsSlide(pptSlide, slide, theme);
        break;
      case 'title_content':
        renderTitleContentSlide(pptSlide, slide, theme);
        break;
      case 'two_column':
        renderTwoColumnSlide(pptSlide, slide, theme);
        break;
      case 'chart':
        renderChartSlide(pptSlide, slide, theme);
        break;
      case 'quote':
        renderQuoteSlide(pptSlide, slide, theme);
        break;
      case 'swot':
        renderSwotSlide(pptSlide, slide, theme);
        break;
      case 'table':
        renderTableSlide(pptSlide, slide, theme);
        break;
      case 'timeline':
        renderTimelineSlide(pptSlide, slide, theme);
        break;
      case 'kpi_grid':
        renderKpiGridSlide(pptSlide, slide, theme);
        break;
      case 'mindmap':
        renderMindmapSlide(pptSlide, slide, theme);
        break;
      case 'process':
        renderProcessSlide(pptSlide, slide, theme);
        break;
      case 'gallery':
        renderGallerySlide(pptSlide, slide, theme);
        break;
      case 'image_text':
        renderImageTextSlide(pptSlide, slide, theme);
        break;
      default:
        renderTitleContentSlide(pptSlide, slide, theme);
    }
  }
  
  // Download the file
  const fileName = `${presentation.title.replace(/[^a-zA-Z0-9\u4e00-\u9fa5]/g, '_')}.pptx`;
  await pptx.writeFile({ fileName });
}

function renderTitleSlide(slide: any, data: SlideContent, theme: Theme) {
  // Title
  slide.addText(data.title, {
    x: 1.0,
    y: 2.5,
    w: 8.0,
    h: 1.5,
    fontSize: 36,
    fontFace: 'Arial',
    color: theme.colors.primary.replace('#', ''),
    align: 'center',
    bold: true,
  });
  
  // Subtitle
  if (data.subtitle) {
    slide.addText(data.subtitle, {
      x: 1.0,
      y: 4.0,
      w: 8.0,
      h: 0.8,
      fontSize: 18,
      fontFace: 'Arial',
      color: theme.colors.secondary.replace('#', ''),
      align: 'center',
    });
  }
  
  // Accent line
  slide.addShape('rect', {
    x: 4.0,
    y: 5.0,
    w: 2.0,
    h: 0.1,
    fill: { color: theme.colors.accent.replace('#', '') },
  });
}

function renderSectionSlide(slide: any, data: SlideContent, theme: Theme) {
  // Circle with first letter
  slide.addShape('ellipse', {
    x: 4.25,
    y: 1.5,
    w: 1.5,
    h: 1.5,
    fill: { color: theme.colors.primary.replace('#', '') },
  });
  
  slide.addText(data.title.charAt(0), {
    x: 4.25,
    y: 1.5,
    w: 1.5,
    h: 1.5,
    fontSize: 32,
    fontFace: 'Arial',
    color: 'FFFFFF',
    align: 'center',
    valign: 'middle',
    bold: true,
  });
  
  // Title
  slide.addText(data.title, {
    x: 1.0,
    y: 3.5,
    w: 8.0,
    h: 1.0,
    fontSize: 28,
    fontFace: 'Arial',
    color: theme.colors.text.replace('#', ''),
    align: 'center',
    bold: true,
  });
  
  // Subtitle
  if (data.subtitle) {
    slide.addText(data.subtitle, {
      x: 1.0,
      y: 4.5,
      w: 8.0,
      h: 0.6,
      fontSize: 16,
      fontFace: 'Arial',
      color: theme.colors.secondary.replace('#', ''),
      align: 'center',
    });
  }
}

function renderBulletsSlide(slide: any, data: SlideContent, theme: Theme) {
  // Title
  slide.addText(data.title, {
    x: 0.5,
    y: 0.3,
    w: 9.0,
    h: 0.8,
    fontSize: 24,
    fontFace: 'Arial',
    color: theme.colors.primary.replace('#', ''),
    bold: true,
    underline: { type: 'single', color: theme.colors.accent.replace('#', '') },
  });
  
  // Bullets
  if (data.bullets && data.bullets.length > 0) {
    const bulletText = data.bullets.map((b) => ({
      text: b,
      options: {
        bullet: { code: '2022' },
        fontSize: 16,
        fontFace: 'Arial',
        color: theme.colors.text.replace('#', ''),
        breakType: 'none' as const,
        lineSpacingMultiple: 1.5,
      },
    }));
    
    slide.addText(bulletText, {
      x: 0.8,
      y: 1.3,
      w: 8.4,
      h: 4.5,
      valign: 'top',
    });
  }
}

function renderTitleContentSlide(slide: any, data: SlideContent, theme: Theme) {
  // Title
  slide.addText(data.title, {
    x: 0.5,
    y: 0.3,
    w: 9.0,
    h: 0.8,
    fontSize: 24,
    fontFace: 'Arial',
    color: theme.colors.primary.replace('#', ''),
    bold: true,
  });
  
  // Content
  if (data.content) {
    slide.addText(data.content, {
      x: 0.8,
      y: 1.3,
      w: 8.4,
      h: 4.5,
      fontSize: 16,
      fontFace: 'Arial',
      color: theme.colors.text.replace('#', ''),
      valign: 'top',
      lineSpacingMultiple: 1.5,
    });
  }
}

function renderTwoColumnSlide(slide: any, data: SlideContent, theme: Theme) {
  // Title
  slide.addText(data.title, {
    x: 0.5,
    y: 0.3,
    w: 9.0,
    h: 0.8,
    fontSize: 24,
    fontFace: 'Arial',
    color: theme.colors.primary.replace('#', ''),
    bold: true,
  });
  
  // Left column
  if (data.left) {
    slide.addShape('roundRect', {
      x: 0.5,
      y: 1.3,
      w: 4.2,
      h: 4.5,
      fill: { color: lightenColor(theme.colors.primary), type: 'solid' },
      rectRadius: 0.1,
    });
    
    slide.addText(data.left.heading, {
      x: 0.7,
      y: 1.5,
      w: 3.8,
      h: 0.5,
      fontSize: 16,
      fontFace: 'Arial',
      color: theme.colors.primary.replace('#', ''),
      bold: true,
    });
    
    if (data.left.items.length > 0) {
      const leftText = data.left.items.map((item) => ({
        text: `• ${item}`,
        options: {
          fontSize: 12,
          fontFace: 'Arial',
          color: theme.colors.text.replace('#', ''),
          breakType: 'none' as const,
        },
      }));
      
      slide.addText(leftText, {
        x: 0.7,
        y: 2.2,
        w: 3.8,
        h: 3.4,
        valign: 'top',
      });
    }
  }
  
  // Right column
  if (data.right) {
    slide.addShape('roundRect', {
      x: 5.3,
      y: 1.3,
      w: 4.2,
      h: 4.5,
      fill: { color: lightenColor(theme.colors.accent), type: 'solid' },
      rectRadius: 0.1,
    });
    
    slide.addText(data.right.heading, {
      x: 5.5,
      y: 1.5,
      w: 3.8,
      h: 0.5,
      fontSize: 16,
      fontFace: 'Arial',
      color: theme.colors.accent.replace('#', ''),
      bold: true,
    });
    
    if (data.right.items.length > 0) {
      const rightText = data.right.items.map((item) => ({
        text: `• ${item}`,
        options: {
          fontSize: 12,
          fontFace: 'Arial',
          color: theme.colors.text.replace('#', ''),
          breakType: 'none' as const,
        },
      }));
      
      slide.addText(rightText, {
        x: 5.5,
        y: 2.2,
        w: 3.8,
        h: 3.4,
        valign: 'top',
      });
    }
  }
}

function renderChartSlide(slide: any, data: SlideContent, theme: Theme) {
  // Title
  slide.addText(data.title, {
    x: 0.5,
    y: 0.3,
    w: 9.0,
    h: 0.8,
    fontSize: 24,
    fontFace: 'Arial',
    color: theme.colors.primary.replace('#', ''),
    bold: true,
  });
  
  // Chart data
  if (data.chart_data) {
    const maxValue = Math.max(...data.chart_data.values);
    const barWidth = 7.0 / data.chart_data.labels.length;
    
    data.chart_data.labels.forEach((label, i) => {
      const value = data.chart_data!.values[i];
      const barHeight = (value / maxValue) * 3.5;
      const x = 1.0 + i * barWidth + barWidth * 0.2;
      const y = 5.0 - barHeight;
      
      // Bar
      slide.addShape('rect', {
        x,
        y,
        w: barWidth * 0.6,
        h: barHeight,
        fill: {
          color: i % 2 === 0
            ? theme.colors.primary.replace('#', '')
            : theme.colors.accent.replace('#', ''),
        },
      });
      
      // Value label
      slide.addText(String(value), {
        x,
        y: y - 0.3,
        w: barWidth * 0.6,
        h: 0.3,
        fontSize: 10,
        fontFace: 'Arial',
        color: theme.colors.text.replace('#', ''),
        align: 'center',
      });
      
      // Category label
      slide.addText(label, {
        x,
        y: 5.1,
        w: barWidth * 0.6,
        h: 0.4,
        fontSize: 10,
        fontFace: 'Arial',
        color: theme.colors.secondary.replace('#', ''),
        align: 'center',
      });
    });
  }
}

function renderQuoteSlide(slide: any, data: SlideContent, theme: Theme) {
  // Quote mark
  slide.addText('"', {
    x: 1.0,
    y: 1.0,
    w: 2.0,
    h: 1.5,
    fontSize: 72,
    fontFace: 'Georgia',
    color: theme.colors.accent.replace('#', ''),
  });
  
  // Quote text
  slide.addText(data.text || '', {
    x: 1.5,
    y: 2.5,
    w: 7.0,
    h: 2.0,
    fontSize: 18,
    fontFace: 'Georgia',
    color: theme.colors.text.replace('#', ''),
    italic: true,
    align: 'center',
  });
  
  // Author
  if (data.author) {
    slide.addText(`— ${data.author}`, {
      x: 1.5,
      y: 4.8,
      w: 7.0,
      h: 0.5,
      fontSize: 14,
      fontFace: 'Arial',
      color: theme.colors.secondary.replace('#', ''),
      align: 'center',
    });
  }
}

function renderSwotSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const swot = data.swot || { strengths: [], weaknesses: [], opportunities: [], threats: [] };
  const cfg: Record<string, { label: string; color: string; x: number; y: number }> = {
    strengths: { label: 'S 优势', color: '16A34A', x: 0.5, y: 1.2 },
    weaknesses: { label: 'W 劣势', color: 'DC2626', x: 5.0, y: 1.2 },
    opportunities: { label: 'O 机会', color: '2563EB', x: 0.5, y: 3.5 },
    threats: { label: 'T 威胁', color: 'EA580C', x: 5.0, y: 3.5 },
  };
  for (const [key, c] of Object.entries(cfg)) {
    slide.addText(c.label, { x: c.x, y: c.y, w: 4.0, h: 0.4, fontSize: 12, fontFace: 'Arial', color: c.color, bold: true });
    const items = (swot as any)[key] || [];
    slide.addText(items.map((i: string) => `• ${i}`).join('\n'), { x: c.x, y: c.y + 0.4, w: 4.0, h: 1.8, fontSize: 10, fontFace: 'Arial', color: theme.colors.text.replace('#', ''), valign: 'top' });
  }
}

function renderTableSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const headers = data.table_headers || [];
  const rows = data.table_rows || [];
  if (headers.length > 0) {
    const tableRows = [
      headers.map(h => ({ text: h, options: { fontSize: 10, fontFace: 'Arial', color: 'FFFFFF', bold: true, fill: { color: theme.colors.accent.replace('#', '') }, align: 'center' as const } })),
      ...rows.map(row => row.map(cell => ({ text: cell, options: { fontSize: 9, fontFace: 'Arial', color: theme.colors.text.replace('#', '') } }))),
    ];
    slide.addTable(tableRows, { x: 0.5, y: 1.2, w: 9.0, colW: headers.map(() => 9.0 / headers.length), border: { pt: 0.5, color: 'CCCCCC' } });
  }
}

function renderTimelineSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const events = data.events || [];
  slide.addShape('rect', { x: 1.5, y: 1.2, w: 0.05, h: 4.0, fill: { color: theme.colors.accent.replace('#', '') } });
  events.forEach((ev, i) => {
    const y = 1.3 + i * 0.8;
    slide.addShape('ellipse', { x: 1.4, y, w: 0.25, h: 0.25, fill: { color: theme.colors.accent.replace('#', '') } });
    slide.addText(ev.date, { x: 1.8, y, w: 1.5, h: 0.3, fontSize: 9, fontFace: 'Arial', color: theme.colors.accent.replace('#', ''), bold: true });
    slide.addText(ev.title, { x: 3.3, y, w: 6.0, h: 0.3, fontSize: 10, fontFace: 'Arial', color: theme.colors.text.replace('#', '') });
  });
}

function renderKpiGridSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const items = data.kpi_items || [];
  const positions = [{ x: 0.5, y: 1.3 }, { x: 5.0, y: 1.3 }, { x: 0.5, y: 3.5 }, { x: 5.0, y: 3.5 }];
  items.slice(0, 4).forEach((kpi, i) => {
    const pos = positions[i];
    slide.addText(kpi.value, { x: pos.x, y: pos.y, w: 4.0, h: 1.0, fontSize: 32, fontFace: 'Arial', color: theme.colors.accent.replace('#', ''), bold: true, align: 'center' });
    slide.addText(kpi.label, { x: pos.x, y: pos.y + 1.0, w: 4.0, h: 0.4, fontSize: 11, fontFace: 'Arial', color: theme.colors.secondary.replace('#', ''), align: 'center' });
  });
}

function renderMindmapSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  slide.addShape('ellipse', { x: 3.5, y: 2.5, w: 3.0, h: 1.2, fill: { color: theme.colors.accent.replace('#', '') } });
  slide.addText(data.central_topic || data.title, { x: 3.5, y: 2.5, w: 3.0, h: 1.2, fontSize: 14, fontFace: 'Arial', color: 'FFFFFF', align: 'center', valign: 'middle', bold: true });
  const branches = data.branches || [];
  branches.slice(0, 6).forEach((branch, i) => {
    const angle = (i / branches.length) * Math.PI * 2 - Math.PI / 2;
    const cx = 5.0, cy = 3.1, r = 2.5;
    const bx = cx + Math.cos(angle) * r;
    const by = cy + Math.sin(angle) * r;
    slide.addShape('rect', { x: bx - 0.8, y: by - 0.25, w: 1.6, h: 0.5, fill: { color: theme.colors.secondary.replace('#', '') }, rectRadius: 0.1 });
    slide.addText(branch.name, { x: bx - 0.8, y: by - 0.25, w: 1.6, h: 0.5, fontSize: 8, fontFace: 'Arial', color: 'FFFFFF', align: 'center', valign: 'middle' });
  });
}

function renderProcessSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const steps = data.steps || [];
  const stepW = 8.0 / Math.max(steps.length, 1);
  steps.forEach((step, i) => {
    const x = 1.0 + i * stepW;
    slide.addShape('ellipse', { x: x + stepW / 2 - 0.3, y: 2.5, w: 0.6, h: 0.6, fill: { color: theme.colors.accent.replace('#', '') } });
    slide.addText(`${i + 1}`, { x: x + stepW / 2 - 0.3, y: 2.5, w: 0.6, h: 0.6, fontSize: 12, fontFace: 'Arial', color: 'FFFFFF', align: 'center', valign: 'middle', bold: true });
    slide.addText(step.title, { x, y: 3.3, w: stepW, h: 0.4, fontSize: 10, fontFace: 'Arial', color: theme.colors.text.replace('#', ''), align: 'center', bold: true });
    if (i < steps.length - 1) {
      slide.addText('→', { x: x + stepW - 0.3, y: 2.5, w: 0.6, h: 0.6, fontSize: 14, fontFace: 'Arial', color: theme.colors.accent.replace('#', ''), align: 'center', valign: 'middle' });
    }
  });
}

function renderGallerySlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  const images = data.images || [];
  const positions = [{ x: 0.5, y: 1.2 }, { x: 5.0, y: 1.2 }, { x: 0.5, y: 3.5 }, { x: 5.0, y: 3.5 }];
  images.slice(0, 4).forEach((img, i) => {
    const pos = positions[i];
    slide.addShape('rect', { x: pos.x, y: pos.y, w: 4.0, h: 1.8, fill: { color: 'F0F0F0' }, rectRadius: 0.1 });
    if (img.caption) {
      slide.addText(img.caption, { x: pos.x, y: pos.y + 1.8, w: 4.0, h: 0.3, fontSize: 8, fontFace: 'Arial', color: theme.colors.secondary.replace('#', ''), align: 'center' });
    }
  });
}

function renderImageTextSlide(slide: any, data: SlideContent, theme: Theme) {
  slide.addText(data.title, { x: 0.5, y: 0.3, w: 9.0, h: 0.6, fontSize: 20, fontFace: 'Arial', color: theme.colors.primary.replace('#', ''), bold: true });
  slide.addShape('rect', { x: 0.5, y: 1.2, w: 4.0, h: 4.0, fill: { color: 'F0F0F0' }, rectRadius: 0.1 });
  if (data.content) {
    slide.addText(data.content, { x: 5.0, y: 1.2, w: 4.5, h: 4.0, fontSize: 11, fontFace: 'Arial', color: theme.colors.text.replace('#', ''), valign: 'top' });
  }
}

export default exportToPptx;
