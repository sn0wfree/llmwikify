# MCPorter Bridge 部署指南

## 概述

[MCPorter](https://github.com/steipete/mcporter) 是一个 TypeScript MCP 运行时和 CLI 工具集，用于发现、调用和管理系统中已配置的 MCP 服务器。

[MCPorter Bridge](https://github.com/Citrus086/mcporter-bridge) 是一个 FastMCP 桥接服务器，将 `mcporter` 注册表中的所有 MCP 服务聚合为一个统一端点，供 LLM 客户端（如 opencode、Claude Code、Codex 等）连接。

### 架构

```
┌─────────────────────────────────────────────────────────────┐
│                        opencode                             │
│                   (MCP Client)                              │
│                                                             │
│  配置: ~/.config/opencode/opencode.json                     │
│  ┌──────────────────────────────────────────────┐           │
│  │ mcp:                                         │           │
│  │   mcporter-bridge:                           │           │
│  │     type: local                              │           │
│  │     command: ["python3", "-m", "mcporter_bridge"] │     │
│  └──────────────────────────────────────────────┘           │
└─────────────────────┬───────────────────────────────────────┘
                      │ stdio (opencode 启动子进程)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    mcporter-bridge                          │
│              (FastMCP 桥接服务器)                            │
│                                                             │
│  读取: ~/.mcporter/mcporter.json                            │
│  ┌──────────────────────────────────────────────┐           │
│  │ mcpServers:                                  │           │
│  │   llmwikify: :8765/mcp (remote)              │           │
│  │   [其他 MCP 服务...]                          │           │
│  └──────────────────────────────────────────────┘           │
└──────────┬──────────────────────┬───────────────────────────┘
           │ HTTP                 │ HTTP
           ▼                      ▼
┌──────────────────┐    ┌──────────────────┐
│    llmwikify     │    │  其他 MCP 服务    │
│    :8765/mcp     │    │  (按需添加)       │
└──────────────────┘    └──────────────────┘
```

### 核心优势

| 特性 | 价值 |
|------|------|
| **统一入口** | 客户端只需配置一个 MCP 连接 |
| **自动发现** | mcporter 自动扫描 ~/.mcporter/mcporter.json 及其他客户端配置 |
| **懒加载** | 大型 MCP 按需激活，节省上下文 |
| **多客户端** | opencode、Claude、Codex、Cline、Cursor 共享同一注册表 |
| **工具发现** | `mcporter_list_servers` 提供完整 MCP 全景视图 |

---

## 安装

### 1. 安装 mcporter（Node.js，全局安装）

```bash
# 全局安装（推荐，所有项目可用）
sudo npm install -g mcporter
```

验证安装：
```bash
mcporter --version
which mcporter  # 应显示 /usr/bin/mcporter 或 /usr/local/bin/mcporter
```

### 2. 安装 mcporter-bridge（Python）

```bash
pip install mcporter-bridge
```

验证安装：
```bash
python3 -m mcporter_bridge --help
```

---

## 配置

### 1. 创建 mcporter 注册表

创建文件 `~/.mcporter/mcporter.json`：

```json
{
  "mcpServers": {
    "llmwikify": {
      "type": "remote",
      "url": "http://localhost:8765/mcp",
      "description": "LLM Wiki Fy - 高级知识库，支持自定义页面类型和知识图谱",
      "tags": ["wiki", "knowledge-base", "custom-pages", "graph"]
    }
  }
}
```

### 2. 注册表配置说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 连接类型：`remote`（HTTP）或 stdio 配置 |
| `url` | string | remote 必填 | HTTP 端点 URL |
| `command` | string | stdio 必填 | 启动命令 |
| `args` | array | stdio 可选 | 启动参数 |
| `description` | string | 否 | 服务描述（帮助 LLM 理解用途） |
| `tags` | array | 否 | 标签（用于分类和搜索） |

### 3. 添加新 MCP 服务

在 `~/.mcporter/mcporter.json` 的 `mcpServers` 中添加新条目：

**HTTP 服务示例**：
```json
{
  "mcpServers": {
    "my-new-service": {
      "type": "remote",
      "url": "http://localhost:9000/mcp",
      "description": "服务描述",
      "tags": ["tag1", "tag2"]
    }
  }
}
```

**stdio 服务示例**：
```json
{
  "mcpServers": {
    "my-stdio-service": {
      "command": "npx",
      "args": ["-y", "@some/mcp-server"],
      "description": "服务描述",
      "tags": ["tag1"]
    }
  }
}
```

---

## systemd 服务管理

### 服务文件位置

`~/.config/systemd/user/mcporter-bridge.service`

### 服务配置

```ini
[Unit]
Description=MCPorter Bridge - Unified MCP Gateway (HTTP)
After=network.target

[Service]
Type=simple
Environment=PATH=/home/ll/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=FASTMCP_SHOW_SERVER_BANNER=false
ExecStart=/home/ll/.local/bin/mcporter-bridge-http
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### 常用命令

```bash
# 设置环境变量（用户级 systemd 需要）
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# 重新加载配置
systemctl --user daemon-reload

# 启动服务
systemctl --user start mcporter-bridge

# 停止服务
systemctl --user stop mcporter-bridge

# 重启服务
systemctl --user restart mcporter-bridge

# 查看状态
systemctl --user status mcporter-bridge

# 设置开机自启
systemctl --user enable mcporter-bridge

# 查看日志
journalctl --user -u mcporter-bridge -f

# 查看最近 50 行日志
journalctl --user -u mcporter-bridge -n 50
```

---

## 客户端配置

### opencode

**全局配置**（推荐，所有项目可用）：

编辑 `~/.config/opencode/opencode.json`：

```json
{
  "mcp": {
    "llm-wiki-kit": {
      "type": "remote",
      "url": "http://localhost:17800/mcp",
      "enabled": true
    },
    "mcporter-bridge": {
      "type": "local",
      "command": ["python3", "-m", "mcporter_bridge"],
      "enabled": true
    }
  }
}
```

**项目级配置**（可选，覆盖全局配置）：

编辑 `项目目录/opencode.json`：

```json
{
  "mcp": {
    "mcporter-bridge": {
      "type": "local",
      "command": ["python3", "-m", "mcporter_bridge"],
      "enabled": true
    }
  }
}
```

> **注意**：opencode 使用 `local` 类型时会自行启动 mcporter-bridge 子进程（stdio 模式）。
> systemd 服务用于后台常驻运行，方便多个客户端共享。

---

## 验证

### 1. 检查 mcporter 发现

```bash
# 设置 PATH 包含 mcporter
export PATH="/home/ll/llmwikify/node_modules/.bin:$PATH"

# 列出所有 MCP 服务器
mcporter list --json

# 查看特定服务的工具
mcporter list llmwikify --schema
```

### 2. 检查 mcporter-bridge 端点

```bash
# HTTP 模式（systemd 服务）
curl -s -o /dev/null -w "%{http_code}" http://localhost:8766/mcp
# 应返回 406（端点存在，需要 MCP 协议请求）

# 测试工具调用（需要 MCP 客户端）
# 在 opencode 中调用 mcporter_list_servers
```

### 3. 端到端测试

在 opencode 中：
1. 调用 `mcporter_list_servers` - 应返回所有注册的 MCP 服务
2. 调用 `mcporter_call_tool` - 应能调用任意服务的工具
3. 调用 `mcporter_help` - 应显示工具帮助信息

---

## 故障排除

### 问题 1：mcporter 找不到

**错误**：`mcporter: command not found`

**解决**：
```bash
# 检查是否全局安装
which mcporter

# 如果未安装，全局安装
sudo npm install -g mcporter

# 验证
mcporter --version
```

### 问题 2：MCP 服务离线

**错误**：`connect ECONNREFUSED 127.0.0.1:8765`

**解决**：
1. 确认目标 MCP 服务已启动
2. 检查端口是否正确：`lsof -i :8765`
3. 验证端点：`curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/mcp`

### 问题 3：systemd 服务启动失败

**检查日志**：
```bash
journalctl --user -u mcporter-bridge -n 50 --no-pager
```

**常见原因**：
- PATH 环境变量不正确
- Python 或 mcporter-bridge 未安装
- 端口冲突

**解决**：
```bash
# 手动测试启动
python3 -m mcporter_bridge

# 检查端口占用
lsof -i :8766
```

### 问题 4：opencode 无法连接

**检查**：
1. opencode.json 配置是否正确
2. mcporter-bridge 是否可执行：`which python3 && python3 -m mcporter_bridge --help`
3. 查看 opencode 日志中的 MCP 连接错误

---

## 高级用法

### 懒加载（按需加载大型 MCP）

对于消耗大量上下文的 MCP 服务（如浏览器自动化），可以配置懒加载：

```bash
# 创建 heavy MCP 目录
mkdir -p ~/.mcporter/heavy/available

# 将大型 MCP 配置移到单独文件
echo '{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"],
      "description": "浏览器自动化",
      "tags": ["浏览器"]
    }
  }
}' > ~/.mcporter/heavy/available/playwright.json

# 从主配置中移除该服务
```

在 opencode 中使用：
1. `mcporter_list_servers()` - 查看 active 和 available 列表
2. `mcporter_activate_mcp(name="playwright")` - 激活服务
3. 使用工具...
4. `mcporter_deactivate_mcp(name="playwright")` - 释放上下文

### 自定义环境变量

```bash
# 覆盖 mcporter 二进制路径
export MCPORTER_BRIDGE_MCPORTER_BIN=/path/to/mcporter

# 限制输出长度
export MCPORTER_BRIDGE_MAX_OUTPUT_CHARS=20000

# 自定义 HTTP 端口（systemd 服务）
# 编辑 ~/.config/systemd/user/mcporter-bridge.service
# 修改 ExecStart 行添加环境变量
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `~/.mcporter/mcporter.json` | MCP 服务注册表 |
| `~/.config/systemd/user/mcporter-bridge.service` | systemd 服务配置 |
| `~/.local/bin/mcporter-bridge-http` | HTTP 模式启动脚本 |
| `~/.config/opencode/opencode.json` | opencode MCP 配置 |

---

*最后更新：2026-04-14 | mcporter v0.8.1 | mcporter-bridge v0.1.0*
