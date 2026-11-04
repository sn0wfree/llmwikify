# teardown 复刻 Checklist（本机可执行版）

> 配套文件：[`AGENTS-teardown.md`](./AGENTS-teardown.md)（压缩版规则，落成 `AGENTS.md` 备用）
> 方法来源：@elvar_official X Article《How I Turn Any Machine Into a 3D Simulator You Can Take Apart》
> 仓库：`https://github.com/elvarofficial/teardown`（MIT，免费）
> 整理自公众号「鸡猫AI江湖」《刷屏全网的 Opus 5.5 机械章鱼，想复刻吗？？？》

本文是**可勾选的操作清单**，不是方法论散文。每一步都给出「输入 → 动作 → 验收标准 → 坑」。

---

## 0. 先决策：走哪条路线

**核心判据（文章原话逻辑）**：这套流程里模型只负责写代码，真正去跑 node / playwright / ffmpeg 的是外面那层「智能体外壳」。所以选工具时**先看它能不能在你电脑上执行命令**，其次才看用什么模型。

| 路线 | 能力 | 代表工具 | 结论 |
|---|---|---|---|
| **A** | 能跑命令 | 智谱 Z Code、Codex、Cursor、Gemini CLI、接了 DeepSeek/GLM 的 Claude Code 兼容客户端 | **推荐**，最接近原作 |
| **B** | 只能聊天 | DeepSeek 网页版等 | 你得当搬运工：存文件、跑命令、截图贴回去 |
| **C** | 只缺视频 | 已有 HTML，只缺 mp4 | 用仓库自带录制脚本，与模型无关 |

- [ ] 已确定路线并写在这里：**路线 ____**

---

## 1. 环境准备

### 1.1 必需

- [ ] Claude Code（含任意套餐）或等价的**能跑命令的智能体**
- [ ] **Node.js ≥ 20**（`node -v`）
- [ ] ffmpeg（**只在录视频、配音效时用**；不做视频可跳过）
- [ ] Python 3（**只用标准库**，`score.py` 不依赖第三方包）

### 1.2 安装（不依赖任何工具的 skill 机制，最稳）

```powershell
git clone https://github.com/elvarofficial/teardown D:\Github\teardown-duck
cd D:\Github\teardown-duck
npm install
npx playwright install chromium
```

- [ ] clone 完成
- [ ] `npm install` 成功（peer dep 冲突就用 `npm install --legacy-peer-deps`）
- [ ] `npx playwright install chromium` 跑完（约 150MB，等它下完）

### 1.3 走 skill 机制（可选，替代 1.2）

```powershell
npx skills add elvarofficial/teardown -g -a zcode      # 或 codex / cursor / gemini-cli
```

- [ ] `npx skills` 需要 **Node ≥ 22.20**，本机 Node 20 **走不通 → 用 1.2 的克隆法**
- [ ] Z Code 的 skill 目录与调用方式（`$teardown` 或 `/` 菜单）已对官方文档核实
- [ ] Codex / Cursor / Gemini CLI 的命令**只确认过搜索摘要**，需逐页打开官方文档复核

### 1.4 每次开聊的固定开场（**无论工具认不认 SKILL.md 都要说**）

```
SKILL_DIR is D:\Github\teardown-duck. Read $SKILL_DIR/SKILL.md first, then follow it.
```

### 1.5 规则文件在哪儿（**最容易踩的坑**）

| 工具 | 读什么 | 不读什么 |
|---|---|---|
| Z Code | `~/.zcode/AGENTS.md` + 工作区根 `AGENTS.md` | **不读 `CLAUDE.md`**，**不展开 `@import`** |
| Codex / Cursor | `AGENTS.md` | — |
| Gemini CLI | 默认 `GEMINI.md`（要读 `AGENTS.md` 需改设置） | — |

teardown 仓库**本身不带 `AGENTS.md`，只有 `SKILL.md`**。所以用 [`AGENTS-teardown.md`](./AGENTS-teardown.md) 存成工作区根 `AGENTS.md`；路线 B（聊天网页）就当第一条消息粘进去。

- [ ] 规则文件落位确认

### 1.6 接国产模型（对官方文档核过，**但模型名更新快，以官方为准**）

| 模型 | Anthropic 协议地址 | OpenAI 协议地址 | 模型名 |
|---|---|---|---|
| DeepSeek | `https://api.deepseek.com/anthropic` | `https://api.deepseek.com` | `deepseek-flash`（对应 V4.1-Flash-1017）、`deepseek-v4-pro` |
| 智谱 GLM | `https://open.bigmodel.cn/api/anthropic` | — | `glm-5.3[1m]`、`glm-5.3-flash[1m]` |

```powershell
$env:ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
$env:ANTHROPIC_AUTH_TOKEN = "<你的key>"
$env:ANTHROPIC_MODEL = "deepseek-flash[1m]"
```

- [ ] **GLM Coding Plan 的 key 与普通 API key 不通用**，且只能在官方支持工具里用（Z Code 排第一）——别挂到名单外的工具
- [ ] **Z Code 不能给第三方模型加自定义请求参数**
- [ ] 未核实项已知：Codex 能否直接用 DeepSeek 的 OpenAI 兼容接口；DeepSeek 模型能否吃图片输入

---

## 2. 十步执行

> **弱模型通用纪律**（每一步都适用）：一次只要一件事 → 先要参数表再要代码 → 一轮只改一处 → 每次输出完整文件别用补丁 → **文件超 400 行就拆** → 数字让脚本断言别让它心算。

### 第 1 步 选机器 + 找参考图（**决定成败**）

作者原话是吃过亏：不给参考，直接让它做穿山甲、犰狳、蝎子，**三个都成了普通玩具**；后来给一段真实的 V8 模拟器片段，它一块面板一块面板复原了出来。

选机器标准：**只有一个驱动输入 + 有真实数字可用**。参考可以是手册剖视图、一张照片或一段视频。

- [ ] 选定机器 + 单一输入（例：曲柄转角 / 喷气相位 / 风速）
- [ ] 拿到参考图，或让视觉模型先写成文字规格存 `ref/spec.md`
- [ ] **规格里每个数字都标了来源**（`from image` / `computed` / `my guess`）
- [ ] 部件清单能和图一一对上

规格模板（≤ 60 行）：

```
Look at the reference image(s) of [机器]. Do not draw or code anything yet.
Write a build spec in plain text, under 60 lines:
1. Parts list: every visible part group, with count, rough shape and material.
2. The ONE input that could drive the whole machine, and what each part does as that input goes from 0 to 1.
3. Dimensions for each part group. Mark every number either "from the image" or "my guess".
4. What the camera sees at the hero angle, and what is hidden behind it.
5. Which parts could open, hinge, unscrew or lift out to show what is inside.
```

### 第 2 步 建模（**模型先于画面**）

Build 提示词原版：

```
Build [机器] as an interactive 3D simulator. Reference attached: [一张图].
Build it from code in real units: [部件清单].
Before you draw anything, write the model as pure functions of one input: [输入 0→1]. Use real numbers: [...].
Check them by hand and show me the check. If you are not sure a number is real, say so and tell me where it comes from.
Every part, every panel and every label reads from that one model. Nothing is animated by hand.
```

**作者为什么说有效**：模型先于画面 → 零件、仪表、时间线读同一个函数，不会对不上；整机只由一个数字驱动才像真机器（12 个零件各自手动做动画，只是 12 段动画）。

对照例子（塞斯纳）：一根液压缸推 201 mm 齿条 → 32 齿齿轮转正好半圈 → 起落架腿摆 180° 收进机身。手算也对得上：模数 4 mm、32 齿 → 分度圆 128 mm → 半圈周长约 201 mm。

**弱模型分四轮**：

- [ ] **2A**：只要参数表，不写代码。列名字 / 数值 / 单位 / 来源（参考图 / 计算 / 我猜的）→ **你确认了表再往下**
- [ ] **2B**：写 `model.js`（**不含任何 three.js**），再写 `check.mjs` 用断言验证（推力、周期、关节角范围）
- [ ] **2C**：几何按总成拆；**先做一条手臂**，对着参考图修好再复制成 8 条；手臂用实例化网格，**整条手臂一次绘制调用**
- [ ] **2D**：先做最小舞台，出第一张静帧，后面所有检查都靠它

- [ ] `check.mjs` 全过
- [ ] 一张静帧里所有部件都在，没有明显穿模

> **量级预期**：一台机器 **1600–2200 行**。仓库实测：V8 ≈ 1900、塞斯纳 ≈ 1600、Strandbeest ≈ 2200；章鱼 25 秒片 = 2616 行。**别指望一轮出完。**

### 第 3 步 控制台面板

```
Lay out a console around the machine at 1600×900:
- the title and the main live number top left, big: [主读数]
- live charts that move with the machine: [随时间变化的曲线]
- a schematic panel that redraws the mechanism in 2D from the same model
- one button per subsystem: isolate it, cut it, show it alone [子系统列表]
- camera views as buttons: [hero, front, side, top, underside]
- callouts with thin leader lines into the parts they name
Every panel redraws from the frame's state. No number on screen is typed in.
```

- [ ] 一次一块面板地加，第一轮只做布局框架 + 两块面板
- [ ] **数字不是写死的**：改一个参数（如喷口直径 38 → 30），推力数字必须跟着变。不变 = 写死了

### 第 4 步 定风格

```
Style: a clean study model on a pale studio.
- light background, soft shadows on an invisible floor, one accent colour for the part that is working right now
- the machine fills 60 to 70% of its view
- dark parts glossy, liners glass, metal roughness at least 0.45 so it never streaks white
- if a part is near-white, give it a thin ink outline or a darker ground
- pick the camera for the mechanism: if it collapses into a lattice face-on, use a 3/4 view
```

- [ ] 弱模型别说「好看一点」，**直接给色值**
- [ ] 近白色件加了墨线或深色地（Strandbeest 白管在奶油底上看不见 → 换沙地 + 墨线）

### 第 5 步 自检（**像挑刺的人一样**）

```
Before you show me anything:
1. Render a still at every beat of the tour and read each one: a part passing through another,
   a part floating off its mount, a label covering what it names, a number that disagrees with the pose.
2. Scrub every transition at 0.2 s steps and look for a jump.
3. Fix collisions with a number in the parameter block. Never hide them with the camera.
Tell me what you checked and what you fixed. Show me the stills.
```

- [ ] **逐张写一行发现**，每张都要写（弱模型很爱说「都没问题」），自己再抽一两张核对
- [ ] 碰撞用参数块里的一个数字修，**没有靠挪相机**
- [ ] **看不了图的模型 → 把截图丢给能看图的模型**，把意见转回去

> **作者靠这步抓出两个差点上线的 bug**：兔子的脸穿出帽子壁（一个数 0.222 m 放回去）；六足的腿每次换步态都会飞出去（直到脚瞄准了下一个真实落脚点）。

**必做的额外修正（文章发现的坑）**：仓库三个示例的 `timeline.json` 里**只有一个 `duration`**，节拍时间写死在 `film.js` 和 `score.py` 两处。你新做一台必须自己写：

```
Write sims/<机器>-film/timeline.json with every beat of the tour in seconds, as flat numbers keyed by name.
film.js and score.py must READ these times from this file, never retype them.
```

- [ ] `timeline.json` 是节拍时间的**唯一真源**
- [ ] 不改的话 `--stills beats` 只出一张图，音效也对不上

### 第 6 步 做成能互动的网页

```
Make the simulator a page people drive:
- the tour from the film plays by itself, with a cursor that walks to each button and presses it
- any click, drag, scroll or key hands control to the visitor; 25 seconds of quiet hands it back
- drag to orbit, scroll to zoom, a key to hide the panels
- warm every shader before the first frame so the page never freezes
- test it on an integrated GPU and add quality steps: no ambient occlusion, a lower pixel ratio,
  smaller shadows, panels redrawn every other frame
```

- [ ] `live.js` 照抄 `cessna-shared/live.js` 结构，只改机器相关部分；按钮 / 巡览 / 降质档位**分三轮加**
- [ ] 首帧前预热着色器
- [ ] **集显才是真测试**（作者六足集显 15fps → 加降质档位后 75fps）

### 第 7 步 录成视频（需要 ffmpeg + 显卡）

```
Record the tour: render(t) has to be a pure function of time, so draw every frame at 60 fps at
1920×1080 in headless Chrome and pipe it into ffmpeg as H.264, yuv420p, faststart.
Then show me a contact sheet of every beat.
```

```powershell
node sims/build.mjs <机器>-film
node sims/capture.mjs <机器>-film --size 1600x900 --dpr 1.2 --out teardown-out/<名字>-silent.mp4
```

- [ ] 排查顺序：`ffmpeg -version` → `python3 --version` → `npx playwright install chromium` 跑过没有
- [ ] 启动时打印一行 `gpu:`，**若是 SwiftShader = 软件渲染，会很慢**（作者无显卡，渲一张静帧约 18 秒，25 秒 60fps = 1500 帧要跑好几小时）→ **录视频请用有显卡的电脑**
- [ ] 逐帧渲染而不是录屏：录屏软件在 GPU 吃紧时会掉帧，能按时间点定位的巡览不会

> **通用性发现（对路线 B/C 有用）**：`capture.mjs` 能录**任何**网页，不限于 teardown 结构。只要页面暴露 `window.seek(秒)`、设好 `window.DURATION` 和 `window.FPS`、且地址带 `?render` 时不用自己的动画循环，就能直接出片。

### 第 8 步 配乐

```
Score it in code on the same timeline: [soft ambient pads, a low whoosh on every jet pulse,
a quiet click on every button press, a soft pop when a part separates].
Master to -14 LUFS with the true peak under -1 dB and mux it into the video.
```

- [ ] 声音用**纯 Python 合成**，放 `sfx/`
- [ ] 所有时间读 `timeline.json`，**别手写数字**
- [ ] 声音是点缀，连续运动保持安静
- [ ] 弱模型一律照抄 `cessna-shared/score.py`（只有 41 行），别让它从零设计合成器

### 第 9 步 发布上线

```
Publish the simulator as a page:
- keep the HTML under 1 MB; move any large model out as a file next to the page
- a 1200×630 preview card from the best frame, with absolute image URLs
- deploy it to Vercel
```

**1MB 这条线是作者吃亏换来的**：兔子页面带模型 15.9MB → X 不显示链接卡片；模型外置后 967KB → 卡片出来了。

**体积预算（作者实测 build 出来的 800KB 底子）**：

| 项 | 体积 |
|---|---|
| 字体 | ≈ 114 KB |
| 大头 | 压缩后的 three.js + 后处理 |
| 塞斯纳整台机器代码 | ≈ 74 KB |
| **留给你的机器** | **≈ 150–200 KB** |

- [ ] build 完报一下 `ls -l` 字节数
- [ ] Vercel 部署要用自己的账号，智能体做不了就自己拖目录

### 第 10 步 加一个滑块，让人把它玩坏

```
Add one slider for [水流, 0 to 3 m/s] and run the model live when it moves: [...]
Show it on the same panels.
```

作者的说法：**谁能把机器推过极限，谁就知道每个数是干什么的。**

- [ ] 只改 `model.js` 加一个输入，**别动几何**
- [ ] 改完先跑 `check.mjs`

---

## 3. 排障速查表

| 现象 | 常见原因 | 怎么跟模型说 |
|---|---|---|
| 零件穿模 | 参数没留余量 | 指出哪个零件在几秒穿了哪个，要求**只改参数块里的一个数**，说清旧值新值，**别动相机** |
| 白屏 / 黑屏 | 着色器 NaN；smoothstep 边界写反；pow() 底数为负 | 先看控制台报错，再逐个检查着色器 |
| 前几帧好，后面全黑 | NaN 经 bloom 扩散整帧 | 找出输出 NaN 的着色器，限制输入范围，emissive 压到 1.0 以下 |
| 页面卡 | 某着色器算重复；AO、阴影太大 | 先量哪个着色器最贵，再加降质档位，报前后帧率 |
| 页面超 1MB，X 没链接卡 | 模型内嵌 | 用 `build.json` 把大模型外置，报新体积 |
| 面板数字和姿态对不上 | 数字写死了 | 要求只从 `state(p)` 读，改一个参数验证面板会变 |
| 代码被截断 | 单文件太长 | 别说「继续」，让它**从第 1 行起重写整个文件**，超 400 行就拆成两个 |
| 巡览和声音对不上 | 节拍时间写死在两处 | 两边都改成读 `timeline.json` |
| 多臂糊成栅栏 | 正面视角 | 镜头改成沿身体轴线的 **3/4 视角** |
| 视频第一秒是空的 | 第 0 帧没画机器 | 第 0 帧就是封面，必须已经画出机器，背景用浅色 |

**Windows 专属坑**：`smoothstep(a,b,x)` 在 `a > b` 时返回 0 → 写成 `1.0 - smoothstep(b,a,x)`。

---

## 4. 本机环境事实（2026-11-04 核实）

| 项 | 状态 |
|---|---|
| Node | ✅ v20.18.1（`D:\tools\node-v20.18.1-win-x64`） |
| npm / npx | ✅ 10.8.2 |
| git | ✅ `D:\tools\MinGit\cmd\git.exe` |
| Python | ✅ 3.13（`C:\Users\1\AppData\Local\Programs\Python\Python313\python.exe`，仅标准库） |
| 网络 | ✅ GitHub 可达（HTTP 200） |
| **ffmpeg** | ❌ **未安装** → 本轮不做视频出片 / 配乐 mux |
| Shell | PowerShell 5.1，**不支持 `&&` `||`**，用 `;` + `$ErrorActionPreference='Stop'` + `$LASTEXITCODE` |

**因此 `npx skills`（需 Node ≥ 22.20）本机走不通 → 一律走克隆法。**

---

## 5. 交付物清单

一台机器做完，产出应是：

- [ ] `sims/<机器>-film/` 下：`model.js` / `geometry.js` / `stage.js` / `console.js` / `film.js` / `live.js` / `timeline.json`（+ `check.mjs`、`score.py`）
- [ ] 单文件 HTML，**字节数 < 1MB**，报告 `ls -l`
- [ ] 每个节拍一张静帧
- [ ] 复现命令清单（clone → install → build → check → stills）

---

## 6. 参考链接

- 方法原文（@elvar_official）：<https://x.com/elvar_official/status/2116174609355571402>
- 章鱼视频（@0x_fokki）：<https://x.com/0x_fokki/status/2116289885870981296>
- teardown 仓库：<https://github.com/elvarofficial/teardown>
- 上游 claude-motion：<https://github.com/whaleyxbt/claude-motion>
- 在线示例：<https://visual-learning.app>
- Z Code 文档：<https://zcode.z.ai/cn/docs>
- skills CLI：<https://github.com/vercel-labs/skills>
- 花花大人的 Codex 移植：<https://github.com/HuaJuan2023/teardown-codex>
