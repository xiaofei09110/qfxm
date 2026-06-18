# QFXM — Telegram 多账号群控系统 开发文档

> 本文档是项目唯一的权威说明。任何接手此项目的开发者（包括 AI）都应先读完本文档再动手写代码。

---

## 一、项目目标

构建一个 **Telegram 多账号批量管理工具**，核心能力：

| 功能 | 说明 |
|------|------|
| 批量导入 session 文件 | 支持 Pyrogram / Telethon 两种 .session 格式，自动识别 |
| 批量验证账号状态 | 检测账号是否存活、是否被封、是否受限 |
| 批量修改账号资料 | 批量改头像、名称（first/last name）、个人简介 |
| 每群定时消息任务 | 为指定账号设置"在哪个群、几点发、发什么"的定时任务 |
| 人机验证引导 | 当账号在群内无法发言时，引导用户完成验证 |
| 任务持久化 | 程序重启后定时任务不丢失 |

---

## 二、技术栈

| 层 | 技术 | 原因 |
|----|------|------|
| Telegram 客户端 | **Pyrogram** | 对协议号 session 格式兼容性更好，中文生态主流 |
| 定时任务 | **APScheduler** + SQLAlchemyJobStore | 任务持久化到 SQLite，重启不丢失 |
| 数据库 | **SQLite** (SQLModel/SQLAlchemy) | 无需安装，本地零配置，可后期换 PostgreSQL |
| GUI | **PyQt5** | 桌面原生应用，稳定，无需浏览器 |
| 图片处理 | Pillow | 处理头像上传 |
| 配置 | python-dotenv + .env | API 凭据不进代码 |

---

## 三、项目目录结构

```
qfxm/
├── DEVELOPMENT.md          ← 本文件，开发全局说明
├── README.md               ← 快速启动说明
├── requirements.txt        ← Python 依赖
├── .env.example            ← 环境变量模板
├── main.py                 ← 程序唯一入口
├── config.py               ← 全局配置读取
├── database.py             ← 数据库初始化 & 表创建
│
├── models/                 ← 数据模型 (SQLModel)
│   ├── __init__.py
│   ├── account.py          ← 账号表：session路径、状态、代理等
│   ├── group.py            ← 群组表：群ID、别名、关联账号
│   └── task.py             ← 任务表：定时消息任务记录
│
├── core/                   ← 核心技术模块（不含业务逻辑）
│   ├── __init__.py
│   ├── session_importer.py ← session文件格式识别与导入 ★
│   ├── client_manager.py   ← Pyrogram客户端池，管理多账号连接 ★
│   ├── scheduler.py        ← APScheduler封装，持久化任务引擎 ★
│   └── profile_manager.py  ← 批量修改头像/名称/简介
│
├── services/               ← 业务逻辑层
│   ├── __init__.py
│   ├── account_service.py  ← 导入、验证、状态管理
│   ├── message_service.py  ← 消息发送、错误重试
│   └── group_service.py    ← 群组管理、入群检测
│
├── gui/                    ← PyQt5 界面
│   ├── __init__.py
│   ├── main_window.py      ← 主窗口，包含所有Tab
│   ├── tabs/
│   │   ├── account_tab.py  ← 账号管理界面
│   │   ├── group_tab.py    ← 群组管理界面
│   │   └── task_tab.py     ← 定时任务界面
│   └── dialogs/
│       ├── import_dialog.py    ← 批量导入 session 对话框
│       ├── task_dialog.py      ← 新建/编辑定时任务对话框
│       └── verify_dialog.py    ← 人机验证引导对话框
│
└── sessions/               ← session 文件存放目录（不进 git）
```

---

## 四、协议号文件格式（重要）

每个协议号是一个**以手机号命名的文件夹**，结构如下：
```
D:\桌面\协议号\
└── 916299146095\               ← 文件夹名 = 手机号
    ├── 916299146095.session    ← Pyrogram session 文件（核心）
    ├── 916299146095.json       ← 账号元数据（app_id/hash、2FA、设备信息等）
    ├── 2fa.txt                 ← 2FA 密码（备用，JSON 里也有）
    └── tdata\                  ← TDesktop 数据（暂不使用）
```

**JSON 关键字段：**
- `app_id` / `app_hash`：该账号专用的 API 凭据（不用 .env 里的全局凭据）
- `twoFA`：2FA 密码
- `device`、`app_version`：设备信息（连接时伪装，不能乱改）
- `spamblock`：是否被 Telegram 标记为 spam

**导入逻辑（`core/session_importer.py`）：**
1. 选择父文件夹 `D:\桌面\协议号\`
2. 扫描所有纯数字命名的子文件夹
3. 读取各自的 JSON 和 .session 文件
4. 将 .session 文件复制到 `sessions/` 统一管理
5. 写入数据库

---

## 五、数据库表设计

### accounts 表
```sql
id              INTEGER PRIMARY KEY
name            TEXT                    -- 账号备注名
phone           TEXT UNIQUE             -- 手机号
session_path    TEXT UNIQUE             -- session文件绝对路径（已复制到sessions/）
session_type    TEXT DEFAULT 'pyrogram'
app_id          INTEGER DEFAULT 2040    -- 来自JSON，每账号独立
app_hash        TEXT                    -- 来自JSON，每账号独立
two_fa          TEXT                    -- 2FA密码（来自JSON/2fa.txt）
device_model    TEXT                    -- 设备型号（连接时用）
app_version     TEXT                    -- 客户端版本（连接时用）
first_name      TEXT
last_name       TEXT
user_id         INTEGER
is_premium      BOOLEAN
spamblock       TEXT                    -- NULL=正常，有值=被标记
status          TEXT DEFAULT 'unknown'  -- unknown/active/restricted/banned/flood/invalid
last_checked    DATETIME
error_msg       TEXT
proxy_type      TEXT
proxy_host      TEXT
proxy_port      INTEGER
proxy_user      TEXT
proxy_pass      TEXT
created_at      DATETIME
```

### groups 表
```sql
id              INTEGER PRIMARY KEY
tg_id           TEXT UNIQUE             -- Telegram 群组 ID（字符串形式）
username        TEXT                    -- 群组 username（@xxx）
title           TEXT                    -- 群组标题
account_id      INTEGER FK→accounts     -- 用于进入该群的账号
joined_at       DATETIME
can_send        BOOLEAN DEFAULT TRUE    -- 是否能发言
needs_verify    BOOLEAN DEFAULT FALSE   -- 是否需要人机验证
```

### tasks 表
```sql
id              INTEGER PRIMARY KEY
name            TEXT                    -- 任务备注名
account_id      INTEGER FK→accounts
group_id        INTEGER FK→groups
message_text    TEXT                    -- 消息内容（支持\n换行）
media_path      TEXT                    -- 可选，本地图片/文件路径
cron_expr       TEXT                    -- cron表达式，如 "0 9 * * *"
timezone        TEXT DEFAULT 'Asia/Shanghai'
is_active       BOOLEAN DEFAULT TRUE
last_run        DATETIME
next_run        DATETIME
run_count       INTEGER DEFAULT 0
fail_count      INTEGER DEFAULT 0
created_at      DATETIME
```

---

## 五、核心难点与解决方案

### 难点1：账号入群无法发言 / 人机验证

**原因：**
- 账号是新号或协议号，Telegram 检测到异常行为，限制在群内发言
- 部分群组开启了"新成员验证机器人"（如 @GroupHelpBot、@Combot）
- 账号处于 SpamBan 状态（@SpamBot 可查）

**检测方法（`message_service.py`）：**
```python
from pyrogram.errors import (
    ChatWriteForbidden,   # 群限制发言
    SlowModeWait,         # 慢速模式，等待 x 秒
    UserBannedInChannel,  # 账号在此群被封
    FloodWait,            # 请求过频，等待 x 秒
)
```

**处理流程：**
1. 捕获 `ChatWriteForbidden` → 将 `groups.needs_verify = True` → GUI 弹出引导对话框
2. 引导对话框说明：让用户用手机打开 Telegram，找到该账号，手动在群内完成验证
3. 捕获 `FloodWait(x)` → 自动等待 x 秒后重试（不中断任务）
4. 捕获 `SlowModeWait(x)` → 记录到任务日志，下次按慢速间隔发送

### 难点2：任务缓存丢失（程序重启后定时任务消失）

**方案：APScheduler + SQLAlchemyJobStore**

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///qfxm.db')
}
scheduler = BackgroundScheduler(jobstores=jobstores)
```

- 所有任务写入 SQLite，重启后自动恢复
- 任务 ID 格式：`task_{task_db_id}`，唯一标识，防止重复注册

**启动时任务恢复流程（`scheduler.py`）：**
1. 程序启动 → `scheduler.start()`
2. APScheduler 自动从 SQLite 加载全部 job
3. 遍历 `tasks` 表中 `is_active=True` 的任务，比对 scheduler 中是否存在
4. 不存在则重新注册，存在则跳过

### 难点3：定时消息发不出去

**常见原因排查表：**

| 症状 | 原因 | 解决 |
|------|------|------|
| 任务执行了但无消息 | 账号 session 已失效 | 重新验证账号状态 |
| 任务根本没执行 | Scheduler 未启动 / 时区错误 | 检查 `scheduler.running`；确认 timezone 设置 |
| 执行报 FloodWait | 发送频率过高 | 任务间加随机延迟 3-15 秒 |
| 执行报 ChatWriteForbidden | 账号被群限制 | 触发人机验证流程 |
| 程序关闭后任务不执行 | Scheduler 随程序退出 | 需要程序保持运行；或部署到服务器 |

**发送前置检查（`message_service.py`）：**
```python
async def safe_send(client, group_id, text):
    # 1. 检查客户端是否连接
    if not client.is_connected:
        await client.connect()
    # 2. 发送，捕获所有已知错误
    try:
        await client.send_message(group_id, text)
    except FloodWait as e:
        await asyncio.sleep(e.value + 5)
        await client.send_message(group_id, text)  # 重试一次
    except ChatWriteForbidden:
        # 触发验证流程
        raise NeedsVerificationError(group_id)
```

---

## 六、部署方案对比

| 方案 | 稳定性 | 复杂度 | 推荐场景 |
|------|--------|--------|----------|
| 本地 Windows 电脑运行 | 中（依赖电脑开机） | 低 | 开发测试、小规模使用 |
| **本地做成桌面 App（推荐）** | 中高 | 低 | 日常使用主方案 |
| 后端部署到 Linux 服务器 | 高（24h 不间断） | 中 | 需要全天候定时任务 |
| Docker 容器化部署 | 高 | 中 | 服务器上隔离运行 |

**当前实现：本地桌面 App（PyQt5）**
- 程序不关闭时，定时任务正常运行
- 如需 24h 运行，将程序部署到 VPS（Linux 服务器）并用 `screen` 或 `systemd` 保活

### 服务器部署步骤（Linux VPS）
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 无界面运行（服务器无GUI）需切换到 CLI 模式
# main.py 加参数 --no-gui 时跳过 PyQt5

# 3. 用 screen 保持后台运行
screen -S qfxm
python main.py --no-gui
# Ctrl+A D 退出 screen，进程继续运行

# 4. 或用 systemd 注册系统服务（开机自启）
```

### 服务器问题排查
- 日志文件：`logs/qfxm.log`，所有错误都写入此文件
- 账号状态异常：检查 `accounts` 表的 `status` 和 `error_msg` 字段
- 任务没执行：检查 `apscheduler_jobs` 表中 `next_run_time` 字段
- 网络问题：确认服务器 IP 能访问 Telegram（需代理或在非封锁地区）

---

## 七、开发进度

| 状态 | 模块 | 说明 |
|------|------|------|
| ✅ 完成 | 项目架构 & 文档 | 本文件 |
| ✅ 完成 | 数据库模型 | account / group / task |
| ✅ 完成 | session 导入器 | 自动识别 Pyrogram/Telethon 格式 |
| ✅ 完成 | 客户端管理器 | 多账号 Pyrogram 客户端池 |
| ✅ 完成 | 定时任务引擎 | APScheduler + SQLite 持久化 |
| ✅ 完成 | 资料修改器 | 批量改头像/名称/简介 |
| ✅ 完成 | 账号服务 | 批量导入、验证状态 |
| ✅ 完成 | 消息服务 | 安全发送、错误处理 |
| ✅ 完成 | GUI 主窗口 | PyQt5 多Tab界面 |
| 🚧 待完善 | GUI 各 Tab | 账号/群组/任务管理界面细节 |
| 🚧 待完善 | 人机验证引导 | 弹窗引导用户手动完成验证 |
| 📋 计划中 | 服务器无头模式 | --no-gui CLI 运行支持 |
| 📋 计划中 | 消息模板变量 | {name} {date} 等动态替换 |
| 📋 计划中 | 导入结果报告 | 导入后输出每个账号状态汇总 |

---

## 八、关键配置项 (.env)

```env
# Telegram API 凭据（从 my.telegram.org 获取）
API_ID=你的API_ID
API_HASH=你的API_HASH

# 数据库路径
DB_PATH=qfxm.db

# 日志级别
LOG_LEVEL=INFO

# 发送消息随机延迟范围（秒）
SEND_DELAY_MIN=3
SEND_DELAY_MAX=15
```

---

## 九、接手注意事项

1. **session 文件是账号的核心凭据**，丢失即丢失账号访问权，必须备份
2. **API_ID 和 API_HASH** 是程序运行必须的，从 my.telegram.org 申请
3. **协议号**指用第三方客户端（如安卓协议）登录的账号，其 session 格式与 Telethon 不同，本项目主用 Pyrogram 格式
4. **FloodWait 是正常现象**，不是 bug，Telegram 的限速机制，程序已自动处理
5. 修改账号资料（头像/名称）频率不宜过高，建议每次操作后等待 10-30 秒
6. 定时任务依赖程序保持运行，如需 24h 执行，部署到服务器
