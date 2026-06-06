# Chat 页面 Hermes 风格化 v0.1 — 设计文档

## 目标
借鉴 Hermes Agent webui（Nous Research 177k stars）的设计语言，重塑
AgentChat 页面，提升视觉层次、状态可见性、可操作性。**不重塑全局
调色板**（保持 blue/slate），仅在 chat 视图内做局部品牌化。

## 现状
- `AgentChat.tsx` (433 行) — 主组件
- `SessionSidebar.tsx` (122 行) — 简单 session 列表
- `MessageBubble.tsx` (95 行) — 基础气泡
- `ToolCard.tsx` (137 行) — 工具调用卡
- 纯色背景、无图标库、emoji 装饰、3 个 emoji/loader 状态

## 借鉴的设计模式
来源：Hermes Agent `web/src/` 1194 行 App.tsx + 4 层 Backdrop + ChatSidebar

| 模式 | 来源 | 改造点 |
|------|------|--------|
| 4 层 Backdrop (z-1/z-2/z-99/z-101) | `components/Backdrop.tsx` | 全局视觉氛围 |
| +lighter mix-blend on active | App.tsx:1083 | 1px 活动指示 |
| 折叠态 icon-only 64px ↔ 240px | App.tsx:538 | SessionSidebar |
| 工具/状态右侧 rail | `ChatSidebar.tsx` | 新增 ToolsRail |
| 状态 badge (model/connection/tokens) | ChatSidebar.tsx:300+ | Header toolbar |
| 消息 hover 操作条 | 通用 | MessageBubble |
| 持久化折叠态 localStorage | App.tsx:344 | SessionSidebar |
| 入场 fade-in 动画 | `index.css:204` | MessageBubble |

## 6 个 commits（按顺序）

### Commit 1 — chore(deps): add lucide-react icon library
- 文件: `package.json`
- 改动: `+lucide-react@^0.400.0` (~30KB gzip, tree-shake)
- 零代码改动

### Commit 2 — feat(chat): 4-layer backdrop with warm vignette + grain
- 文件: `src/styles/index.css` (+~60 行), `src/App.tsx` (+5 行)
- 4 层 fixed inset-0:
  - z-1 bg-primary mix-blend-difference
  - z-2 反相纹理（SVG data-url 噪点）
  - z-99 radial-gradient 暖色 vignette
  - z-101 SVG 噪点 color-dodge
- 蓝调版本（不动 --accent）

### Commit 3 — feat(chat): header toolbar with model badge + connection state
- 文件: `src/components/AgentChat.tsx` (~+40 行)
- 头部升级: Cpu icon + model name + connection dot + Coins token count
- 数据流: 从 chatStream event 提取 model 字段

### Commit 4 — feat(chat): SessionSidebar collapse + active indicator
- 文件: `src/components/SessionSidebar.tsx` (~+50 行)
- 折叠: 64px icon-only ↔ 240px (PanelLeftClose/Open)
- 状态: localStorage['chat-sidebar-collapsed']
- 活动: 1px +lighter 替代 2px 边
- 删除: Trash2 icon 替代 ×

### Commit 5 — feat(chat): right-side ToolsRail
- 文件: `src/components/ToolsRail.tsx` (新, ~200 行)
- 顶部: model picker + connection state
- 中部: tool timeline (从 messages 聚合)
- 底部: session meta
- 布局: [sidebar][chat 1fr][rail 320]
- 响应式: ≥1280 显示, 1024-1279 可折叠, <1024 隐藏

### Commit 6 — feat(chat): MessageBubble hover actions + fade-in + avatar
- 文件: `src/components/ui/MessageBubble.tsx` (~+60 行)
- 助手侧: Bot icon + "Assistant" 角色名
- 用户侧: User icon + "You"
- Hover 操作条: Copy / RotateCw / Quote
- 入场: fade-in + slide-up 200ms
- Copy 反馈: Check icon 1.5s

### Commit 7 — feat(chat): ToolCard visual sync
- 文件: `src/components/ui/ToolCard.tsx` (~+30 行)
- 状态 emoji → lucide: Loader2 / CheckCircle2 / XCircle
- Tool 映射: 7 个 wiki 工具 + 通用 Wrench
- args/result: 默认折叠，点击展开
- 视觉整合: 紧贴 assistant 气泡，左缩进 8px

## 文件改动总览
| 文件 | 改动 | 行数 |
|------|------|------|
| `package.json` | +lucide-react | +1 |
| `src/styles/index.css` | +backdrop +animations | +60 |
| `src/App.tsx` | +Backdrop component | +5 |
| `src/components/AgentChat.tsx` | header + rail 集成 | +65 |
| `src/components/SessionSidebar.tsx` | 折叠 + 1px indicator | +50 |
| `src/components/ToolsRail.tsx` | 新文件 | +200 |
| `src/components/ui/MessageBubble.tsx` | avatar + hover + fade | +60 |
| `src/components/ui/ToolCard.tsx` | lucide icons + 折叠 | +30 |
| **总计** | | **~470 行** |

## 验证

每 commit 后:
1. `npx tsc --noEmit` 无新错误
2. `npx vite build` bundle 增 ~30KB

最终 e2e:
- 桌面 1280-1920px: 3 列布局
- 中屏 1024-1279px: rail 可手动折叠
- 小屏 <1024px: 单列，rail 隐藏

## 不在范围（v0.1 不做）

- React 19 升级（持久化 chat 容器需要）
- 持久化 chat 容器（display:none toggle）
- Mondwest 字体 tier 系统
- 4 套主题切换
- 全局 teal/cream 调色板
- ConfirmationModal 视觉升级
