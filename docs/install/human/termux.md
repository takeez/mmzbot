# Android Termux + proot Debian 部署

## 适用范围

本指南介绍在 Android Termux 中通过 proot-distro 运行 Debian，并由 Termux 脚本启动机魂小悦。无需 Android root 或 sudo。后台进程管理因设备厂商而异；如需稳定的 7×24 运行，建议选择 Linux 或 Docker。

## 准备条件

| 项目 | 要求 | 怎么确认 |
|---|---|---|
| 系统 | Android 7+，arm64 | Debian 内运行 `uname -m`，应为 `aarch64` |
| 内存 / 磁盘 | 建议 4 GB 内存起，至少 4 GB 空闲存储 | 系统设置 → 内存 / 存储 |
| 公网 IP | 不需要，本机面板用 `127.0.0.1` | — |
| 图形界面 | 手机本身用于安装与扫码；Debian 内本体不需要桌面 | — |
| 权限 | 不需要 root；Termux 内使用 proot-distro，不用 sudo | — |
| 端口 | 机魂小悦 `17383`；NapCat API `3000`；WebUI `6099` | 本机端口 |

从 [F-Droid 的 Termux 页面](https://f-droid.org/packages/com.termux/) 安装 Termux。不要装 Google Play 旧版。NapCat 和 QQ 会明显增加内存占用；如果手机资源紧张，先只跑本体，不要硬塞 QQ 通道。

## 准备工作

安装 Termux 后，第一步是在 Termux App 中运行下面的命令并授予存储权限；后续步骤要读取 `/sdcard/Download`：

```bash
termux-setup-storage
```

## 部署注意事项

- QQ 通道仍要官方 QQ 和 NapCat。Termux/proot 里可以用 Linux arm64 QQ + NapCat，不是直接把安卓 QQ 当作通道。NapCat 的 API token、上报 token 和 `bot.token` 必须相同。
- Debian、Python、proot-distro 等依赖用仓库当前稳定版。Termux 的 `pkg` 命令只在 Termux App 里运行；容器里的 Debian 命令都用 `proot-distro login debian -- ...` 包一层。这里没有 sudo。

## 部署步骤

### 1. 在 Termux 安装 proot-distro

打开 Termux：

```bash
pkg update -y
pkg install -y proot-distro curl
proot-distro list
```

**预期结果：** 可用发行版列表里有 `debian`。

**未通过时检查：** `pkg: command not found` 说明命令不在 Termux 里跑。下载失败先检查网络或 Termux 软件源。

### 2. 安装 Debian 并装 Python

```bash
proot-distro install debian
proot-distro login debian -- bash -lc 'cat /etc/debian_version && apt update && apt install -y python3 python3-venv curl ca-certificates unzip'
proot-distro login debian -- bash -lc 'python3 --version'
```

**预期结果：** Debian 版本号和 Python 3.11 或更高版本。Debian 12 自带 Python 3.11。

**未通过时检查：** `proot-distro list` 确认名称；确认网络正常。容器里不要输入 `sudo`，直接用 `apt`。

### 3. 放代码并准备数据目录

默认将仓库目录从手机存储复制到 Debian 的 `/root/mmzbot`；这条路径不需要 git。若选择在 Debian 容器内执行 `git clone`，需另行安装 git。检查：

```bash
proot-distro login debian -- bash -lc 'ls /root/mmzbot/phone-bot-v2.py /root/mmzbot/fg-bot-v2-start.sh /root/mmzbot/mmzbot-watchdog.sh'
```

**预期结果：** 三个文件都存在。

**未通过时检查：** 检查实际代码路径及准备阶段的存储授权；读取 `/sdcard` 时使用 `proot-distro login debian --bind /sdcard:/sdcard -- ...` 挂载。

### 4. 配本体并生成启动脚本

在 Termux 生成 token 并记下来：

```bash
TOKEN=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
printf '%s\n' "$TOKEN"
```

在 Debian 写本体配置。名称默认为 `机魂小悦`，可按需自定。`agent.name` 和 `agent.wakeWords` 中的词出现在消息开头时会唤醒机魂小悦；`agent.wakeWords` 可以留空。首次配置时请先查看 `personality.md`，确认是否需要修改；登录面板后可以继续调整。用真实 QQ 号、群号和模型密钥替换示例值；默认数据目录与代码目录一致：

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && MMZBOT_DATA=/root/mmzbot python3 phone-bot-v2.py --set bot.selfId=<真实QQ号> bot.groups=<真实群号> bot.token=<同一串token> agent.name=机魂小悦 agent.wakeWords=小悦 napcat.baseUrl=http://127.0.0.1:3000 llm.baseUrl=https://api.deepseek.com/v1 llm.model=deepseek-chat llm.apiKey=<真实模型密钥>'
```

先把上面命令里的 `<同一串token>` 换成刚生成的 token。`--set bot.token` 会同步写 `bot.token`、`bot.napcatToken` 和 `napcat.token`。

检查仓库的 `runinc.sh` 是否已经能从 Termux 调入 Debian。若没有，在 Termux 家目录创建：

```bash
cat > ~/runinc.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec proot-distro login debian -- bash -lc "$1"
EOF
chmod +x ~/runinc.sh
```

复制启动脚本和看门狗到 Termux 家目录：

```bash
ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/debian"
cp "$ROOTFS/root/mmzbot/fg-bot-v2-start.sh" ~/fg-bot-v2-start.sh
cp "$ROOTFS/root/mmzbot/mmzbot-watchdog.sh" ~/mmzbot-watchdog.sh
chmod +x ~/fg-bot-v2-start.sh ~/mmzbot-watchdog.sh
bash ~/runinc.sh 'python3 -c "print(1+1)"'
```

**预期结果：** 配置保存提示，随后烟雾测试打印 `2`。

**未通过时检查：** `$ROOTFS` 应是 proot-distro 安装的 rootfs。`runinc.sh` 要用实际安装的发行版名。如果代码或数据目录不是 `/root/mmzbot`，同步修改本节中的路径。

### 4.1 安装向量语义记忆依赖与模型（必需）

在 Debian 中创建虚拟环境、安装 `requirements.txt` 的依赖，并下载模型到数据目录：

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && MMZBOT_DATA=/root/mmzbot .venv/bin/python tools/fetch_model.py'
```

下载输出必须显示 3 个文件全部就位（约 24 MB）。模型来自 GitHub Release，不在 Git 仓库内；失败可用 `tools/fetch_model.py --base <镜像根地址>` 重试。缺少依赖或模型即表示安装未完成：程序可能启动，但记忆检索不可用并会退回全量记忆，增加 token 消耗。

依赖和模型就位后启动本体。启动后，在 QQ 中触发一次记忆查询或写入以加载模型，再检查：

```bash
proot-distro login debian -- bash -lc 'grep -F "语义召回：模型加载好了" /root/mmzbot/bot.log'
```

### 5. 启动本体

```bash
MMZBOT_DIR=/root/mmzbot MMZBOT_DATA=/root/mmzbot bash ~/fg-bot-v2-start.sh
```

在 Termux 新建一个会话验证：

```bash
curl -s http://127.0.0.1:17383/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17383/panel
```

**预期结果：** 根路径 `机魂小悦在跑。`，面板为 `200`。

**未通过时检查：** `tail -50 ~/mmzbot-stdout.log`。保持 Termux 常驻通知，不要清理 Termux 后台进程；在系统设置里关闭 Termux 的电池优化。

### 6. 安装 NapCat（可选，但 QQ 收发需要）

这一步要准备适用于 Linux arm64 的 QQ `.deb` 和 NapCat Linux zip，放进手机的 Download 目录。先在 Termux 授权存储，再让 proot 能访问它：

```bash
proot-distro login debian --bind /sdcard:/sdcard -- bash -lc 'uname -m && apt install -y /sdcard/Download/linuxqq_*.deb && ls -l /opt/QQ/qq'
```

**预期结果：** `aarch64` 和 `/opt/QQ/qq` 文件。

**未通过时检查：** 确认下载的是 arm64 `.deb`。Ubuntu 24.04 / Debian 13 使用的音频库名为 `libasound2t64`，Debian 12 的包名仍为 `libasound2`；不要在 Debian 12 强装不存在的 `libasound2t64`。

NapCat Shell zip 里没有 Linux 启动器。不能解压后直接运行 `xvfb-run /opt/QQ/qq`，那只会起没有注入 NapCat 的裸 QQ。按下面方式安装注入入口：

```bash
proot-distro login debian --bind /sdcard:/sdcard -- bash -lc '
  apt install -y xvfb libgbm1 libasound2 libnss3 libxss1 libxtst6 fonts-noto-cjk
  mkdir -p /opt/QQ/resources/app/napcat
  unzip -o /sdcard/Download/NapCat*.zip -d /opt/QQ/resources/app/napcat
  cat > /opt/QQ/resources/app/loadNapCat.cjs <<"EOF"
const path = require("path");
(async () => { await import("file://" + path.join(__dirname, "./napcat/napcat.mjs")); })();
EOF
  sed -i "s#\"main\": \".*index.js\"#\"main\": \"./loadNapCat.cjs\"#" /opt/QQ/resources/app/package.json
  grep -n "\"main\"" /opt/QQ/resources/app/package.json
'
```

**预期结果：** `main` 字段指向 `./loadNapCat.cjs`。然后在另一个 Termux 会话启动：

```bash
proot-distro login debian -- bash -lc 'xvfb-run -a -s "-screen 0 1080x720x24" /opt/QQ/qq --no-sandbox'
```

**预期结果：** NapCat 服务启动。浏览器通过 `http://<手机IP>:6099/webui` 打开 WebUI；若要求 token，从 NapCat 日志获取。登录后添加 HTTP 服务器 `3000` 和上报 `http://127.0.0.1:17383/`，两项 token 与本体一致，再扫码。实时二维码约两分钟一换。

**未通过时检查：** 检查 NapCat zip 解压路径、`package.json` 的 `main` 字段和 Xvfb 输出。NapCat 重启会掉登录，网络配置先写好再扫码。

## 修改配置

第 4 步已写入基本配置。之后可在面板或通过 `--set` 修改；Termux 与 Debian 侧命令必须使用同一数据目录（本篇为 `/root/mmzbot`）。`--list-models` 会列出每个模型支持的思考强度：

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && python3 phone-bot-v2.py --list-models <地址> <密钥>'
```

### 设置思考强度

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && MMZBOT_DATA=/root/mmzbot python3 phone-bot-v2.py --set llm.effort=low'
```

可选值为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。强度变更在后续请求生效。

### 处理端口冲突

如果 `17383` 已被占用，可改为 `17390`：

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && MMZBOT_DATA=/root/mmzbot python3 phone-bot-v2.py --set port=17390'
```

停止当前本体进程（如使用看门狗，先停止看门狗），再运行 `MMZBOT_DIR=/root/mmzbot MMZBOT_DATA=/root/mmzbot bash ~/fg-bot-v2-start.sh`。同时将 NapCat 上报地址改为 `http://127.0.0.1:17390/`，保存并重启 NapCat；面板地址改为 `http://<手机IP>:17390/panel`。后续验收命令中的 `17383` 也应替换为 `17390`。

### 允许局域网访问面板

如果同一局域网中的其他设备打开面板返回 `403`，将示例网段替换成自己的局域网 CIDR：

```bash
proot-distro login debian -- bash -lc 'cd /root/mmzbot && MMZBOT_DATA=/root/mmzbot python3 phone-bot-v2.py --set bot.control.allowIps=192.168.1.0/24'
```

该设置仅适用于可信局域网；不要使用 `0.0.0.0/0`。公网访问应使用带登录保护的反向代理，见[反向代理说明](../../reverse-proxy.md)。

本体需要 QQ 号、共享 token、群号、模型与 API Key，以及人设正文。`--set` 配置通常热加载；修改本体 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能使 QQ 掉线，网络配置应先完成再扫码。

## 启动并验证

以下示例使用默认代码和数据目录；若前文调整过路径，请同步替换这两个值。此处只运行自检和连通性检查，不要再次启动本体。

```bash
MMZBOT_DIR=/root/mmzbot
MMZBOT_DATA=/root/mmzbot
proot-distro login debian -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --check"
printf 'exit=%s\n' "$?"
curl -sL -H "Authorization: Bearer <同一串token>" http://127.0.0.1:3000/get_login_info
curl -s http://127.0.0.1:17383/
```

**预期结果：** `--check` 六项全 ✓、退出码 `0`；NapCat 返回 `retcode:0`。再打开手机浏览器的 `http://127.0.0.1:17383/panel`，最后到目标群发一句，确认机魂小悦能回复。

`--check` 前五项只验有没有填，第六项才会实际探测 NapCat。退出码 `0` 是通过，`1` 是还缺配置或 NapCat 不通，`2` 是参数错误。

## 出问题时

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `proot-distro: command not found` | Termux 没装 proot-distro | `pkg install -y proot-distro` |
| 容器里找不到 Python | Python 装在 Termux 侧，不在 Debian | 用 `proot-distro login debian -- ...` 在容器里安装 Python |
| 启动脚本找不到代码目录 | `MMZBOT_DIR` 与容器路径不一致 | 启动时明确传 `MMZBOT_DIR=/实际路径` 和 `MMZBOT_DATA=/实际数据路径` |
| 手机后台一会儿就停 | Android 厂商省电策略杀掉 Termux | 关闭电池优化，保留 Termux 通知；需要时用 Termux:Boot |
| NapCat 有端口但 `--check` reset | NapCat WebUI 没启用 HTTP 服务器 | 在 WebUI 网络配置中添加端口 3000 的 HTTP 服务器 |
| NapCat QQ 起不来 | 版本不匹配、注入入口错误或依赖库缺失 | 检查 QQ / NapCat 对应版本，确认 `main` 指向 `loadNapCat.cjs`，按 Debian 版本安装音频库 |
| 群文件下载失败 | QQ build 超过 `packetBackend` 支持范围 | 该功能最高支持 QQ build `36580`；升级 NapCat 不会扩展支持范围 |
| `--selftest` 读了实际配置 | 设置了指向实际数据目录的 `MMZBOT_DATA` | 运行 1155 条自检时不要指向真实数据目录 |

## 怎么卸掉 / 回滚

先停看门狗和本体，再备份容器里的代码与数据：

```bash
pkill -f mmzbot-watchdog.sh || true
proot-distro login debian -- bash -lc 'pkill -f phone-bot-v2.py || true'
ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/debian"
tar czf ~/mmzbot-backup.tar.gz -C "$ROOTFS/root" mmzbot
```

确认备份后，再删除容器内目录和 Termux 启动脚本。移除整个 Debian 会一并删除 QQ、NapCat、本体和其他容器数据，先确认备份再操作。

回滚本体时换回 `/root/mmzbot` 中的旧代码，保留数据目录。Termux:Boot 若已配置，也要移除对应启动项。
