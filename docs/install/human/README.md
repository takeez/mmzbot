# 部署机魂小悦（MMZBOT）：选择运行环境

机魂小悦提供面板、配置和 Agent 对话逻辑。要通过 QQ 收发消息，还需要可登录的 QQ 账号和 NapCat；本项目不实现 QQ 协议。

## 环境选择

| 环境 | 适用场景 | 运行方式 | 指南 |
|---|---|---|---|
| Linux 原生 | Ubuntu / Debian 服务器，需要 systemd 管理服务 | 本体使用 systemd；NapCat 可运行在 Docker | [Linux](linux.md) |
| Windows 10/11 | 常开 Windows 电脑 | `mmzbot.ps1`，可配置开机任务；Windows QQ + NapCat | [Windows](windows.md) |
| Docker Compose | 使用 Docker 管理本体和 NapCat | Compose 管理两个容器，也支持混合部署 | [Docker](docker.md) |
| Android Termux | 闲置安卓设备，可接受手机常驻运行 | Termux + proot Debian | [Termux](termux.md) |

## 共同准备与安全

- 准备能登录目标群的 QQ 账号，以及模型服务地址、模型名和有效 API Key。`sk-PLACEHOLDER…` 等占位值不能用于部署。
- 网页搜索 API Key 为可选配置：推荐使用百度千帆搜索；未配置时会回退到必应 RSS，搜索能力可能有所下降。具体设置命令见所选环境指南中的可选配置步骤。
- 按所选环境准备 Python 3.11+、Docker 或 Termux；各指南列有具体要求。
- 向量语义记忆是必需组件：需安装 `requirements.txt` 中的三个 Python 包，并下载 GitHub Release 模型文件。模型缺失或依赖安装失败时，程序可能启动，但记忆检索不可用，安装未完成。
- 默认端口：机魂小悦服务 `17383`、NapCat API `3000`、NapCat WebUI `6099`。不要将 `3000` 或 `6099` 暴露到公网。
- 数据目录优先级：`MMZBOT_DATA` 环境变量 > `local-config.json` 中的 `dataDir` > 平台默认目录。启动、配置和检查时确认使用同一数据目录。
- `--set` 与面板修改的配置通常热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能使 QQ 掉线；先完成网络配置，再扫码。

## 启动与验收

入口为 `python3 phone-bot-v2.py`（Windows 使用 `python`）；不带参数会启动服务。部署完成后运行 `--check`：前五项只检查配置是否填写，第六项实际探测 NapCat。退出码 `0` 表示通过，`1` 表示配置缺项或 NapCat 不通，`2` 表示参数错误。常见占位值 `10000`、`1234567890`、`987654321`、`sk-PLACEHOLDER…` 会判定为未配置。

完整验收还需确认 NapCat 登录信息可查询，并在目标群发送消息确认机魂小悦能回复；只看到进程或面板不代表 QQ 通道已跑通。

## 已知限制

- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；用 `curl` 检查时加 `-L`。二维码约两分钟刷新一次，请使用实时二维码。
- `packetBackend` 支持范围最高到 QQ build `36580`；超出后群文件下载不可用，升级 NapCat 不能绕过该限制。
- `--selftest` 包含 1155 条断言。不要让 `MMZBOT_DATA` 指向真实数据目录运行自检。
- 混合部署（Linux 本体原生运行、NapCat 使用 Docker）需设置 `bot.control.allowIps=172.17.0.0/16`，并将 NapCat 上报地址设为 `http://172.17.0.1:17383/`。详见 [Docker 部署指南](docker.md)。

选择上表中与你的设备相符的指南，按步骤完成安装、配置、启动、验收与排错。涉及扫码、管理员权限或重启设备时，请由设备使用者操作。
