# teardown · AGENTS.md（压缩版规则 + 本机适配）

> **用途**：这是一份**可直接落成 `AGENTS.md` 的规则文件**。
> - 用能跑命令的智能体（Z Code / Codex / Cursor / Gemini CLI / Claude Code 兼容客户端）→ 存成**工作区根目录 `AGENTS.md`**
> - 用只能聊天的网页（DeepSeek 网页版等）→ 把下面「第一部分」整段当**第一条消息**粘进去
> - 装完整仓库时，最后一行会让智能体去读 `SKILL.md` 全文
>
> **来源**：规则压缩自 `teardown` 仓库的 `SKILL.md` 核心几节（作者原文），**「第二部分」为本仓/本机适配，非作者原文**。
> 配套：[`CHECKLIST.md`](./CHECKLIST.md)

---

# 第一部分：Teardown 核心规则（原文压缩，英文）

```markdown
# Teardown: build one interactive 3D machine simulator as an offline HTML page

You build ONE machine as ONE self-contained HTML page (target under 1 MB) that people can take apart,
with live panels driven by the same model that moves the parts, plus a film of the tour recorded frame by frame.

## Stack (do not change it)
- three.js (0.186.x), bundled with esbuild into one HTML file. No CDN, no network at runtime. Fonts are inlined.
- Plain JavaScript modules. No framework. No external 3D model files unless I say so.
- Node 20+, Playwright Chromium for stills and video, ffmpeg for encoding, Python 3 (stdlib only) for the score.

## File structure, one folder per machine, one job per file
- model.js    the math. Real units, one input, every pose and readout as a pure function of it. NO three.js in this file.
- geometry.js the parts, built from code. update(input) poses them. Group parts by assembly so each can be isolated.
- stage.js    studio, lights, soft shadows, post (ambient occlusion, bloom). frame(state, cam) draws one frame.
- console.js  the overlay: a fixed 1600x900 CSS layout of panels, charts, buttons, callouts with leader lines.
- film.js     a SCRIPT of operator moves (views, isolate, cut, explode) and render(t) as a PURE function of time.
- live.js     the same machine in real time: buttons, orbit, zoom, keys. With no input it plays the film script as an auto tour with a cursor.
              Any click, drag, wheel or key hands control to the visitor; 25 s of quiet hands it back.
- score.py    the sound, on the film's timeline.

Write ONE file per reply, complete, never a diff. If a file will pass ~400 lines, split it.

## Hard rules
1. Reference first. Build against the reference I give you and compare. If I gave none, ask for one. Never invent from a sentence.
2. Real numbers, one source. Every gauge, chart and label reads from the same function that poses the parts. No number on screen is typed in.
   Hand-check one number and show the arithmetic. If you are not sure a number is real, say so.
3. ONE input drives everything. Nothing is keyframed by hand.
4. The part doing the work opens up: isolate it, cut it, x-ray it, explode it. Collisions are fixed with a number in the parameter block, never by moving the camera.
5. Light studio, ONE accent colour that marks the part working right now. Near-white parts get a thin ink outline or a darker ground.
   The machine fills 60-70% of its view. Labels are never under 34 px on a 1080 canvas.
6. render(t) is pure: no Math.random (use a seeded rng), no Date, no state kept between frames.
   Frame 0 must already show the machine. Every beat goes in timeline.json (seconds).
7. Live page: add quality tiers for integrated GPUs, compile shaders before the first frame, keep the page under 1 MB.

## three.js traps
- smoothstep(a,b,x) with a>b returns 0 on Windows: write 1.0 - smoothstep(b,a,x).
- Clamp every pow() base in a shader (one NaN blacks out the frame through bloom).
- Keep emissive under 1.0 (bloom). Big metal surfaces: roughness >= 0.45.

## How you work
- Small steps. Before any code for a new part, write a parameter table (name, value, unit, source) and wait for my OK.
- One change per round. After a change, rebuild, render a still, and tell me what you saw.
- If the repo is installed at $SKILL_DIR, read $SKILL_DIR/SKILL.md and copy the closest example in $SKILL_DIR/sims/ (cessna-* is the smallest) before writing from scratch.
```

---

# 第二部分：本机 / 本仓适配（非作者原文）

## 2.1 路径约定

| 用途 | 路径 | 说明 |
|---|---|---|
| teardown 仓库（方法真源） | `D:\Github\teardown-duck` | **在 llmwikify 仓库之外**，不要放进 `D:\Github\llmwikify` |
| 本机新建机器的工作区 | `D:\Github\teardown-duck` 内的 `sims/<机器>-film\` | 一个机器一个文件夹 |
| 参考规格 | `sims/<机器>-film\ref\spec.md` | 每个数字标注来源：`from image` / `computed` / `my guess` |
| 产出单页 | `sims/<机器>-film\dist\` | build 产物，**< 1MB** |
| 静帧 | `teardown-out\<机器>\` | build 后用仓库自带 stills 命令出 |
| 本仓（llmwikify）文档 | `D:\Github\llmwikify\docs\teardown\` | 本文件与 `CHECKLIST.md` |

## 2.2 硬边界（**违反即任务失败**）

1. **不要修改 `D:\Github\llmwikify` 下的任何源码**（`src/`、`ui/`、`tests/`、`scripts/`）。那是另一个在跑的项目，工作区当前有未提交改动，碰了就污染别人的活。
2. **不要 git commit / push**（llmwikify 和 teardown 都不行）。要提交由人来做。
3. **不要碰 `D:\Github\llmwikify\AGENTS.md`** —— 那是 agents-sync 托管的文件（gist 同步），本地改了会被覆盖。
4. 不要部署 Vercel / 不要把任何东西传到外网。
5. 不要顺手重构/改格式/删"看起来没用"的代码（llmwikify 的 Surgical Changes 原则同样适用）。

## 2.3 Shell 约定（Windows PowerShell 5.1）

- **不支持 `&&` 和 `||`**，用 `;` 或换行；脚本开头写 `$ErrorActionPreference = 'Stop'`
- 原生命令后检查 `$LASTEXITCODE`
- **不要用** heredoc、`sed -i`、Bash 反斜杠转义
- 写文件用 UTF-8；`Out-File -Encoding UTF8` 会带 BOM，Node 读 `.js` 时注意
- 长命令（`npm install`、`npx playwright install chromium`）用后台任务跑，别卡住会话

## 2.4 本机工具链现状

| 工具 | 状态 | 影响 |
|---|---|---|
| Node v20.18.1 | ✅ | 满足 teardown 的 Node 20+ 要求 |
| `npx skills` | ❌ 需 Node ≥ 22.20 | **走克隆法**，不要用 skill CLI |
| Python 3.13 | ✅ 仅标准库 | `score.py` 可写 |
| **ffmpeg** | ❌ **未安装** | **本轮不做视频出片与音频 mux**；`score.py` 可以写但别试图并进 mp4 |
| 显卡 | 未知 | 启动打印 `gpu:`；若是 `SwiftShader` 就是软件渲染，静帧可能十几秒一张 → 别在无显卡机器上做视频 |

## 2.5 验证命令（**每次改完就跑，不要攒到最后**）

```powershell
cd D:\Github\teardown-duck

node sims\<机器>\check.mjs          # 断言必须全过
node sims/build.mjs <机器>           # 构建
Get-ChildItem -Recurse -Filter *.html | Select-Object FullName, Length   # 报告字节数，必须 < 1MB
node sims/capture.mjs <机器> --stills beats   # 逐节拍静帧（参数以仓库 README 为准）
```

**体积预算**：底子约 800KB = 字体 ≈ 114KB + three.js/后处理（大头）+ 机器代码 ≈ 74KB（塞斯纳实测）→ **留给你的机器约 150–200KB**。

## 2.6 自检是硬门槛，不是可选项

作者靠这一步抓出两个差点上线的 bug（兔子脸穿出帽子壁、六足换步态腿飞出去）。规矩：

- **逐张静帧写一行发现**，每张都要写。不许输出「都没问题」。
- 碰撞**只能用参数块里的一个数字修**，绝不靠挪相机。
- 弱模型看不了图 → 把截图丢给能看图的模型，把意见转回去。
- 面板数字写死是最常见的暗坑：**改一个参数，数字必须跟着变**。

## 2.7 与 llmwikify 本仓规约的对齐

teardown 的方法论和本仓 `AGENTS.md` 高度同源，这里显式映射，便于统一心智：

| teardown 规则 | llmwikify 对应原则 |
|---|---|
| 单一输入纯函数驱动一切，屏幕数字不手写 | 单一消息真源（业务数据绑 assistant message） |
| ONE file per reply，完整输出，超 400 行拆分 | Simplicity First + Surgical Changes |
| 一轮只改一处，改完立刻验证 | Verify-Then-Proceed（每 edit 后立即 ruff check） |
| 碰撞用参数块数字修，不靠挪相机 | 同上：不用"顺手重构"掩盖问题 |
| 目标明确就循环到通过 | Loop Until Done |

**一条本仓特有的硬约束**：teardown 产出物（HTML/静帧/mp4）**不进 llmwikify 的 git 仓库**，只作为工作区文件存在；真要归档，放 `docs/teardown/` 下的 markdown 记录，不放二进制。

## 2.8 开工前的开场白（任何工具都用这句）

```
SKILL_DIR is D:\Github\teardown-duck. Read $SKILL_DIR/SKILL.md first, then follow it.
```

对于只能聊天的网页，把**第一部分整段**粘成第一条消息即可，无需这句。
