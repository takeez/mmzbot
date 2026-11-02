# 项目目标与验收规范

> 本文件用于开发和验收，不是用户安装指南。项目目标与验收条件以此为准；“当前差距”一节记录的是标注日期时的实现状态。

## 0. 一句话

**机魂小悦是一个能被 AI Agent 按文档安装配置的 QQ Agent；普通用户也能照着指南完成部署。**
装在哪都行：安卓手机、云服务器、废旧主机、Windows 电脑。

## 1. 运行环境（四条都要能跑）

| 环境 | 安装 | 启动 | 数据目录 |
|---|---|---|---|
| 手机 Termux + proot Debian | 脚本（已有） | Termux 启动脚本 + 看门狗 | proot 内 `~/mmzbot` |
| Linux 原生（云主机 / 废旧主机） | 脚本 / `docker` | systemd unit | `~/mmzbot`（可配） |
| Windows 原生 | 脚本（`.ps1`） | 任务计划 或 nssm | `%LOCALAPPDATA%\MMZBOT`（可配） |
| Docker（任意 Linux） | `docker compose up -d` | 容器 entrypoint | 挂载卷 |

硬性要求：

- **不许写死任何平台路径**（现在 `deploy.py` 里写死 Termux 路径 ✗ 必须改成可配）。
- **不许假设"有一台 PC 通过 SSH 推代码到手机"**（这是现在的做法 ✗ 云主机上没有这种结构）。
- Windows 上时间必须正确（`base.py` 目前用 IANA 时区，Windows 下 `datetime.now()` 会静默变 UTC ✗ 必须先修）。
- 运行时必须安装 `requirements.txt` 中的 `onnxruntime`、`tokenizers`、`numpy`，并下载 BGE-small-zh-v1.5 int8 语义记忆模型。缺少任一项时程序可以启动，但语义记忆检索不可用，安装验收不通过。

## 2. 网络（三种都要成立）

| 场景 | 面板怎么访问 |
|---|---|
| 同一局域网（家里、手机） | `http://<IP>:17383/panel`，可免登录 |
| 公网云主机 | 面板必须**登录**才能用（不能裸奔 ✗），绑定地址可配 |
| 反代后面（nginx / caddy + HTTPS） | 反代转发到本地端口；README 给一段可复制的配置 |

硬性要求：

- 监听地址可配（默认 `0.0.0.0`，不要写死 `127.0.0.1`）。
- 远程（非本机/局域网）访问面板 = **必须凭据**；凭据缺失时给出明确提示，不是白屏。
- 不做自己的 TLS（交给反代 ✓）。
- 公网能不能调 `/api` 由配置开关控制，默认关。

## 3. 两条使用路径

### 3.1 agent 部署（一键、可脚本化）

目标：**agent 不需要点 GUI、不需要手改文件**就能把机器人配到"能跑"。

必须提供：

```
python phone-bot-v2.py --set key=value [key=value …]     # 写 local-config.json，可重复执行（幂等）
python phone-bot-v2.py --check                           # 输出"能不能跑"的检查表，退出码 = 0/1
python phone-bot-v2.py --init-config                     # 用模板初始化（幂等，不覆盖已有的值）
```

- `--set` 与面板走**同一份** `local-config.json`、**同一套**校验（⛔ 不许两套实现）。
- 键名 = 配置文件里的点分路径（`bot.selfId`、`llm.model`…），与面板字段一一对应。
- `--check` 的每一项与面板「能不能跑」那张表**同源**。
- 任何一步失败要返回**非 0 退出码 + 一句人话**（agent 靠它判断成功与否）。

**验收**：一条命令序列装完，`--check` 退出码 0，机器人能在群里回一句话。

### 3.2 普通人部署（照文档）

```
· README 三条命令起步：装依赖 → 填配置 → 启动
· 首次打开面板自动跳到「初始化」页，六块都 ✓ 之后才提示"可以跑了"
· 所有能改的东西都在面板里，⛔ 不需要用户去翻文件 ✗
```

**验收**：一个没看过代码的人，照 README 从零到她在群里回一句话，不需要编辑除配置文件以外的任何文件。

## 4. 配置模型（单一真源）

```
config.json          出厂模板（进仓库，值都是占位）
local-config.json    用户覆盖（不进仓库，面板 / --set 都写这里）
```

- 合并必须是**深合并**（面板改一个键不许把兄弟键冲掉 ✗）。
- 仓库里不许出现任何真实 token / 密钥 / QQ 号 / 群号 / 内网地址 / 个人名字 ✓
- 面板 / `--set` / 环境变量（可选）三者优先级写清楚，且在文档里说明。

## 5. 明确不做（non-goals）

```
· 不做多租户 / SaaS（一份代码服务一个机器人）
· 不做自己的 TLS、不做自己的用户系统（靠反代 + 一把 token）
· 不做 Web 端改代码 / 自我修改
· 不做移动端 App（面板是网页，手机浏览器能用就够）
```

## 6. 当前差距

> ✅ = 已按本文件的验收口径做完并自检；「在做」= 有人正在改，别抢。

| # | 差距 | 状态 |
|---|---|---|
| 1 | 设置页（面板八块 + 检查表） | ✅（面板与 `--set` 共用 `onboard.py`，自检 6.14 一整节） |
| 2 | `--set` / `--check` 无头配置 | ✅（和面板同一套校验；自检里钉着命令行这条路） |
| 3 | 数据目录 / 监听地址可配，去掉写死路径 | ✅（`MMZBOT_DATA` > `dataDir` > 平台默认；所有状态文件从数据目录派生，自检里用临时目录验过） |
| 4 | Windows 时区坑 | ✅（不再依赖 `tzdata` / `zoneinfo`：`time.localtime` + `time.timezone`/`altzone` 自己算；自检断言 `now` 和 `time.localtime()` 一致） |
| 5 | systemd / Windows / Docker 三套启动 | ✅（`scripts/linux/mmzbot.service` + `scripts/windows/mmzbot.ps1` + `docker/Dockerfile`/`docker-compose.yml`；手机那条是 `fg-bot-v2-start.sh` + 可选看门狗） |
| 6 | 面板远程登录 + 反代文档 | ✅（公网 `/panel` → 登录页；`/login` 发 HttpOnly 会话 cookie，退出立刻失效；失败冷却；`panel.trustedProxies` 决定信不信 `X-Forwarded-For`；nginx / Caddy 照抄配置见 `docs/reverse-proxy.md`；自检 6.55b） |
| 7 | README 面向普通人重写 | ✅（「安装」四条并排：手机 / Linux / Windows / Docker，命令可照抄） |
| 8 | 公开版自检全绿 | ✅（1155 条，原来那 12 条改成夹具/读公开模板） |
| 9 | `deploy.py` 写死 Termux 路径 / `import phone` 崩溃 / `--help` 会真部署 | ✅（三目标 local/ssh/termux，路径/端口/重启方式全可配；`--dry` 不写文件，自检里钉着） |
| 10 | 扩展包系统（知识锁） | ✅（`fgbot/capabilities.py`：扫数据目录 + 仓库自带两处、六条校验安装/加载共用一份、按 mtime 重载；`skill` 工具读技能才解锁包的工具 schema，会话级最多 6 个包；`--install/--check/--list/--remove-capability`；面板「扩展」页（上传 zip / 从网址安装 / 停用 / 卸载 / 额外允许域名）；`pc_status` 是**示例包**（`examples/packages/pc-status`，装上去才用）；`pack-manager` 是仓库自带的 `package` 工具（装/卸/取文件，只有主人能用；文件入站走 `fgbot/files.py`）；自检 6.16 / 6.17 两节） |

**§1 硬性要求的落实位置**（验收时照着查）：

- 写死平台路径 → `fgbot/base.py` 的 `resolve_data_dir()`（`MMZBOT_DATA` / `dataDir` /
  平台默认 / 就地兼容）；`deploy.py` 的路径全部来自配置。
- 不假设「PC 用 SSH 推手机」→ `deploy.py --target local` 一条命令在本机完成。
- Windows 时间正确 → `base.local_now()` / `local_at()` / `local_stamp()`；`clock.py` 是薄壳。
- Python 依赖 → `requirements.txt` 列出向量语义记忆必需的 `onnxruntime`、`tokenizers`、`numpy`；模型资产从 GitHub Release 下载，不进入 Git 仓库。`deploy.py` 的 paramiko 仍为**可选**（未安装时使用系统 `ssh`）。

**§2 硬性要求的落实位置**：

- 监听地址可配 → `config.json` 的 `host`（默认 `0.0.0.0`）。
- 远程必须凭据 → `fgbot/server.py` 的 `/login` + `fgbot/websession.py`（cookie 会话）；
  没登录只给登录页；`panel.allowRemote` 关着时公网一律 403。
- 反代后面的来源判定 → `fgbot/proxy.py` + `panel.trustedProxies`（只信名单里的反代，
  `X-Forwarded-For` 从右往左取）。
- 可照抄的反代配置 → `docs/reverse-proxy.md`（nginx / Caddy）；README「公网访问」一节给最短版。
