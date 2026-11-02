# Linux 原生部署（systemd）

## 适用范围

本指南适用于 Ubuntu / Debian 服务器，以 systemd 管理机魂小悦，并通过 Docker 运行 NapCat。需要 sudo 权限；安卓设备请参阅 [Termux 部署指南](termux.md)。

## 准备条件

| 项目 | 要求 | 怎么确认 |
|---|---|---|
| 系统 | Ubuntu 24.04.5 LTS 或 Debian 12+，64 位 | `cat /etc/os-release`、`uname -m` |
| Python | 3.11+ | `python3 --version` |
| 内存 / 磁盘 | 2 GB 内存起；磁盘空闲 5 GB 起 | `free -h`、`df -h /` |
| 公网 IP | 不需要。只有外网要访问面板时才需要公网入口或内网穿透 | — |
| 图形界面 | 本方案不需要 | — |
| 权限 | 可用 sudo 的账号 | `sudo -v` |
| 端口 | 机魂小悦 `17383`；NapCat API `3000`；WebUI `6099` | `ss -ltnp` |

代码放在 `/opt/mmzbot`，数据放在 `/var/lib/mmzbot`，日志放在 `/var/log/mmzbot`。本指南通过发行版软件源安装 `docker.io`；如需使用 Docker 官方仓库的 Engine 版本，请按[官方安装说明](https://docs.docker.com/engine/install/)操作，不要重复安装。NapCat 镜像 `mlikiowa/napcat-docker:latest` 内含 QQ 和 NapCat。

## 部署注意事项

- QQ 通道由 Docker 中的 NapCat 和 QQ 提供；NapCat API token、上报 token 与 `bot.token` 必须相同。
- 本指南使用发行版提供的 Python 和 Docker 包。Ubuntu 24.04.5 实测 Python 3.12.3；系统库名称可能随版本变化，请以当前发行版仓库为准。

## 部署步骤

### 1. 安装系统依赖

```bash
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv curl rsync git
python3 --version
```

**预期结果：** Python 版本为 3.11 或更高。Ubuntu 24.04.5 的实测输出是 `Python 3.12.3`。

**未通过时检查：** `python3: command not found` 时检查发行版的软件源和安装输出。

### 2. 建服务用户和目录

```bash
sudo useradd -r -M -s /usr/sbin/nologin mmzbot
sudo mkdir -p /opt/mmzbot /var/lib/mmzbot /var/log/mmzbot
```

把仓库代码复制到 `/opt/mmzbot`。下面假设你已把仓库放在 `/path/to/MMZBOT/`：

```bash
sudo rsync -a --exclude=.git --exclude=__pycache__ /path/to/MMZBOT/ /opt/mmzbot/
sudo chown -R mmzbot:mmzbot /opt/mmzbot /var/lib/mmzbot /var/log/mmzbot
sudo chmod 755 /opt/mmzbot
ls /opt/mmzbot/phone-bot-v2.py /opt/mmzbot/mmzbot.service
```

**预期结果：** 两个文件路径都列出来，`id mmzbot` 能查到系统用户。

**未通过时检查：** 如果提示用户已存在，跳过 `useradd`。别用 `useradd -m`；它会把 `.bashrc`、`.profile`、`.bash_logout` 写进数据目录。若复制来的目录权限是 700，`chown` 后仍确认代码目录为 755，避免服务用户不能进入目录。

### 3. 写入本体配置

先生成一串随机 token，并记下来。它要同时填进面板、NapCat API 和 NapCat 上报配置。

```bash
TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
printf '%s\n' "$TOKEN"
```

名称默认为 `机魂小悦`，可按需自定。`agent.name` 和 `agent.wakeWords` 中的词出现在消息开头时会唤醒机魂小悦；`agent.wakeWords` 可以留空。首次配置时请先查看 `personality.md`，确认是否需要修改；登录面板后可以继续调整。用真实 QQ 号、群号和模型密钥替换尖括号中的值：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set \
  bot.selfId=<真实QQ号> \
  bot.groups=<真实群号> \
  bot.token="$TOKEN" \
  agent.name=机魂小悦 \
  agent.wakeWords=小悦 \
  napcat.baseUrl=http://127.0.0.1:3000 \
  llm.baseUrl=https://api.deepseek.com/v1 \
  llm.model=deepseek-chat \
  llm.apiKey=<真实模型密钥>
```

也可以先不写模型字段，稍后在面板配置。`--set bot.token` 会同步写 `bot.token`、`bot.napcatToken` 和 `napcat.token`。

**预期结果：** `✓ 已保存（N 项），下一条消息就按新值走`。

**未通过时检查：** 检查每个键名和值。`10000`、`1234567890`、`987654321` 和 `sk-PLACEHOLDER…` 都是占位值，不能留在最终配置中。

### 4. 安装并启动 systemd 服务

仓库单元默认使用 `/opt/mmzbot`、`/var/lib/mmzbot` 和 `mmzbot` 用户：

```bash
sudo cp /opt/mmzbot/mmzbot.service /etc/systemd/system/mmzbot.service
sudo chmod 644 /etc/systemd/system/mmzbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now mmzbot
systemctl is-active mmzbot
systemctl is-enabled mmzbot
```

**预期结果：** `active` 和 `enabled`。

**未通过时检查：** 运行 `sudo journalctl -u mmzbot -n 50 --no-pager`。先看第一条真正的错误；检查单元里的路径和目录属主。

### 5. 确认面板可访问

```bash
curl -s http://127.0.0.1:17383/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17383/panel
```

**预期结果：** 根路径返回 `机魂小悦在跑。`，面板返回 `200`。

**未通过时检查：** `systemctl is-active mmzbot` 和 `ss -ltnp | grep 17383`。局域网直接开 `http://<这台机器IP>:17383/panel`；公网才要 `panel.allowRemote=true`。

### 6. 用 Docker 启动 NapCat

```bash
sudo apt-get install -y docker.io
sudo systemctl enable --now docker
sudo docker run -d --name napcat --restart unless-stopped \
  -p 3000:3000 -p 6099:6099 \
  -e NAPCAT_UID=1000 -e NAPCAT_GID=1000 \
  -v napcat-config:/app/napcat/config \
  -v napcat-qq:/app/.config/QQ \
  mlikiowa/napcat-docker:latest
sudo docker ps --filter name=napcat
```

**预期结果：** `napcat` 状态为 `Up`，端口映射包含 `3000` 和 `6099`。这两个端口只给本机或管理网段用；云安全组不要向公网开放。远程 WebUI 用 SSH 转发或限制来源 IP。

**未通过时检查：** `sudo docker logs --tail=50 napcat`。若 Docker Hub 拉取失败，先处理 Docker 网络或镜像加速。

### 7. 先配置 NapCat 网络，再扫码

打开 `http://<服务器IP>:6099/webui`，按 NapCat 窗口或日志里显示的 WebUI token 登录。在网络配置里增加：

| 项目 | 值 |
|---|---|
| HTTP 服务器 | 启用，监听 `0.0.0.0:3000`，token 填 `$TOKEN` |
| HTTP 上报 / HTTP 客户端 | 启用，地址 `http://172.17.0.1:17383/`，token 填 `$TOKEN` |

混合部署时容器请求来自 `172.17.0.2`，本体要允许 Docker 网桥网段：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set bot.control.allowIps=172.17.0.0/16
```

先保存 NapCat 配置，再重启容器：

```bash
sudo docker restart napcat
sudo docker logs --tail=40 napcat
```

看到 WebUI token 和二维码生成日志后，浏览器打开 `http://<服务器IP>:6099/webui?token=<WebUI令牌>`，用 QQ 扫实时二维码。二维码约两分钟一换。NapCat 重启会掉 QQ 登录，所以这一步之后不要为普通配置改动重启。

**预期结果：** 日志显示二维码已生成；扫码后 `get_login_info` 返回 `retcode:0`。

**未通过时检查：** WebUI 页面和 `sudo docker logs napcat`。6099 首页会 `301` 到 `/webui`，`curl` 检查时加 `-L`。如果 `--check` 报连接重置，检查 NapCat 里是否真的启用了 HTTP 服务器。

## 修改配置

第 3 步已写入基本配置。之后可在面板或用 `--set` 修改；两者写入同一份本机配置。`--list-models` 会列出每个模型支持的思考强度：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --list-models <地址> <密钥>
```

必填项包括 QQ 号、共享 token、群号、模型与 API Key，以及人设正文。人设可在面板编辑，也可通过 `--persona-file` 指定。

### 设置思考强度

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set llm.effort=low
```

可选值为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。强度变更在后续请求生效。

### 处理端口冲突

如果 `17383` 已被占用，可改为 `17390` 并重启本体：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set port=17390
sudo systemctl restart mmzbot
```

同时将 NapCat 上报地址改为 `http://172.17.0.1:17390/`，访问面板时使用 `http://<服务器IP>:17390/panel`；后续端口检查命令中的 `17383` 也应改为 `17390`。

### 允许局域网访问面板

如果同一局域网中的其他设备打开面板返回 `403`，将示例网段替换成自己的局域网 CIDR：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set bot.control.allowIps=172.17.0.0/16,192.168.1.0/24
```

此设置只用于可信局域网，不要填写 `0.0.0.0/0`。公网访问应使用带登录保护的反向代理，见[反向代理说明](../../reverse-proxy.md)。配置通常热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能使 QQ 掉线，网络配置应先完成再扫码。

## 安装语义记忆依赖与模型（必需）

在服务运行用户的虚拟环境中安装三个 Python 依赖，再将三个模型文件下载到数据目录。模型从 GitHub Release 下载，不在 Git 仓库内；总量约 24 MB。

```bash
sudo -u mmzbot python3 -m venv /opt/mmzbot/.venv
sudo -u mmzbot /opt/mmzbot/.venv/bin/python -m pip install -r /opt/mmzbot/requirements.txt
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot /opt/mmzbot/.venv/bin/python /opt/mmzbot/tools/fetch_model.py
```

下载必须显示 3 个文件全部就位。若网络下载失败，可使用 `--base <镜像根地址>` 重试；依赖或模型未安装成功时，部署尚未完成。服务已运行时重启：

```bash
sudo systemctl restart mmzbot
```

模型在首次记忆查询或写入时加载。触发一次记忆操作后，检查日志是否出现 `语义召回：模型加载好了`：

```bash
grep -F '语义召回：模型加载好了' /var/lib/mmzbot/bot.log
```

没有依赖或模型时，机魂小悦仍可能启动，但记忆检索不可用并会退回全量记忆，增加 token 消耗；这不算完整安装。

## 启动并验证

```bash
systemctl is-active mmzbot
systemctl is-enabled mmzbot
ss -ltnp | grep 17383
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --check
printf 'exit=%s\n' "$?"
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
```

**预期结果：** 服务为 `active` / `enabled`，端口有 `LISTEN`，`--check` 六项全 ✓ 并退出 `0`，NapCat 返回 `retcode:0`。最后到目标群发一句消息，确认机魂小悦能回复。

`--check` 前五项只看有没有填，第六项才会问 NapCat。退出码 `1` 表示还有缺项或 NapCat 不通；`2` 表示参数错误。

## 出问题时

| 症状 | 原因 | 怎么办 |
|---|---|---|
| systemd 报 `status=203/EXEC` | Python 或脚本路径不对 | 用 `systemctl cat mmzbot` 核对 `ExecStart`，再查路径 |
| 写配置提示权限错误 | 数据目录不是 `mmzbot` 所有 | `sudo chown -R mmzbot:mmzbot /var/lib/mmzbot` |
| `--check` 显示 `[Errno 104] Connection reset by peer` | 两种：① 3000 映射存在但 NapCat 里没建 HTTP 服务器；② **还没扫码登录**（登录前 3000 不接请求） | 先看有没有扫码；再看 WebUI 建 HTTP 服务器，端口 3000、token 与本体一致 |
| NapCat 端口通但鉴权失败 | API 或上报 token 与 `bot.token` 不同 | 三处填同一个 token，再保存配置；NapCat 改动后重启会掉登录 |
| NapCat 容器上报收到 404 | Docker 来源 IP 不在允许列表 | 本体设 `bot.control.allowIps=172.17.0.0/16` |
| 群里消息不进本体 | 上报地址写成容器内的 `127.0.0.1` | 混合部署填 `http://172.17.0.1:17383/` |
| 群文件下载报 `packetBackend不可用` | QQ build 超出 `packetBackend` 支持范围 | 该后端最高支持 QQ build `36580`；升级 NapCat 不能修复超范围 build |
| `--selftest` 中途异常 | 自检读到了真实数据目录 | 不要让 `MMZBOT_DATA` 指向真实数据目录再跑；自检断言共 1155 条 |

## 怎么卸掉 / 回滚

先停服务，再备份。确认备份完成后才删除数据目录：

```bash
sudo systemctl disable --now mmzbot
sudo tar czf ~/mmzbot-backup.tar.gz -C /var/lib mmzbot
sudo rm -f /etc/systemd/system/mmzbot.service
sudo systemctl daemon-reload
```

删代码、数据和 NapCat 卷是不可逆操作。确认要彻底清除后再执行：

```bash
sudo rm -rf /opt/mmzbot /var/lib/mmzbot /var/log/mmzbot
sudo docker rm -f napcat
sudo docker volume rm napcat-config napcat-qq
```

回滚代码时只换回旧版 `/opt/mmzbot`，数据目录保留，然后 `sudo systemctl restart mmzbot`。更新或回滚 NapCat 前先记住：NapCat 重启会使 QQ 登录掉线。
