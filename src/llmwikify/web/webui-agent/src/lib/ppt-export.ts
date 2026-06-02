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
      fill: { color: theme.colors.primary.replace('#', ''), type: 'solid' },
      rectRadius: 0.1,
    });
    
    slide.addText(data.left.heading, {
      x: 0.7,
      y: 1.5,
      w: 3.8,
      h: 0.5,
      fontSize: 16,
      fontFace: 'Arial',
      color: 'FFFFFF',
      bold: true,
    });
    
    if (data.left.items.length > 0) {
      const leftText = data.left.items.map((item) => ({
        text: `• ${item}`,
        options: {
          fontSize: 12,
          fontFace: 'Arial',
          color: 'FFFFFF',
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
      fill: { color: theme.colors.accent.replace('#', ''), type: 'solid' },
      rectRadius: 0.1,
    });
    
    slide.addText(data.right.heading, {
      x: 5.5,
      y: 1.5,
      w: 3.8,
      h: 0.5,
      fontSize: 16,
      fontFace: 'Arial',
      color: 'FFFFFF',
      bold: true,
    });
    
    if (data.right.items.length > 0) {
      const rightText = data.right.items.map((item) => ({
        text: `• ${item}`,
        options: {
          fontSize: 12,
          fontFace: 'Arial',
          color: 'FFFFFF',
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

export default exportToPptx;
