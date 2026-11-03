# Agent 安装入口

| 环境 | 文档 | 前置 | 权限 |
|---|---|---|---|
| Linux 原生 + systemd | [linux.md](linux.md) | Ubuntu 24.04.5 / Debian 12+；Python 3.11+；Docker 用于 NapCat | sudo |
| Windows 10/11 | [windows.md](windows.md) | Python 3.11+；Windows QQ；NapCat Windows 包 | 普通用户运行；管理员注册任务 |
| Docker / compose | [docker.md](docker.md) | Linux Docker Engine + Compose v2；代码仓库在本机 | Docker daemon 或 sudo |
| Android Termux + proot Debian | [termux.md](termux.md) | Termux、arm64、proot-distro；容器内 Python 3.11+ | 无 sudo / 无 root |

## 先跑这个

先选定上表中的一个环境。不要把不同文档的路径混着用。

**Linux**（在仓库根目录）：

```bash
python3 --version
# 期望：Python 3.11 或更高
# 失败：检查 PATH 和发行版 Python 包；低于 3.11 时先升级解释器
```

**Windows**（PowerShell）：

```powershell
python --version
# 期望：Python 3.11 或更高
# 失败：安装时勾选 Add python.exe to PATH，然后重开 PowerShell
```

**Docker**：

```bash
docker compose version
# 期望：Docker Compose v2 版本号
# 失败：安装 Docker Engine 与 Compose 插件，或检查 Docker daemon 权限
```

**Termux**：

```bash
proot-distro list
# 期望：可用发行版中有 debian
# 失败：在 Termux 中运行 pkg install -y proot-distro 后重试
```

## 执行约定

- 选择一种运行环境，按对应文档顺序执行；不要混用路径，也不要跳过成功判据。
- 首次向用户收集配置前，读取代码目录中的 `personality.md`，将全文展示给用户并询问是否想调整。不要擅自改人格文件；用户登录面板后可以自行编辑。
- 一次收集以下信息：名称（`agent.name`，默认 `机魂小悦`，可自定义）；唤醒词（`agent.wakeWords`，默认 `小悦`，可提供多个或留空）。名称或唤醒词出现在消息开头时会唤醒机魂小悦回复。再收集真实 QQ 号、目标群号、模型 API Key，并在取得 Key 后用 `--list-models` 查询模型及其支持的思考强度，再请用户选择。配置前将用户选定的名称和唤醒词填入 `BOTNAME`、`WAKEWORDS`；没有额外唤醒词时令 `WAKEWORDS=''`。不要猜测配置值或使用占位值。
- Windows 部署还需用户先登录 Windows QQ。扫码是另一处需要用户配合的步骤：Agent 先配置 NapCat 网络、重启 NapCat并获取实时二维码，再交给用户扫描。
- 默认端口：机魂小悦服务 `17383`、NapCat API `3000`、NapCat WebUI `6099`。不要将 `3000` 或 `6099` 暴露到公网。
- 网页搜索 API Key 为可选项：在对应安装指南的本体配置步骤后，可用 `python3 phone-bot-v2.py --set search.apiKey=<搜索服务API密钥>` 配置（Windows 使用 `python`；Docker、Termux 请使用各自指南中的命令）。推荐百度千帆搜索；未配置时回退到必应 RSS，搜索能力可能有所下降。
- 入口为 `python3 phone-bot-v2.py`（Windows 使用 `python`）；不带参数时启动服务。
- `--check` 共六项：前五项检查是否填写，第六项探测 NapCat（未登录时也会失败）。退出码 `0` 表示通过、`1` 表示配置缺失或探测失败、`2` 表示参数错误。`10000`、`1234567890`、`987654321`、`sk-PLACEHOLDER…` 等占位值不通过。
- 向量语义记忆是必需组件：必须安装 `requirements.txt` 中的依赖并下载 GitHub Release 模型。依赖或模型缺失时程序可能启动，但记忆检索不可用，安装不能验收通过。模型在首次记忆查询或写入时加载；之后应确认日志出现 `语义召回：模型加载好了`。
- 数据目录优先级：`MMZBOT_DATA` > `local-config.json` 中的 `dataDir` > 平台默认目录。`--set` 配置热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能使 QQ 掉线。
- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；使用 `curl` 检查时加 `-L`。二维码约两分钟刷新一次。
- Linux 本体原生运行、NapCat 使用 Docker 的混合部署需设置 `bot.control.allowIps=172.17.0.0/16`，上报地址使用 `http://172.17.0.1:17383/`。
- `packetBackend` 最高支持 QQ build `36580`；超出后群文件下载不可用。`--selftest` 有 1155 条断言；不要让 `MMZBOT_DATA` 指向真实数据目录。
- 服务启动、NapCat 登录和目标群回复验收通过后，使用可用的浏览器工具打开面板地址；登录页出现时，将共享令牌 `TOKEN` 粘贴到口令框。若当前 Agent 无法操作浏览器，私下把面板地址和令牌交给用户并引导其登录；不要在群聊中发送令牌。告知用户面板还有更多设置，名称、唤醒词和其他配置后续都可修改。
