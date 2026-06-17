# LapTalk Cockpit 插件

通过 [Cockpit](https://cockpit-project.org/) Web 面板管理 LapTalk 平台：
**服务启停** · **定时调度配置** · **实时日志** · **系统状态**。

## 功能

| 模块 | 能力 |
|---|---|
| **服务控制** | 一键 启动 / 停止 / 重启（调用 `start_platform.sh`），实时回显命令输出，状态指示灯 |
| **定时调度** | 配置数据采集 cron、AI 全流程 cron（小时/分钟 + 开关），保存即时热生效（自动重载调度器，无需重启后端） |
| **系统状态** | 文章数、事件数、调度器状态、pipeline 当前步骤，附主页/API 文档链接 |
| **实时日志** | `tail -f` 跟踪 `logs/backend.log`，可切换显示行数（200/500/1000/5000），自动滚动 |

> 配置生效策略：调度配置走后端 `PUT /api/fetch/schedule`（内部触发 `reload_scheduler()`），保存即生效；
> 服务启停走 `start_platform.sh`，显式按钮 + 二次确认。

## 目录结构

```
cockpit/
├── manifest.json    # Cockpit 插件清单（注册到「工具」菜单）
├── index.html       # 单页面（四区块布局 + 路径注入点）
├── laptalk.js       # 业务逻辑：Service / Config / LogView 三模块
├── laptalk.css      # 样式（PatternFly 风格，自包含）
├── install.sh       # 一键安装脚本
└── README.md        # 本文档
```

## 安装

### 方式一：一键脚本（推荐）

在**部署服务器**（Linux，已装 Cockpit）上执行：

```bash
# 项目已在服务器上（如在 /opt/LapTalk_NewsAggregationTool）
cd /opt/LapTalk_NewsAggregationTool

bash cockpit/install.sh

# 若项目不在默认位置，用环境变量指定：
# LAPTALK_HOME=/your/path bash cockpit/install.sh

# 若 /usr/local/share 不可写，加 sudo（保留环境变量）：
# sudo -E env LAPTALK_HOME=/your/path bash cockpit/install.sh
```

脚本会：
1. 校验 `start_platform.sh` 存在
2. 把插件文件复制到 `/usr/local/share/cockpit/laptalk/`
3. 注入实际项目路径到 `index.html`（替换 `__LAPTALK_HOME__` 占位符）
4. 检查权限（项目目录归属、日志可读、脚本可执行）

### 方式二：手动安装

```bash
# 1. 复制文件
sudo mkdir -p /usr/local/share/cockpit/laptalk
sudo cp cockpit/{manifest.json,index.html,laptalk.js,laptalk.css} \
     /usr/local/share/cockpit/laptalk/

# 2. 把 index.html 里的 __LAPTALK_HOME__ 替换为项目实际路径
sudo sed -i 's|__LAPTALK_HOME__|/opt/LapTalk_NewsAggregationTool|g' \
     /usr/local/share/cockpit/laptalk/index.html
```

### 安装后

1. **退出当前 Cockpit 会话并重新登录**（Cockpit 重登后才扫描新插件）
2. 左侧菜单「工具」下出现「LapTalk 平台」
3. 如改了代码，浏览器按 `Ctrl+Shift+R` 强刷

## 卸载

```bash
sudo rm -rf /usr/local/share/cockpit/laptalk
```

## 权限模型

- 插件以**登录 Cockpit 的当前用户**身份执行 `start_platform.sh` 和 `tail`
- 调用使用 `superuser: "try"`：不强制 root；非特权也能跑（端口 8081 > 1024）
- **前提**：该用户对项目目录（含 `logs/` `pids/`）有读写权限
- 若权限不足，`install.sh` 会提示 `chown`/`chmod` 命令

## 依赖的后端 API

插件完全复用现有后端接口，**不修改后端代码**：

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 判断后端是否运行 |
| `GET /api/stats` | 文章数、事件数 |
| `GET /api/fetch/schedule` | 读取定时调度 |
| `PUT /api/fetch/schedule` | 保存调度（自动 `reload_scheduler`） |
| `GET /api/pipeline/status` | pipeline 当前状态 |
| `bash start_platform.sh start/stop/restart` | 服务启停（`cockpit.spawn`） |
| `tail -n N -f logs/backend.log` | 实时日志（`cockpit.spawn`） |

## 环境要求

- Cockpit ≥ 236（提供 `cockpit.js` 和 `cockpit.spawn`/`cockpit.file` API）
- 浏览器：现代 Chrome / Firefox / Edge
- 后端已在 `localhost:8081` 监听（`main.py` 默认）
