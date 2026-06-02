"""PPT Generator - Preset theme configurations.

v0.6.1: Expanded from 8 to 36 themes by adopting the CSS-token system from
html-ppt-skill (https://github.com/lewislulu/html-ppt-skill, MIT, 5.4k ⭐).

Each theme is a `Theme` Pydantic model with:
- id: canonical identifier (e.g. "minimal-white")
- name_zh / name_en: user-facing labels
- category: minimal|soft|warm|cool|dark|colorful|tech|brand|design|retro
- description: 50-100 char usage hint
- tokens: dict of CSS custom properties (color-*, font-*, radius-*, shadow-*, gradient-*)
- colors: legacy 5-color palette derived from tokens (backward compat with v0.5)

Legacy v0.5 theme IDs (professional, modern, minimal, nature, warm, dark, academic, creative)
are aliased to their closest html-ppt-skill equivalent — existing user data
and API requests with old IDs continue to work.

Attribution: theme tokens are adapted from html-ppt-skill (MIT, © 2026 lewislulu).
"""

from typing import Dict, List
from .schema import Theme, ThemeColors


# ============================================================================
# 36 v0.6.1 themes (adapted from html-ppt-skill)
# ============================================================================

THEMES: Dict[str, Theme] = {
    "minimal-white": Theme(
        id="minimal-white",
        name="Minimal White",
        name_zh="极简白",
        name_en="Minimal White",
        label="Minimal White",
        category="minimal",
        description="克制高级的纯白底，黑灰主调，适合商务汇报、产品发布。",
        tokens={"color-bg": "#ffffff", "color-bg-soft": "#fafafa", "color-surface": "#ffffff", "color-surface-2": "#f5f5f6", "color-border": "rgba(17,18,22,.08)", "color-border-strong": "rgba(17,18,22,.16)", "color-text-1": "#0c0d10", "color-text-2": "#55596a", "color-text-3": "#9ca1b0", "color-accent": "#111216", "color-accent-2": "#3b3f4a", "color-accent-3": "#6b6f7a", "color-good": "#1aaf6c", "color-warn": "#c98500", "color-bad": "#c13a3a", "gradient-primary": "linear-gradient(135deg,#111216,#3b3f4a)", "gradient-soft": "linear-gradient(135deg,#f5f5f6,#ffffff)", "radius-md": "14px", "radius-sm": "8px", "radius-lg": "22px", "shadow-md": "0 1px 2px rgba(17,18,22,.04),0 8px 24px rgba(17,18,22,.06)", "shadow-lg": "0 20px 60px rgba(17,18,22,.1)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.035em"},
        colors=ThemeColors(
            primary="#111216",
            secondary="#3b3f4a",
            background="#ffffff",
            text="#0c0d10",
            accent="#6b6f7a",
        ),
    ),
    "editorial-serif": Theme(
        id="editorial-serif",
        name="Editorial Serif",
        name_zh="编辑衬线",
        name_en="Editorial Serif",
        label="Editorial Serif",
        category="minimal",
        description="杂志编辑风，衬线字体，浓郁文学气息，适合品牌故事、深度长文。",
        tokens={"color-bg": "#fbf8f3", "color-bg-soft": "#f3eee4", "color-surface": "#ffffff", "color-surface-2": "#f7f2e8", "color-border": "rgba(20,16,8,.14)", "color-border-strong": "rgba(20,16,8,.32)", "color-text-1": "#18130a", "color-text-2": "#423a2a", "color-text-3": "#8a7e66", "color-accent": "#a8321a", "color-accent-2": "#3a2e10", "color-accent-3": "#7a4a1a", "color-good": "#3a6a2a", "color-warn": "#a86a1a", "color-bad": "#a82a2a", "gradient-primary": "linear-gradient(135deg,#a8321a,#3a2e10)", "gradient-soft": "linear-gradient(135deg,#f3eee4,#fbf8f3)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "4px", "shadow-md": "0 1px 0 rgba(20,16,8,.08)", "shadow-lg": "0 10px 30px rgba(20,16,8,.12)", "font-body": "'Playfair Display','Noto Serif SC',Georgia,serif", "font-heading": "'Playfair Display','Noto Serif SC',Georgia,serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#a8321a",
            secondary="#3a2e10",
            background="#fbf8f3",
            text="#18130a",
            accent="#7a4a1a",
        ),
    ),
    "soft-pastel": Theme(
        id="soft-pastel",
        name="Soft Pastel",
        name_zh="柔和粉彩",
        name_en="Soft Pastel",
        label="Soft Pastel",
        category="soft",
        description="马卡龙粉彩色调，温柔治愈，适合女性产品、生活方式、儿童教育。",
        tokens={"color-bg": "#fdf6f9", "color-bg-soft": "#f6ecf0", "color-surface": "#ffffff", "color-surface-2": "#faf0f4", "color-border": "rgba(160,90,120,.18)", "color-border-strong": "rgba(160,90,120,.36)", "color-text-1": "#3a2530", "color-text-2": "#5a3a48", "color-text-3": "#9a7a8a", "color-accent": "#e58fb3", "color-accent-2": "#a08ac4", "color-accent-3": "#7ac4c0", "color-good": "#7ac4a0", "color-warn": "#e5c08a", "color-bad": "#e58f8f", "gradient-primary": "linear-gradient(135deg,#e58fb3,#a08ac4)", "gradient-soft": "linear-gradient(135deg,#faf0f4,#fdf6f9)", "radius-md": "18px", "radius-sm": "12px", "radius-lg": "26px", "shadow-md": "0 4px 14px rgba(160,90,120,.1)", "shadow-lg": "0 16px 40px rgba(160,90,120,.16)", "font-body": "'Quicksand','Noto Sans SC',sans-serif", "font-heading": "'Quicksand','Noto Sans SC',sans-serif", "letter-tight": "-.01em"},
        colors=ThemeColors(
            primary="#e58fb3",
            secondary="#a08ac4",
            background="#fdf6f9",
            text="#3a2530",
            accent="#7ac4c0",
        ),
    ),
    "sharp-mono": Theme(
        id="sharp-mono",
        name="Sharp Mono",
        name_zh="锋利单色",
        name_en="Sharp Mono",
        label="Sharp Mono",
        category="minimal",
        description="极致单色高对比，工程感强，适合技术文档、API 演示。",
        tokens={"color-bg": "#fafafa", "color-bg-soft": "#f0f0f0", "color-surface": "#ffffff", "color-surface-2": "#f5f5f5", "color-border": "rgba(0,0,0,.85)", "color-border-strong": "rgba(0,0,0,1)", "color-text-1": "#0a0a0a", "color-text-2": "#2a2a2a", "color-text-3": "#7a7a7a", "color-accent": "#000000", "color-accent-2": "#404040", "color-accent-3": "#707070", "color-good": "#1a8a3a", "color-warn": "#a87a1a", "color-bad": "#a82a2a", "gradient-primary": "linear-gradient(135deg,#000000,#404040)", "gradient-soft": "linear-gradient(135deg,#f0f0f0,#fafafa)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "none", "shadow-lg": "0 1px 0 #000", "font-body": "'JetBrains Mono','IBM Plex Mono',monospace", "font-heading": "'JetBrains Mono','IBM Plex Mono',monospace", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#000000",
            secondary="#404040",
            background="#fafafa",
            text="#0a0a0a",
            accent="#707070",
        ),
    ),
    "arctic-cool": Theme(
        id="arctic-cool",
        name="Arctic Cool",
        name_zh="北极冷色",
        name_en="Arctic Cool",
        label="Arctic Cool",
        category="cool",
        description="冰蓝极地色调，清爽冷峻，适合科技企业、数据可视化。",
        tokens={"color-bg": "#f0f7fa", "color-bg-soft": "#e1eef4", "color-surface": "#ffffff", "color-surface-2": "#e8f1f5", "color-border": "rgba(40,90,120,.16)", "color-border-strong": "rgba(40,90,120,.36)", "color-text-1": "#0a1f2a", "color-text-2": "#1f3a4a", "color-text-3": "#6a8a9a", "color-accent": "#1a8ac4", "color-accent-2": "#0a4a7a", "color-accent-3": "#5ac4d4", "color-good": "#1a8a5a", "color-warn": "#c4a81a", "color-bad": "#c43a3a", "gradient-primary": "linear-gradient(135deg,#1a8ac4,#0a4a7a)", "gradient-soft": "linear-gradient(135deg,#e8f1f5,#f0f7fa)", "radius-md": "10px", "radius-sm": "6px", "radius-lg": "18px", "shadow-md": "0 4px 14px rgba(40,90,120,.12)", "shadow-lg": "0 16px 40px rgba(40,90,120,.18)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#1a8ac4",
            secondary="#0a4a7a",
            background="#f0f7fa",
            text="#0a1f2a",
            accent="#5ac4d4",
        ),
    ),
    "sunset-warm": Theme(
        id="sunset-warm",
        name="Sunset Warm",
        name_zh="日落暖色",
        name_en="Sunset Warm",
        label="Sunset Warm",
        category="warm",
        description="橙黄日落渐变，温暖活力，适合营销推广、节日主题。",
        tokens={"color-bg": "#fff7f0", "color-bg-soft": "#fceedc", "color-surface": "#ffffff", "color-surface-2": "#fdf0e0", "color-border": "rgba(180,90,30,.18)", "color-border-strong": "rgba(180,90,30,.36)", "color-text-1": "#2a180a", "color-text-2": "#4a2e1a", "color-text-3": "#8a6a4a", "color-accent": "#ea580c", "color-accent-2": "#c43a1a", "color-accent-3": "#f9a06b", "color-good": "#4a8a3a", "color-warn": "#c47a1a", "color-bad": "#c43a3a", "gradient-primary": "linear-gradient(135deg,#ea580c,#c43a1a)", "gradient-soft": "linear-gradient(135deg,#fdf0e0,#fff7f0)", "radius-md": "14px", "radius-sm": "8px", "radius-lg": "22px", "shadow-md": "0 6px 18px rgba(180,90,30,.14)", "shadow-lg": "0 18px 40px rgba(180,90,30,.2)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#ea580c",
            secondary="#c43a1a",
            background="#fff7f0",
            text="#2a180a",
            accent="#f9a06b",
        ),
    ),
    "catppuccin-latte": Theme(
        id="catppuccin-latte",
        name="Catppuccin Latte",
        name_zh="卡布奇诺·拿铁",
        name_en="Catppuccin Latte",
        label="Catppuccin Latte",
        category="colorful",
        description="温和米色底 + 柔粉抹茶色，开发者友好的暖色系。",
        tokens={"color-bg": "#eff1f5", "color-bg-soft": "#e6e9ef", "color-surface": "#ffffff", "color-surface-2": "#e6e9ef", "color-border": "rgba(140,140,160,.2)", "color-border-strong": "rgba(140,140,160,.4)", "color-text-1": "#4c4f69", "color-text-2": "#5c5f77", "color-text-3": "#8c8fa1", "color-accent": "#8839ef", "color-accent-2": "#ea76cb", "color-accent-3": "#40a02b", "color-good": "#40a02b", "color-warn": "#df8e1d", "color-bad": "#d20f39", "gradient-primary": "linear-gradient(135deg,#8839ef,#ea76cb 55%,#40a02b)", "gradient-soft": "linear-gradient(135deg,#e6e9ef,#eff1f5)", "radius-md": "12px", "radius-sm": "8px", "radius-lg": "18px", "shadow-md": "0 6px 16px rgba(76,79,105,.08)", "shadow-lg": "0 16px 40px rgba(76,79,105,.14)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#8839ef",
            secondary="#ea76cb",
            background="#eff1f5",
            text="#4c4f69",
            accent="#40a02b",
        ),
    ),
    "catppuccin-mocha": Theme(
        id="catppuccin-mocha",
        name="Catppuccin Mocha",
        name_zh="卡布奇诺·摩卡",
        name_en="Catppuccin Mocha",
        label="Catppuccin Mocha",
        category="dark",
        description="深棕底 + 蓝紫粉绿点缀，开发者最爱的暗色主题。",
        tokens={"color-bg": "#1e1e2e", "color-bg-soft": "#181825", "color-surface": "#313244", "color-surface-2": "#45475a", "color-border": "rgba(205,214,244,.12)", "color-border-strong": "rgba(205,214,244,.24)", "color-text-1": "#cdd6f4", "color-text-2": "#bac2de", "color-text-3": "#7f849c", "color-accent": "#cba6f7", "color-accent-2": "#f5c2e7", "color-accent-3": "#94e2d5", "color-good": "#a6e3a1", "color-warn": "#f9e2af", "color-bad": "#f38ba8", "gradient-primary": "linear-gradient(135deg,#cba6f7,#f5c2e7 55%,#94e2d5)", "gradient-soft": "linear-gradient(135deg,#313244,#45475a)", "radius-md": "12px", "radius-sm": "8px", "radius-lg": "18px", "shadow-md": "0 10px 30px rgba(0,0,0,.4)", "shadow-lg": "0 22px 60px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#cba6f7",
            secondary="#f5c2e7",
            background="#1e1e2e",
            text="#cdd6f4",
            accent="#94e2d5",
        ),
    ),
    "dracula": Theme(
        id="dracula",
        name="Dracula",
        name_zh="德古拉",
        name_en="Dracula",
        label="Dracula",
        category="dark",
        description="经典紫色暗色，开发者圈最流行，适合技术分享、代码演示。",
        tokens={"color-bg": "#282a36", "color-bg-soft": "#21222c", "color-surface": "#343746", "color-surface-2": "#44475a", "color-border": "rgba(248,248,242,.12)", "color-border-strong": "rgba(248,248,242,.24)", "color-text-1": "#f8f8f2", "color-text-2": "#bdbde0", "color-text-3": "#6272a4", "color-accent": "#bd93f9", "color-accent-2": "#ff79c6", "color-accent-3": "#8be9fd", "color-good": "#50fa7b", "color-warn": "#f1fa8c", "color-bad": "#ff5555", "gradient-primary": "linear-gradient(135deg,#bd93f9,#ff79c6 55%,#8be9fd)", "gradient-soft": "linear-gradient(135deg,#343746,#44475a)", "radius-md": "12px", "radius-sm": "8px", "radius-lg": "18px", "shadow-md": "0 10px 30px rgba(0,0,0,.4)", "shadow-lg": "0 22px 60px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#bd93f9",
            secondary="#ff79c6",
            background="#282a36",
            text="#f8f8f2",
            accent="#8be9fd",
        ),
    ),
    "tokyo-night": Theme(
        id="tokyo-night",
        name="Tokyo Night",
        name_zh="东京之夜",
        name_en="Tokyo Night",
        label="Tokyo Night",
        category="dark",
        description="霓虹蓝紫深夜风，City Pop 氛围，适合技术演讲。",
        tokens={"color-bg": "#1a1b26", "color-bg-soft": "#16161e", "color-surface": "#24283b", "color-surface-2": "#2f3447", "color-border": "rgba(192,202,245,.12)", "color-border-strong": "rgba(192,202,245,.24)", "color-text-1": "#c0caf5", "color-text-2": "#a9b1d6", "color-text-3": "#565f89", "color-accent": "#7aa2f7", "color-accent-2": "#bb9af7", "color-accent-3": "#7dcfff", "color-good": "#9ece6a", "color-warn": "#e0af68", "color-bad": "#f7768e", "gradient-primary": "linear-gradient(135deg,#7aa2f7,#bb9af7 55%,#7dcfff)", "gradient-soft": "linear-gradient(135deg,#24283b,#2f3447)", "radius-md": "10px", "radius-sm": "6px", "radius-lg": "16px", "shadow-md": "0 10px 30px rgba(0,0,0,.4)", "shadow-lg": "0 22px 60px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#7aa2f7",
            secondary="#bb9af7",
            background="#1a1b26",
            text="#c0caf5",
            accent="#7dcfff",
        ),
    ),
    "nord": Theme(
        id="nord",
        name="Nord",
        name_zh="北方",
        name_en="Nord",
        label="Nord",
        category="colorful",
        description="极地冷色调 + 绿松石点缀，北欧极简风。",
        tokens={"color-bg": "#eceff4", "color-bg-soft": "#e5e9f0", "color-surface": "#ffffff", "color-surface-2": "#e5e9f0", "color-border": "rgba(76,86,106,.18)", "color-border-strong": "rgba(76,86,106,.36)", "color-text-1": "#2e3440", "color-text-2": "#3b4252", "color-text-3": "#7b88a1", "color-accent": "#5e81ac", "color-accent-2": "#88c0d0", "color-accent-3": "#a3be8c", "color-good": "#a3be8c", "color-warn": "#ebcb8b", "color-bad": "#bf616a", "gradient-primary": "linear-gradient(135deg,#5e81ac,#88c0d0 55%,#a3be8c)", "gradient-soft": "linear-gradient(135deg,#e5e9f0,#eceff4)", "radius-md": "8px", "radius-sm": "4px", "radius-lg": "14px", "shadow-md": "0 4px 12px rgba(46,52,64,.08)", "shadow-lg": "0 14px 36px rgba(46,52,64,.14)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#5e81ac",
            secondary="#88c0d0",
            background="#eceff4",
            text="#2e3440",
            accent="#a3be8c",
        ),
    ),
    "solarized-light": Theme(
        id="solarized-light",
        name="Solarized Light",
        name_zh="日晒·明",
        name_en="Solarized Light",
        label="Solarized Light",
        category="colorful",
        description="经典护眼浅色，学术、文档首选。",
        tokens={"color-bg": "#fdf6e3", "color-bg-soft": "#eee8d5", "color-surface": "#ffffff", "color-surface-2": "#f5efdc", "color-border": "rgba(101,123,131,.18)", "color-border-strong": "rgba(101,123,131,.36)", "color-text-1": "#073642", "color-text-2": "#586e75", "color-text-3": "#93a1a1", "color-accent": "#268bd2", "color-accent-2": "#d33682", "color-accent-3": "#2aa198", "color-good": "#859900", "color-warn": "#b58900", "color-bad": "#dc322f", "gradient-primary": "linear-gradient(135deg,#268bd2,#2aa198)", "gradient-soft": "linear-gradient(135deg,#f5efdc,#fdf6e3)", "radius-md": "6px", "radius-sm": "4px", "radius-lg": "10px", "shadow-md": "0 2px 6px rgba(7,54,66,.08)", "shadow-lg": "0 8px 20px rgba(7,54,66,.12)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#268bd2",
            secondary="#d33682",
            background="#fdf6e3",
            text="#073642",
            accent="#2aa198",
        ),
    ),
    "gruvbox-dark": Theme(
        id="gruvbox-dark",
        name="Gruvbox Dark",
        name_zh="Gruvbox·暗",
        name_en="Gruvbox Dark",
        label="Gruvbox Dark",
        category="dark",
        description="复古暖色暗色，护眼奶油色调。",
        tokens={"color-bg": "#282828", "color-bg-soft": "#1d2021", "color-surface": "#3c3836", "color-surface-2": "#504945", "color-border": "rgba(235,219,178,.12)", "color-border-strong": "rgba(235,219,178,.24)", "color-text-1": "#ebdbb2", "color-text-2": "#d5c4a1", "color-text-3": "#a89984", "color-accent": "#fabd2f", "color-accent-2": "#fe8019", "color-accent-3": "#b8bb26", "color-good": "#b8bb26", "color-warn": "#fabd2f", "color-bad": "#fb4934", "gradient-primary": "linear-gradient(135deg,#fabd2f,#fe8019 55%,#b8bb26)", "gradient-soft": "linear-gradient(135deg,#3c3836,#504945)", "radius-md": "6px", "radius-sm": "4px", "radius-lg": "12px", "shadow-md": "0 6px 18px rgba(0,0,0,.4)", "shadow-lg": "0 18px 44px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#fabd2f",
            secondary="#fe8019",
            background="#282828",
            text="#ebdbb2",
            accent="#b8bb26",
        ),
    ),
    "rose-pine": Theme(
        id="rose-pine",
        name="Rosé Pine",
        name_zh="玫瑰松",
        name_en="Rosé Pine",
        label="Rosé Pine",
        category="dark",
        description="玫瑰金 + 松绿，温柔暗色系。",
        tokens={"color-bg": "#191724", "color-bg-soft": "#1f1d2e", "color-surface": "#26233a", "color-surface-2": "#2a273f", "color-border": "rgba(224,222,244,.12)", "color-border-strong": "rgba(224,222,244,.24)", "color-text-1": "#e0def4", "color-text-2": "#c4c0d8", "color-text-3": "#6e6a86", "color-accent": "#ebbcba", "color-accent-2": "#31748f", "color-accent-3": "#9ccfd8", "color-good": "#9ccfd8", "color-warn": "#f6c177", "color-bad": "#eb6f92", "gradient-primary": "linear-gradient(135deg,#ebbcba,#9ccfd8 55%,#c4a7e7)", "gradient-soft": "linear-gradient(135deg,#26233a,#2a273f)", "radius-md": "10px", "radius-sm": "6px", "radius-lg": "16px", "shadow-md": "0 6px 18px rgba(0,0,0,.4)", "shadow-lg": "0 18px 44px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif"},
        colors=ThemeColors(
            primary="#ebbcba",
            secondary="#31748f",
            background="#191724",
            text="#e0def4",
            accent="#9ccfd8",
        ),
    ),
    "neo-brutalism": Theme(
        id="neo-brutalism",
        name="Neo Brutalism",
        name_zh="新粗野",
        name_en="Neo Brutalism",
        label="Neo Brutalism",
        category="design",
        description="硬边粗黑描边、高饱和原色，2025 设计潮流。",
        tokens={"color-bg": "#fef3c7", "color-bg-soft": "#fde68a", "color-surface": "#ffffff", "color-surface-2": "#fef3c7", "color-border": "#0a0a0a", "color-border-strong": "#0a0a0a", "color-text-1": "#0a0a0a", "color-text-2": "#1a1a1a", "color-text-3": "#3a3a3a", "color-accent": "#f472b6", "color-accent-2": "#22d3ee", "color-accent-3": "#a3e635", "color-good": "#22c55e", "color-warn": "#f59e0b", "color-bad": "#ef4444", "gradient-primary": "linear-gradient(135deg,#f472b6,#22d3ee)", "gradient-soft": "linear-gradient(135deg,#fde68a,#fef3c7)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "6px 6px 0 #0a0a0a", "shadow-lg": "12px 12px 0 #0a0a0a", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.04em"},
        colors=ThemeColors(
            primary="#f472b6",
            secondary="#22d3ee",
            background="#fef3c7",
            text="#0a0a0a",
            accent="#a3e635",
        ),
    ),
    "glassmorphism": Theme(
        id="glassmorphism",
        name="Glassmorphism",
        name_zh="玻璃拟物",
        name_en="Glassmorphism",
        label="Glassmorphism",
        category="design",
        description="毛玻璃 + 渐变背景，macOS Big Sur 风。",
        tokens={"color-bg": "#1a1033", "color-bg-soft": "#0f0820", "color-surface": "rgba(255,255,255,.12)", "color-surface-2": "rgba(255,255,255,.18)", "color-border": "rgba(255,255,255,.2)", "color-border-strong": "rgba(255,255,255,.4)", "color-text-1": "#ffffff", "color-text-2": "rgba(255,255,255,.85)", "color-text-3": "rgba(255,255,255,.6)", "color-accent": "#a78bfa", "color-accent-2": "#22d3ee", "color-accent-3": "#f472b6", "color-good": "#86efac", "color-warn": "#fde68a", "color-bad": "#fca5a5", "gradient-primary": "linear-gradient(135deg,#a78bfa,#22d3ee 50%,#f472b6)", "gradient-soft": "linear-gradient(135deg,rgba(167,139,250,.2),rgba(34,211,238,.2))", "radius-md": "20px", "radius-sm": "12px", "radius-lg": "32px", "shadow-md": "0 8px 32px rgba(0,0,0,.18)", "shadow-lg": "0 20px 60px rgba(0,0,0,.3)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#a78bfa",
            secondary="#22d3ee",
            background="#1a1033",
            text="#ffffff",
            accent="#f472b6",
        ),
    ),
    "bauhaus": Theme(
        id="bauhaus",
        name="Bauhaus",
        name_zh="包豪斯",
        name_en="Bauhaus",
        label="Bauhaus",
        category="design",
        description="包豪斯几何 + 红黄蓝原色，经典现代主义。",
        tokens={"color-bg": "#f5f1e8", "color-bg-soft": "#e8e2d0", "color-surface": "#ffffff", "color-surface-2": "#faf6ec", "color-border": "rgba(20,16,8,.85)", "color-border-strong": "rgba(20,16,8,1)", "color-text-1": "#1a1610", "color-text-2": "#3a352a", "color-text-3": "#7a7060", "color-accent": "#d92020", "color-accent-2": "#0a4ac4", "color-accent-3": "#f9c80e", "color-good": "#1a8a3a", "color-warn": "#f9c80e", "color-bad": "#d92020", "gradient-primary": "linear-gradient(135deg,#d92020,#0a4ac4 50%,#f9c80e)", "gradient-soft": "linear-gradient(135deg,#faf6ec,#f5f1e8)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "4px 4px 0 #1a1610", "shadow-lg": "8px 8px 0 #1a1610", "font-body": "'Futura','Arial Black','Noto Sans SC',sans-serif", "font-heading": "'Futura','Arial Black','Noto Sans SC',sans-serif", "letter-tight": "-.04em"},
        colors=ThemeColors(
            primary="#d92020",
            secondary="#0a4ac4",
            background="#f5f1e8",
            text="#1a1610",
            accent="#f9c80e",
        ),
    ),
    "swiss-grid": Theme(
        id="swiss-grid",
        name="Swiss Grid",
        name_zh="瑞士网格",
        name_en="Swiss Grid",
        label="Swiss Grid",
        category="design",
        description="瑞士国际主义平面设计风，网格严谨、信息优先。",
        tokens={"color-bg": "#f5f5f0", "color-bg-soft": "#eaeae0", "color-surface": "#ffffff", "color-surface-2": "#f0f0e8", "color-border": "rgba(20,20,20,.12)", "color-border-strong": "rgba(20,20,20,.85)", "color-text-1": "#0a0a0a", "color-text-2": "#2a2a2a", "color-text-3": "#6a6a6a", "color-accent": "#d92020", "color-accent-2": "#0a0a0a", "color-accent-3": "#4a4a4a", "color-good": "#1a8a3a", "color-warn": "#d97a1a", "color-bad": "#d92020", "gradient-primary": "linear-gradient(135deg,#d92020,#0a0a0a)", "gradient-soft": "linear-gradient(135deg,#f0f0e8,#f5f5f0)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "none", "shadow-lg": "none", "font-body": "'Helvetica Neue','Arial','Noto Sans SC',sans-serif", "font-heading": "'Helvetica Neue','Arial Black','Noto Sans SC',sans-serif", "letter-tight": "-.04em"},
        colors=ThemeColors(
            primary="#d92020",
            secondary="#0a0a0a",
            background="#f5f5f0",
            text="#0a0a0a",
            accent="#4a4a4a",
        ),
    ),
    "terminal-green": Theme(
        id="terminal-green",
        name="Terminal Green",
        name_zh="终端绿",
        name_en="Terminal Green",
        label="Terminal Green",
        category="tech",
        description="经典黑底绿字终端，怀旧黑客风。",
        tokens={"color-bg": "#0a0e0a", "color-bg-soft": "#050805", "color-surface": "#0f140f", "color-surface-2": "#141a14", "color-border": "rgba(51,255,51,.25)", "color-border-strong": "rgba(51,255,51,.5)", "color-text-1": "#33ff66", "color-text-2": "#33cc55", "color-text-3": "#1a8033", "color-accent": "#33ff66", "color-accent-2": "#66ffaa", "color-accent-3": "#aaffaa", "color-good": "#33ff66", "color-warn": "#ffcc33", "color-bad": "#ff3355", "gradient-primary": "linear-gradient(135deg,#33ff66,#1a8033)", "gradient-soft": "linear-gradient(135deg,#0f140f,#141a14)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "0 0 12px rgba(51,255,51,.25)", "shadow-lg": "0 0 30px rgba(51,255,51,.4)", "font-body": "'JetBrains Mono','IBM Plex Mono','Courier New',monospace", "font-heading": "'JetBrains Mono','IBM Plex Mono','Courier New',monospace"},
        colors=ThemeColors(
            primary="#33ff66",
            secondary="#66ffaa",
            background="#0a0e0a",
            text="#33ff66",
            accent="#aaffaa",
        ),
    ),
    "xiaohongshu-white": Theme(
        id="xiaohongshu-white",
        name="Xiaohongshu White",
        name_zh="小红书白",
        name_en="Xiaohongshu White",
        label="Xiaohongshu White",
        category="soft",
        description="小红书白底杂志风，柔光美妆种草。",
        tokens={"color-bg": "#fffbf5", "color-bg-soft": "#fdf3e8", "color-surface": "#ffffff", "color-surface-2": "#fff7ec", "color-border": "rgba(180,120,80,.14)", "color-border-strong": "rgba(180,120,80,.32)", "color-text-1": "#2a201a", "color-text-2": "#5a4a3a", "color-text-3": "#8a7a6a", "color-accent": "#e85a4a", "color-accent-2": "#f4a06a", "color-accent-3": "#c4a06a", "color-good": "#7ac46a", "color-warn": "#e8a83a", "color-bad": "#e85a4a", "gradient-primary": "linear-gradient(135deg,#e85a4a,#f4a06a)", "gradient-soft": "linear-gradient(135deg,#fff7ec,#fffbf5)", "radius-md": "16px", "radius-sm": "10px", "radius-lg": "24px", "shadow-md": "0 4px 14px rgba(180,120,80,.1)", "shadow-lg": "0 14px 36px rgba(180,120,80,.16)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#e85a4a",
            secondary="#f4a06a",
            background="#fffbf5",
            text="#2a201a",
            accent="#c4a06a",
        ),
    ),
    "rainbow-gradient": Theme(
        id="rainbow-gradient",
        name="Rainbow Gradient",
        name_zh="彩虹渐变",
        name_en="Rainbow Gradient",
        label="Rainbow Gradient",
        category="colorful",
        description="彩虹色全色谱渐变，年轻潮流。",
        tokens={"color-bg": "#0a0a14", "color-bg-soft": "#05050a", "color-surface": "#15151f", "color-surface-2": "#1f1f2a", "color-border": "rgba(255,255,255,.1)", "color-border-strong": "rgba(255,255,255,.25)", "color-text-1": "#ffffff", "color-text-2": "rgba(255,255,255,.85)", "color-text-3": "rgba(255,255,255,.6)", "color-accent": "#ff2bd6", "color-accent-2": "#00f0ff", "color-accent-3": "#ffd700", "color-good": "#39ff14", "color-warn": "#ffd700", "color-bad": "#ff2bd6", "gradient-primary": "linear-gradient(90deg,#ff0080,#ff8c00 20%,#ffd700 40%,#00ff80 60%,#00d4ff 80%,#a020f0)", "gradient-soft": "linear-gradient(135deg,rgba(255,0,128,.15),rgba(0,212,255,.15))", "radius-md": "16px", "radius-sm": "10px", "radius-lg": "26px", "shadow-md": "0 8px 24px rgba(0,0,0,.4)", "shadow-lg": "0 20px 50px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.03em"},
        colors=ThemeColors(
            primary="#ff2bd6",
            secondary="#00f0ff",
            background="#0a0a14",
            text="#ffffff",
            accent="#ffd700",
        ),
    ),
    "aurora": Theme(
        id="aurora",
        name="Aurora",
        name_zh="极光",
        name_en="Aurora",
        label="Aurora",
        category="cool",
        description="极光渐变，青绿紫蓝梦幻。",
        tokens={"color-bg": "#0a1628", "color-bg-soft": "#050b14", "color-surface": "#0f1d3a", "color-surface-2": "#16264a", "color-border": "rgba(100,200,200,.2)", "color-border-strong": "rgba(100,200,200,.4)", "color-text-1": "#e0f0ff", "color-text-2": "#a0c0e0", "color-text-3": "#6080a0", "color-accent": "#3affbf", "color-accent-2": "#7a8aff", "color-accent-3": "#ff7ad4", "color-good": "#3affbf", "color-warn": "#ffd700", "color-bad": "#ff5a8a", "gradient-primary": "linear-gradient(135deg,#3affbf 0%,#7a8aff 50%,#ff7ad4 100%)", "gradient-soft": "linear-gradient(135deg,rgba(58,255,191,.15),rgba(122,138,255,.15))", "radius-md": "14px", "radius-sm": "8px", "radius-lg": "22px", "shadow-md": "0 8px 28px rgba(58,255,191,.2)", "shadow-lg": "0 20px 60px rgba(58,255,191,.3)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#3affbf",
            secondary="#7a8aff",
            background="#0a1628",
            text="#e0f0ff",
            accent="#ff7ad4",
        ),
    ),
    "blueprint": Theme(
        id="blueprint",
        name="Blueprint",
        name_zh="蓝图",
        name_en="Blueprint",
        label="Blueprint",
        category="cool",
        description="建筑蓝图蓝白，技术架构图风格。",
        tokens={"color-bg": "#0d2a5e", "color-bg-soft": "#0a2049", "color-surface": "#0f3470", "color-surface-2": "#164180", "color-border": "rgba(150,200,255,.25)", "color-border-strong": "rgba(150,200,255,.55)", "color-text-1": "#e8f1ff", "color-text-2": "#a0c0e8", "color-text-3": "#5080b8", "color-accent": "#7adcff", "color-accent-2": "#ffffff", "color-accent-3": "#a0d8ff", "color-good": "#7affb0", "color-warn": "#ffd700", "color-bad": "#ff7a7a", "gradient-primary": "linear-gradient(135deg,#7adcff,#ffffff)", "gradient-soft": "linear-gradient(135deg,rgba(122,220,255,.15),rgba(255,255,255,.1))", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "none", "shadow-lg": "0 0 0 1px rgba(150,200,255,.2)", "font-body": "'JetBrains Mono','Courier New',monospace", "font-heading": "'JetBrains Mono','Courier New',monospace"},
        colors=ThemeColors(
            primary="#7adcff",
            secondary="#ffffff",
            background="#0d2a5e",
            text="#e8f1ff",
            accent="#a0d8ff",
        ),
    ),
    "memphis-pop": Theme(
        id="memphis-pop",
        name="Memphis Pop",
        name_zh="孟菲斯波普",
        name_en="Memphis Pop",
        label="Memphis Pop",
        category="colorful",
        description="80年代孟菲斯设计，撞色几何图案。",
        tokens={"color-bg": "#fff5f0", "color-bg-soft": "#fde8dc", "color-surface": "#ffffff", "color-surface-2": "#fff0e5", "color-border": "rgba(0,0,0,.85)", "color-border-strong": "rgba(0,0,0,1)", "color-text-1": "#0a0a0a", "color-text-2": "#2a2a2a", "color-text-3": "#5a5a5a", "color-accent": "#ff3b6e", "color-accent-2": "#3bafff", "color-accent-3": "#ffd83b", "color-good": "#3bff7a", "color-warn": "#ffd83b", "color-bad": "#ff3b6e", "gradient-primary": "linear-gradient(135deg,#ff3b6e,#3bafff 50%,#ffd83b)", "gradient-soft": "linear-gradient(135deg,#fff0e5,#fff5f0)", "radius-md": "16px", "radius-sm": "8px", "radius-lg": "32px", "shadow-md": "4px 4px 0 #0a0a0a", "shadow-lg": "8px 8px 0 #0a0a0a", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.03em"},
        colors=ThemeColors(
            primary="#ff3b6e",
            secondary="#3bafff",
            background="#fff5f0",
            text="#0a0a0a",
            accent="#ffd83b",
        ),
    ),
    "cyberpunk-neon": Theme(
        id="cyberpunk-neon",
        name="Cyberpunk Neon",
        name_zh="赛博朋克",
        name_en="Cyberpunk Neon",
        label="Cyberpunk Neon",
        category="tech",
        description="霓虹粉青 + 暗底，赛博朋克 2077 风。",
        tokens={"color-bg": "#000000", "color-bg-soft": "#0a0a12", "color-surface": "#0f0f1a", "color-surface-2": "#14141f", "color-border": "rgba(255,0,170,.25)", "color-border-strong": "rgba(0,240,255,.55)", "color-text-1": "#f5f7ff", "color-text-2": "#b4b8d4", "color-text-3": "#6b6e8a", "color-accent": "#ff2bd6", "color-accent-2": "#00f0ff", "color-accent-3": "#f9f871", "color-good": "#39ff14", "color-warn": "#f9f871", "color-bad": "#ff2bd6", "gradient-primary": "linear-gradient(135deg,#ff2bd6,#7a00ff 50%,#00f0ff)", "gradient-soft": "linear-gradient(135deg,rgba(255,43,214,.18),rgba(0,240,255,.18))", "radius-md": "6px", "radius-sm": "3px", "radius-lg": "10px", "shadow-md": "0 0 0 1px rgba(255,43,214,.35),0 0 24px rgba(255,43,214,.35),0 0 48px rgba(0,240,255,.18)", "shadow-lg": "0 0 0 1px rgba(0,240,255,.5),0 0 40px rgba(0,240,255,.45),0 0 80px rgba(255,43,214,.3)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'JetBrains Mono','IBM Plex Mono',monospace"},
        colors=ThemeColors(
            primary="#ff2bd6",
            secondary="#00f0ff",
            background="#000000",
            text="#f5f7ff",
            accent="#f9f871",
        ),
    ),
    "y2k-chrome": Theme(
        id="y2k-chrome",
        name="Y2K Chrome",
        name_zh="Y2K 铬金",
        name_en="Y2K Chrome",
        label="Y2K Chrome",
        category="retro",
        description="2000 年未来主义，铬银 + 渐变，Y2K 复古回潮。",
        tokens={"color-bg": "#e8e8f0", "color-bg-soft": "#d4d4e0", "color-surface": "#ffffff", "color-surface-2": "#f0f0f8", "color-border": "rgba(100,100,140,.3)", "color-border-strong": "rgba(100,100,140,.6)", "color-text-1": "#1a1a3a", "color-text-2": "#3a3a5a", "color-text-3": "#7a7a9a", "color-accent": "#c0c0ff", "color-accent-2": "#ff7ad4", "color-accent-3": "#7afff0", "color-good": "#7affb0", "color-warn": "#ffd700", "color-bad": "#ff5a8a", "gradient-primary": "linear-gradient(135deg,#c0c0ff,#ff7ad4 50%,#7afff0)", "gradient-soft": "linear-gradient(135deg,#d4d4e0,#e8e8f0)", "radius-md": "20px", "radius-sm": "14px", "radius-lg": "32px", "shadow-md": "inset 0 1px 0 rgba(255,255,255,.6),0 4px 14px rgba(100,100,140,.2)", "shadow-lg": "inset 0 1px 0 rgba(255,255,255,.6),0 12px 30px rgba(100,100,140,.3)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.04em"},
        colors=ThemeColors(
            primary="#c0c0ff",
            secondary="#ff7ad4",
            background="#e8e8f0",
            text="#1a1a3a",
            accent="#7afff0",
        ),
    ),
    "retro-tv": Theme(
        id="retro-tv",
        name="Retro TV",
        name_zh="复古电视",
        name_en="Retro TV",
        label="Retro TV",
        category="retro",
        description="70-80年代电视暖色，VHS 复古。",
        tokens={"color-bg": "#2a1a0f", "color-bg-soft": "#1a0f08", "color-surface": "#3a2a1a", "color-surface-2": "#4a3a2a", "color-border": "rgba(255,180,80,.25)", "color-border-strong": "rgba(255,180,80,.5)", "color-text-1": "#f9d97a", "color-text-2": "#d4a85a", "color-text-3": "#8a6a3a", "color-accent": "#ff7a3a", "color-accent-2": "#f9d97a", "color-accent-3": "#ff5a8a", "color-good": "#a3d97a", "color-warn": "#f9d97a", "color-bad": "#ff5a5a", "gradient-primary": "linear-gradient(135deg,#ff7a3a,#f9d97a 50%,#ff5a8a)", "gradient-soft": "linear-gradient(135deg,#3a2a1a,#4a3a2a)", "radius-md": "12px", "radius-sm": "6px", "radius-lg": "20px", "shadow-md": "0 4px 14px rgba(0,0,0,.4)", "shadow-lg": "0 12px 30px rgba(0,0,0,.55)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#ff7a3a",
            secondary="#f9d97a",
            background="#2a1a0f",
            text="#f9d97a",
            accent="#ff5a8a",
        ),
    ),
    "japanese-minimal": Theme(
        id="japanese-minimal",
        name="Japanese Minimal",
        name_zh="日式极简",
        name_en="Japanese Minimal",
        label="Japanese Minimal",
        category="minimal",
        description="日式侘寂风，米白底 + 朱印红点。",
        tokens={"color-bg": "#f5f0e8", "color-bg-soft": "#ebe4d6", "color-surface": "#faf6ee", "color-surface-2": "#efe8d8", "color-border": "rgba(60,40,20,.18)", "color-border-strong": "rgba(60,40,20,.36)", "color-text-1": "#1a1410", "color-text-2": "#3a302a", "color-text-3": "#7a6a5a", "color-accent": "#a8321a", "color-accent-2": "#3a2a1a", "color-accent-3": "#7a5a3a", "color-good": "#5a7a3a", "color-warn": "#a87a1a", "color-bad": "#a82a2a", "gradient-primary": "linear-gradient(135deg,#a8321a,#3a2a1a)", "gradient-soft": "linear-gradient(135deg,#ebe4d6,#f5f0e8)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "4px", "shadow-md": "none", "shadow-lg": "0 1px 0 rgba(60,40,20,.08)", "font-body": "'Noto Serif SC','Yu Mincho',serif", "font-heading": "'Noto Serif SC','Yu Mincho',serif", "letter-tight": "-.01em"},
        colors=ThemeColors(
            primary="#a8321a",
            secondary="#3a2a1a",
            background="#f5f0e8",
            text="#1a1410",
            accent="#7a5a3a",
        ),
    ),
    "vaporwave": Theme(
        id="vaporwave",
        name="Vaporwave",
        name_zh="蒸汽波",
        name_en="Vaporwave",
        label="Vaporwave",
        category="retro",
        description="蒸汽波紫粉渐变 + 网格，老网恋美学。",
        tokens={"color-bg": "#1a0a2a", "color-bg-soft": "#0f0518", "color-surface": "#251540", "color-surface-2": "#301a55", "color-border": "rgba(255,80,180,.25)", "color-border-strong": "rgba(0,220,255,.5)", "color-text-1": "#ffe0f5", "color-text-2": "#c0a0e0", "color-text-3": "#7a5a9a", "color-accent": "#ff50b4", "color-accent-2": "#00dcef", "color-accent-3": "#a0ffd0", "color-good": "#a0ffd0", "color-warn": "#ffe060", "color-bad": "#ff5a8a", "gradient-primary": "linear-gradient(135deg,#ff50b4,#00dcef 50%,#a0ffd0)", "gradient-soft": "linear-gradient(135deg,rgba(255,80,180,.18),rgba(0,220,239,.18))", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "0 0 20px rgba(255,80,180,.3)", "shadow-lg": "0 0 40px rgba(0,220,239,.4)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.04em"},
        colors=ThemeColors(
            primary="#ff50b4",
            secondary="#00dcef",
            background="#1a0a2a",
            text="#ffe0f5",
            accent="#a0ffd0",
        ),
    ),
    "midcentury": Theme(
        id="midcentury",
        name="Midcentury",
        name_zh="中世纪",
        name_en="Midcentury",
        label="Midcentury",
        category="warm",
        description="中世纪现代主义，橙棕 + 鼠尾草绿。",
        tokens={"color-bg": "#f5ebe0", "color-bg-soft": "#e8dac4", "color-surface": "#fdf5ec", "color-surface-2": "#f0e2cc", "color-border": "rgba(120,80,40,.18)", "color-border-strong": "rgba(120,80,40,.36)", "color-text-1": "#1a1208", "color-text-2": "#3a2818", "color-text-3": "#7a5a3a", "color-accent": "#c47a3a", "color-accent-2": "#7a8a5a", "color-accent-3": "#a85a3a", "color-good": "#5a7a3a", "color-warn": "#c4a01a", "color-bad": "#a82a2a", "gradient-primary": "linear-gradient(135deg,#c47a3a,#7a8a5a)", "gradient-soft": "linear-gradient(135deg,#f0e2cc,#f5ebe0)", "radius-md": "8px", "radius-sm": "4px", "radius-lg": "16px", "shadow-md": "0 4px 12px rgba(120,80,40,.12)", "shadow-lg": "0 12px 30px rgba(120,80,40,.18)", "font-body": "'Futura','Arial','Noto Sans SC',sans-serif", "font-heading": "'Futura','Arial Black','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#c47a3a",
            secondary="#7a8a5a",
            background="#f5ebe0",
            text="#1a1208",
            accent="#a85a3a",
        ),
    ),
    "corporate-clean": Theme(
        id="corporate-clean",
        name="Corporate Clean",
        name_zh="企业清洁",
        name_en="Corporate Clean",
        label="Corporate Clean",
        category="brand",
        description="企业商务专业风，蓝白灰严谨配色。",
        tokens={"color-bg": "#ffffff", "color-bg-soft": "#f5f7fa", "color-surface": "#ffffff", "color-surface-2": "#f0f4f8", "color-border": "rgba(20,40,80,.12)", "color-border-strong": "rgba(20,40,80,.32)", "color-text-1": "#0a1a3a", "color-text-2": "#2a3a5a", "color-text-3": "#6a7a9a", "color-accent": "#1a4ac4", "color-accent-2": "#0a2a7a", "color-accent-3": "#5a8ac4", "color-good": "#1a8a3a", "color-warn": "#c47a1a", "color-bad": "#c43a3a", "gradient-primary": "linear-gradient(135deg,#1a4ac4,#0a2a7a)", "gradient-soft": "linear-gradient(135deg,#f0f4f8,#f5f7fa)", "radius-md": "6px", "radius-sm": "4px", "radius-lg": "10px", "shadow-md": "0 2px 8px rgba(20,40,80,.08)", "shadow-lg": "0 10px 24px rgba(20,40,80,.12)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#1a4ac4",
            secondary="#0a2a7a",
            background="#ffffff",
            text="#0a1a3a",
            accent="#5a8ac4",
        ),
    ),
    "academic-paper": Theme(
        id="academic-paper",
        name="Academic Paper",
        name_zh="学术论文",
        name_en="Academic Paper",
        label="Academic Paper",
        category="brand",
        description="学术论文正式，Times 衬线 + 严谨排版。",
        tokens={"color-bg": "#fdfcf8", "color-bg-soft": "#f7f5ed", "color-surface": "#ffffff", "color-surface-2": "#f5f3ea", "color-border": "rgba(20,20,20,.14)", "color-border-strong": "rgba(20,20,20,.35)", "color-text-1": "#0a0a0a", "color-text-2": "#333333", "color-text-3": "#707070", "color-accent": "#1a3a7a", "color-accent-2": "#0a0a0a", "color-accent-3": "#8a1a1a", "color-good": "#1a5a2a", "color-warn": "#8a6a1a", "color-bad": "#8a1a1a", "gradient-primary": "linear-gradient(135deg,#1a3a7a,#0a0a0a)", "gradient-soft": "linear-gradient(135deg,#e8edf8,#f5f3ea)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "none", "shadow-lg": "0 1px 2px rgba(0,0,0,.1)", "font-body": "'Latin Modern Roman','Playfair Display','Noto Serif SC',Georgia,serif", "font-heading": "'Latin Modern Roman','Playfair Display','Noto Serif SC',Georgia,serif"},
        colors=ThemeColors(
            primary="#1a3a7a",
            secondary="#0a0a0a",
            background="#fdfcf8",
            text="#0a0a0a",
            accent="#8a1a1a",
        ),
    ),
    "news-broadcast": Theme(
        id="news-broadcast",
        name="News Broadcast",
        name_zh="新闻广播",
        name_en="News Broadcast",
        label="News Broadcast",
        category="brand",
        description="新闻联播风，红蓝配色，权威感。",
        tokens={"color-bg": "#f5f5f5", "color-bg-soft": "#e8e8e8", "color-surface": "#ffffff", "color-surface-2": "#efefef", "color-border": "rgba(0,0,0,.15)", "color-border-strong": "rgba(0,0,0,.4)", "color-text-1": "#0a0a0a", "color-text-2": "#2a2a2a", "color-text-3": "#6a6a6a", "color-accent": "#c41a1a", "color-accent-2": "#1a3a7a", "color-accent-3": "#0a0a0a", "color-good": "#1a8a3a", "color-warn": "#c47a1a", "color-bad": "#c41a1a", "gradient-primary": "linear-gradient(135deg,#c41a1a,#1a3a7a)", "gradient-soft": "linear-gradient(135deg,#efefef,#f5f5f5)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "0 1px 3px rgba(0,0,0,.1)", "shadow-lg": "0 4px 12px rgba(0,0,0,.15)", "font-body": "'Source Han Sans SC','Noto Sans SC',sans-serif", "font-heading": "'Source Han Sans SC','Noto Sans SC',sans-serif", "letter-tight": "-.02em"},
        colors=ThemeColors(
            primary="#c41a1a",
            secondary="#1a3a7a",
            background="#f5f5f5",
            text="#0a0a0a",
            accent="#0a0a0a",
        ),
    ),
    "pitch-deck-vc": Theme(
        id="pitch-deck-vc",
        name="Pitch Deck VC",
        name_zh="VC 路演",
        name_en="Pitch Deck VC",
        label="Pitch Deck VC",
        category="brand",
        description="硅谷 VC 路演，深色 + 强调色，专业融资。",
        tokens={"color-bg": "#0a0a14", "color-bg-soft": "#05050a", "color-surface": "#15151f", "color-surface-2": "#1f1f2a", "color-border": "rgba(255,255,255,.08)", "color-border-strong": "rgba(255,255,255,.2)", "color-text-1": "#ffffff", "color-text-2": "rgba(255,255,255,.85)", "color-text-3": "rgba(255,255,255,.55)", "color-accent": "#00ffaa", "color-accent-2": "#a78bfa", "color-accent-3": "#ffd700", "color-good": "#00ffaa", "color-warn": "#ffd700", "color-bad": "#ff5a5a", "gradient-primary": "linear-gradient(135deg,#00ffaa,#a78bfa 50%,#ffd700)", "gradient-soft": "linear-gradient(135deg,rgba(0,255,170,.1),rgba(167,139,250,.1))", "radius-md": "12px", "radius-sm": "8px", "radius-lg": "20px", "shadow-md": "0 8px 24px rgba(0,0,0,.3)", "shadow-lg": "0 20px 50px rgba(0,0,0,.5)", "font-body": "'Inter','Noto Sans SC',sans-serif", "font-heading": "'Inter','Noto Sans SC',sans-serif", "letter-tight": "-.03em"},
        colors=ThemeColors(
            primary="#00ffaa",
            secondary="#a78bfa",
            background="#0a0a14",
            text="#ffffff",
            accent="#ffd700",
        ),
    ),
    "magazine-bold": Theme(
        id="magazine-bold",
        name="Magazine Bold",
        name_zh="杂志大胆",
        name_en="Magazine Bold",
        label="Magazine Bold",
        category="warm",
        description="时尚杂志风，巨型衬线标题 + 撞色。",
        tokens={"color-bg": "#fff5e8", "color-bg-soft": "#f5e8d0", "color-surface": "#ffffff", "color-surface-2": "#fff0d8", "color-border": "rgba(0,0,0,.85)", "color-border-strong": "rgba(0,0,0,1)", "color-text-1": "#0a0a0a", "color-text-2": "#2a2a2a", "color-text-3": "#5a5a5a", "color-accent": "#d92020", "color-accent-2": "#1a1a1a", "color-accent-3": "#f9c80e", "color-good": "#1a8a3a", "color-warn": "#f9c80e", "color-bad": "#d92020", "gradient-primary": "linear-gradient(135deg,#d92020,#1a1a1a)", "gradient-soft": "linear-gradient(135deg,#fff0d8,#fff5e8)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "4px 4px 0 #0a0a0a", "shadow-lg": "10px 10px 0 #0a0a0a", "font-body": "'Playfair Display','Noto Serif SC',Georgia,serif", "font-heading": "'Playfair Display','Noto Serif SC',Georgia,serif", "letter-tight": "-.05em"},
        colors=ThemeColors(
            primary="#d92020",
            secondary="#1a1a1a",
            background="#fff5e8",
            text="#0a0a0a",
            accent="#f9c80e",
        ),
    ),
    "engineering-whiteprint": Theme(
        id="engineering-whiteprint",
        name="Engineering Whiteprint",
        name_zh="工程白图",
        name_en="Engineering Whiteprint",
        label="Engineering Whiteprint",
        category="cool",
        description="工程白图风格，蓝色单色线条技术图。",
        tokens={"color-bg": "#f5f8fa", "color-bg-soft": "#e8eef2", "color-surface": "#ffffff", "color-surface-2": "#f0f4f6", "color-border": "rgba(30,80,140,.18)", "color-border-strong": "rgba(30,80,140,.4)", "color-text-1": "#0a2030", "color-text-2": "#2a3a4a", "color-text-3": "#6a7a8a", "color-accent": "#1a4a7a", "color-accent-2": "#0a2a4a", "color-accent-3": "#5a8ab8", "color-good": "#1a7a3a", "color-warn": "#a87a1a", "color-bad": "#a82a2a", "gradient-primary": "linear-gradient(135deg,#1a4a7a,#0a2a4a)", "gradient-soft": "linear-gradient(135deg,#e8eef2,#f5f8fa)", "radius-md": "0px", "radius-sm": "0px", "radius-lg": "0px", "shadow-md": "none", "shadow-lg": "0 1px 2px rgba(30,80,140,.12)", "font-body": "'JetBrains Mono','Courier New',monospace", "font-heading": "'JetBrains Mono','Courier New',monospace"},
        colors=ThemeColors(
            primary="#1a4a7a",
            secondary="#0a2a4a",
            background="#f5f8fa",
            text="#0a2030",
            accent="#5a8ab8",
        ),
    ),
}


# ============================================================================
# v0.5 backward compatibility aliases
# ============================================================================
# Old v0.5 theme IDs map to their closest v0.6.1 equivalent.
# Stored tasks and API requests with old IDs continue to work.

LEGACY_THEME_ALIASES: Dict[str, str] = {
    "professional": "corporate-clean",
    "modern": "dracula",
    "minimal": "minimal-white",
    "nature": "midcentury",
    "warm": "sunset-warm",
    "dark": "dracula",
    "academic": "academic-paper",
    "creative": "memphis-pop",
}


# ============================================================================
# Public API
# ============================================================================

DEFAULT_THEME = "minimal-white"


def get_theme(name: str) -> Theme:
    """Get theme by id, with legacy alias resolution and safe fallback.

    Lookup order:
    1. Direct match in THEMES
    2. Legacy v0.5 alias resolution (professional -> corporate-clean etc.)
    3. Safe fallback to DEFAULT_THEME
    """
    if name in THEMES:
        return THEMES[name]
    if name in LEGACY_THEME_ALIASES:
        resolved = LEGACY_THEME_ALIASES[name]
        return THEMES[resolved]
    return THEMES[DEFAULT_THEME]


def list_themes() -> List[Theme]:
    """List all 36 available themes (in declared order)."""
    return list(THEMES.values())


def list_theme_ids() -> List[str]:
    """List theme IDs in declared order."""
    return list(THEMES.keys())


def list_themes_by_category() -> Dict[str, List[Theme]]:
    """Group themes by category for grouped display in UI."""
    grouped: Dict[str, List[Theme]] = {}
    for theme in THEMES.values():
        grouped.setdefault(theme.category, []).append(theme)
    return grouped


def get_legacy_aliases() -> Dict[str, str]:
    """Return the legacy v0.5 -> v0.6.1 alias mapping (for API/docs)."""
    return dict(LEGACY_THEME_ALIASES)


# Category display labels (zh + en) for UI grouping
CATEGORY_LABELS: Dict[str, Dict[str, str]] = {
    "minimal":   {"zh": "极简",   "en": "Minimal"},
    "soft":      {"zh": "柔和",   "en": "Soft"},
    "warm":      {"zh": "暖色",   "en": "Warm"},
    "cool":      {"zh": "冷色",   "en": "Cool"},
    "dark":      {"zh": "暗色",   "en": "Dark"},
    "colorful":  {"zh": "卡通风", "en": "Colorful"},
    "tech":      {"zh": "科技",   "en": "Tech"},
    "brand":     {"zh": "品牌专业", "en": "Brand"},
    "design":    {"zh": "设计",   "en": "Design"},
    "retro":     {"zh": "复古",   "en": "Retro"},
}


def get_category_order() -> List[str]:
    """Canonical category display order."""
    return ["minimal", "soft", "warm", "cool", "dark", "colorful", "tech", "brand", "design", "retro"]
