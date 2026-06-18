# QFXM — Telegram 多账号群控系统 开发文档

> 本文档是项目唯一的权威说明。任何接手此项目的开发者（包括 AI）都应先读完本文档再动手写代码。

---

## 一、项目目标

构建一个 **Telegram 多账号批量管理工具**，采用 **瘦客户端 + 厚服务端** 架构：

- **服务器（43.165.173.63）**：运行 FastAPI + APScheduler + Telethon 客户端 + SQLite 数据库 + session 文件。任务在服务器上持续执行，本地 PC 关机不影响。
- **本地 PyQt5 GUI**：纯控制面板，通过 HTTP API 调用服务器，自身不运行任何 Telegram 逻辑。

### 核心功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 批量导入协议号 | ✅ 完成 | 支持文件夹格式，打包 ZIP 上传服务器 |
| 批量验证账号状态 | ✅ 完成 | 服务器连接 Telegram 返回：正常/失效/封号/多地登录 |
| 批量修改账号资料 | ✅ 完成 | 批量改名字、简介、头像（已验证可用）|
| 定时消息任务 | ✅ 完成 | APScheduler 持久化，重启不丢失 |
| 清理失效账号 | ✅ 完成 | 一键删除 invalid/banned 账号，保留正常账号 |
| 服务器自动启动 | ✅ 完成 | systemd 服务，服务器重启后自动恢复 |

---

## 二、技术栈

| 层 | 技术 | 版本 | 说明 |
|----|------|------|------|
| Telegram 客户端 | **Telethon** | 1.36.0 | 使用 MemorySession，避免 tmp_auth_key 列问题 |
| 定时任务 | **APScheduler** | 3.10.4 | SQLAlchemyJobStore 持久化到 SQLite |
| HTTP 服务 | **FastAPI** + uvicorn | 最新 | 服务器端 REST API |
| 数据库 | **SQLite** | — | 无需安装，路径由 .env 的 DB_PATH 指定 |
| GUI | **PyQt5** | — | 桌面原生应用，仅用于本地控制面板 |
| HTTP 客户端 | requests | — | 本地 GUI 调用服务器 API |
| 配置 | python-dotenv | — | .env 文件管理配置 |

> ⚠️ 早期版本用过 Pyrogram，已全面切换到 Telethon。代码中不应再出现 Pyrogram 相关引用。

---

## 三、项目目录结构

```
qfxm/
├── DEVELOPMENT.md          ← 本文件，开发全局说明
├── requirements.txt        ← Python 依赖
├── .env                    ← 环境变量（不进 git）
├── .env.client             ← 本地客户端 .env 模板
├── .env.server             ← 服务器端 .env 模板
├── .gitignore
│
├── main.py                 ← 程序唯一入口
├── config.py               ← 全局配置读取（含 SERVER_URL）
├── database.py             ← 数据库初始化 & 表创建
├── api.py                  ← FastAPI 服务端（服务器运行）
├── api_client.py           ← HTTP 客户端（本地 GUI 调用服务器）
│
├── models/                 ← 数据模型 (SQLModel)
│   ├── account.py
│   ├── group.py
│   └── task.py
│
├── core/                   ← 核心技术模块
│   ├── session_importer.py ← 协议号文件夹解析与导入
│   ├── client_manager.py   ← Telethon 客户端池
│   ├── scheduler.py        ← APScheduler 封装
│   └── profile_manager.py  ← 批量修改头像/名称/简介
│
├── services/               ← 业务逻辑层
│   ├── account_service.py  ← 导入、验证、状态管理（本地模式）
│   ├── message_service.py  ← 消息发送、错误重试
│   ├── group_service.py    ← 群组管理、任务恢复
│   └── proxy.py            ← 模式切换器：本地 or 远程 ★
│
├── gui/                    ← PyQt5 界面
│   ├── main_window.py      ← 主窗口（状态栏显示服务器状态）
│   └── tabs/
│       ├── account_tab.py  ← 账号管理界面
│       ├── group_tab.py    ← 群组管理界面
│       └── task_tab.py     ← 定时任务界面
│
├── sessions/               ← session 文件（不进 git，服务器端在 /home/ubuntu/qfxm/sessions/）
└── logs/                   ← 日志文件（不进 git）
```

---

## 四、双端架构说明

### 运行模式切换（`services/proxy.py`）

`config.py` 读取 `.env` 中的 `SERVER_URL`：

- **`SERVER_URL` 有值** → 远程模式：所有业务调用走 `api_client.py` → HTTP → 服务器
- **`SERVER_URL` 为空** → 本地模式：直接调用 `services/` 本地服务

GUI 所有 Tab 统一从 `services.proxy` 导入函数，不感知当前是哪种模式。

### 本地客户端 `.env`

```env
SERVER_URL=http://43.165.173.63:8000
API_KEY=qfxm2024
```

### 服务器端 `.env`（位于 `/home/ubuntu/qfxm/.env`）

```env
API_KEY=qfxm2024
DB_PATH=/home/ubuntu/qfxm/qfxm.db
SESSIONS_DIR=/home/ubuntu/qfxm/sessions
LOG_LEVEL=INFO
SEND_DELAY_MIN=3
SEND_DELAY_MAX=15
PORT=8000
# SERVER_URL 不设置（留空），服务器本身是本地模式
```

---

## 五、协议号文件格式

每个协议号是一个**以手机号命名的文件夹**，导入时从本地选择父文件夹，程序打包成 ZIP 上传服务器：

```
D:\桌面\协议号\
└── 916299146095\               ← 文件夹名 = 手机号
    ├── 916299146095.session    ← Telethon session 文件（核心）
    ├── 916299146095.json       ← 账号元数据（app_id/hash、2FA、设备信息等）
    ├── 2fa.txt                 ← 2FA 密码（备用，JSON 里也有）
    └── tdata\                  ← TDesktop 数据（暂不使用）
```

**JSON 关键字段：**
- `app_id` / `app_hash`：该账号专用的 API 凭据
- `twoFA`：2FA 密码
- `device`、`app_version`：设备信息（连接时伪装，不能乱改）

**上传流程（`api_client.py → _upload_folder()`）：**
1. 本地 GUI 选择父文件夹
2. 逐个子文件夹打包成 ZIP（排除 `-journal` 临时文件）
3. POST 到 `/accounts/upload`，服务器解压后调用 `import_from_folders()`
4. 返回导入结果

---

## 六、数据库表设计

### accounts 表

```sql
id              INTEGER PRIMARY KEY
name            TEXT                    -- 账号备注名
phone           TEXT UNIQUE             -- 手机号
session_path    TEXT UNIQUE             -- session 文件路径（服务器本地）
app_id          INTEGER                 -- 来自 JSON，每账号独立
app_hash        TEXT                    -- 来自 JSON，每账号独立
two_fa          TEXT                    -- 2FA 密码
device_model    TEXT                    -- 设备型号
app_version     TEXT                    -- 客户端版本
first_name      TEXT
last_name       TEXT
user_id         INTEGER
status          TEXT DEFAULT 'unknown'  -- unknown/active/restricted/banned/invalid
last_checked    DATETIME
error_msg       TEXT
created_at      DATETIME
```

### groups 表

```sql
id              INTEGER PRIMARY KEY
tg_id           TEXT UNIQUE             -- Telegram 群组 ID
username        TEXT                    -- 群组 @username
title           TEXT                    -- 群组标题
account_id      INTEGER FK→accounts     -- 用于进入该群的账号
joined_at       DATETIME
```

### tasks 表

```sql
id              INTEGER PRIMARY KEY
name            TEXT                    -- 任务备注名
account_id      INTEGER FK→accounts
group_id        INTEGER FK→groups
message_text    TEXT                    -- 消息内容
media_path      TEXT                    -- 可选，图片路径（服务器本地）
cron_expr       TEXT                    -- cron 表达式，如 "0 9 * * *"
timezone        TEXT DEFAULT 'Asia/Shanghai'
is_active       BOOLEAN DEFAULT TRUE
last_run        DATETIME
run_count       INTEGER DEFAULT 0
fail_count      INTEGER DEFAULT 0
created_at      DATETIME
```

---

## 七、关键技术问题与解决方案

### 问题1：APScheduler + Python 3.13 的 kwargs 验证 Bug

**现象**：创建任务时报 `The following arguments have not been supplied: task_id`

**根本原因**：APScheduler 3.10.4 在 Python 3.13 下对 `kwargs` 参数有签名验证 bug。

**尝试过但失败的方法**：
- `functools.partial(func, task_id=task_id)` — SQLAlchemy Store 无法序列化 partial 对象
- `job_kwargs = {"task_id": task_id}` — 同样触发验证 bug

**最终解决方案**：改用 `args=(task_id,)` 位置参数，APScheduler 不对位置参数做签名验证，且纯 int 元组可被序列化。

```python
# core/scheduler.py — 关键实现
_scheduler.add_job(func, trigger=trigger, id=job_id, args=(task_id,))
# 对应的任务函数签名必须是：def run_task(task_id: int): ...
```

### 问题2：任务函数签名

所有注册到 APScheduler 的任务函数必须接受 `task_id: int` 作为第一个位置参数：

```python
def send_scheduled_message(task_id: int):
    # 从数据库按 task_id 查询任务详情
    ...
```

### 问题3：Telethon MemorySession

服务器使用 `MemorySession` 而非文件 session，避免 `tmp_auth_key` 列兼容性问题。session 数据在启动时从 `.session` 文件导入，运行期间保存在内存中。

### 问题4：`logs/` 目录首次运行报错

`logging.FileHandler("logs/qfxm.log")` 在目录不存在时崩溃。修复：`main.py` 最顶部加 `os.makedirs("logs", exist_ok=True)`，在 `basicConfig` 之前执行。

---

## 八、FastAPI 服务端接口（`api.py`）

所有接口需要请求头 `X-API-Key: <API_KEY>`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回活跃任务数 |
| GET | `/accounts` | 账号列表 |
| POST | `/accounts/upload` | 上传协议号 ZIP，解压并导入 |
| POST | `/accounts/{id}/check` | 验证单个账号状态 |
| DELETE | `/accounts/{id}` | 删除账号 |
| POST | `/accounts/profile` | 批量修改账号资料 |
| POST | `/upload/media` | 上传图片文件，返回服务器路径 |
| GET | `/groups` | 群组列表 |
| POST | `/groups/resolve` | 解析群组 @username 或 ID |
| POST | `/groups/save` | 保存群组到数据库 |
| GET | `/tasks` | 任务列表（含 next_run_str 字段）|
| POST | `/tasks` | 创建任务 |
| PUT | `/tasks/{id}` | 更新任务 |
| DELETE | `/tasks/{id}` | 删除任务 |

---

## 九、服务器部署

### 环境信息

- 系统：Ubuntu 22.04
- IP：43.165.173.63
- 端口：8000（已在腾讯云安全组放行）
- Python：3.12（通过 venv 隔离）
- 代码目录：`/home/ubuntu/qfxm/`
- venv 路径：`/home/ubuntu/qfxm/venv/`

### systemd 服务（已配置，开机自启）

服务文件位于 `/etc/systemd/system/qfxm.service`：

```ini
[Unit]
Description=QFXM Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/qfxm
ExecStart=/home/ubuntu/qfxm/venv/bin/python main.py --no-gui --api
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

常用命令：

```bash
sudo systemctl status qfxm     # 查看状态
sudo systemctl restart qfxm    # 重启服务
sudo systemctl stop qfxm       # 停止服务
sudo journalctl -u qfxm -f     # 实时查看日志
```

---

## 十、代码更新流程

本地修改代码后，推送到 GitHub，服务器拉取并重启：

```bash
# 本地（Windows）
git add .
git commit -m "修复说明"
git push

# 服务器（FinalShell SSH）
cd ~/qfxm
git pull
sudo systemctl restart qfxm
```

GitHub 仓库：https://github.com/xiaofei09110/qfxm（公开）

---

## 十一、开发进度

| 状态 | 模块 | 说明 |
|------|------|------|
| ✅ 完成 | 项目架构 | 瘦客户端 + 厚服务端，双模式切换 |
| ✅ 完成 | 数据库模型 | account / group / task |
| ✅ 完成 | 协议号导入 | 文件夹格式 → ZIP 上传 → 服务器解压导入 |
| ✅ 完成 | 账号状态验证 | 批量验证，正常/失效/封号/多地登录 |
| ✅ 完成 | 批量修改资料 | 改名字、简介、头像（已实测成功）|
| ✅ 完成 | 定时任务引擎 | APScheduler + SQLite 持久化，重启不丢失 |
| ✅ 完成 | 消息发送 | 定时发送，已验证消息正常到达群组 |
| ✅ 完成 | 清理失效账号 | 一键删除 invalid/banned，保留正常账号 |
| ✅ 完成 | FastAPI 服务端 | 全功能 REST API，含鉴权 |
| ✅ 完成 | HTTP 客户端 | api_client.py，SimpleNamespace 适配 GUI |
| ✅ 完成 | 双模式切换 | services/proxy.py，GUI 无感知切换 |
| ✅ 完成 | GUI 主窗口 | 状态栏实时显示服务器模式/活跃任务数 |
| ✅ 完成 | GUI 账号Tab | 导入、验证、改资料、清理失效 |
| ✅ 完成 | GUI 群组Tab | 添加群组、列表展示 |
| ✅ 完成 | GUI 任务Tab | 创建/编辑/删除定时任务，显示下次执行时间 |
| ✅ 完成 | 服务器部署 | Ubuntu venv + systemd 开机自启 |
| ✅ 完成 | 代码更新流程 | git push → git pull → systemctl restart |
| 📋 待开发 | 消息模板变量 | {name} {date} 等动态替换 |
| 📋 待开发 | 导入结果报告 | 导入后输出每个账号状态汇总 |
| 📋 待开发 | 账号代理设置 | 为单个账号配置独立代理 |
| 📋 待开发 | 人机验证引导 | 发言受限时弹窗引导用户手动完成验证 |

---

## 十二、接手注意事项

1. **session 文件是账号核心凭据**，服务器上的 `sessions/` 目录必须定期备份
2. **两套 .env**：本地用 `.env.client` 模板（填 SERVER_URL + API_KEY），服务器用 `.env.server` 模板（不填 SERVER_URL）
3. **Telethon 不是 Pyrogram**：两者 API 不同，不能混用。本项目全部使用 Telethon 1.36.0
4. **APScheduler args 不是 kwargs**：任务注册必须用 `args=(task_id,)`，不能用 `kwargs`（Python 3.13 bug）
5. **服务器无 GUI**：服务器只运行 `python main.py --no-gui --api`，不能导入任何 PyQt5 模块
6. **FloodWait 是正常现象**：Telegram 限速，程序已自动处理，不是 bug
7. **日志**：服务器日志在 `logs/qfxm.log`，也可用 `sudo journalctl -u qfxm -f` 实时查看
