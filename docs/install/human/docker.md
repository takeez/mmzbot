# Docker Compose 部署

## 适用范围

本指南介绍如何在 Linux 上通过 Docker Compose 运行机魂小悦和 NapCat，也包括本体原生运行、NapCat 单独使用容器的混合部署。Android 设备请参阅 [Termux 部署指南](termux.md)，Windows 本体请参阅 [Windows 部署指南](windows.md)。

## 准备条件

| 项目 | 要求 | 怎么确认 |
|---|---|---|
| 系统 | 能运行 Docker Engine 的 Linux，x86_64 或 arm64 | `uname -m` |
| Docker | Docker Engine 和 Compose v2 | `docker --version`、`docker compose version` |
| 内存 / 磁盘 | 建议内存 2 GB 起；卷预留 4–6 GB | `free -h`、`df -h /var/lib/docker` |
| 公网 IP | 不需要。外部访问面板才需要公网入口或内网穿透 | — |
| 图形界面 | 不需要，本体与 NapCat 在容器中运行 | — |
| 权限 | 有 Docker daemon 权限，或命令前使用 `sudo` | `docker ps` |
| 端口 | 机魂小悦 `17383`；NapCat API `3000`；WebUI `6099` | `ss -ltnp` |

数据存入 compose 卷。NapCat 镜像使用 `mlikiowa/napcat-docker:latest`，里面带 QQ 和 NapCat。Docker 安装方式看 [Docker Engine 文档](https://docs.docker.com/engine/install/)。

## 部署注意事项

- QQ 通道不能省。compose 方案里 NapCat 与本体并排运行。NapCat API token、上报 token 和本体 `bot.token` 必须一致。
- Docker、Compose 和镜像使用可获得的最新稳定版。compose 内本体访问 NapCat 用服务名 `napcat`，不是 `127.0.0.1`。NapCat 配置改完需重启，可能会掉 QQ 登录；先配完再扫码。

## 部署步骤

### 1. 检查 Docker 和 compose

```bash
docker --version
docker compose version
```

**预期结果：** 两条都打印版本号，Compose 为 v2。

**未通过时检查：** `permission denied` 表示当前用户没有 Docker daemon 权限；改用 `sudo docker ...`，或按系统的 Docker 文档配置权限。

### 2. 检查仓库目录

在仓库根目录运行：

```bash
ls docker-compose.yml docker/Dockerfile phone-bot-v2.py
```

**预期结果：** 三个文件都存在。

**未通过时检查：** `pwd` 确认是否在仓库根目录；不是就 `cd` 到包含这三个文件的目录。

### 3. 构建并启动两个服务

```bash
docker compose up -d --build
docker compose ps
```

**预期结果：** `mmzbot` 与 `napcat` 均为 `Up`。首次构建会下载基础镜像，并在镜像中按 `requirements.txt` 安装语义记忆依赖。

**未通过时检查：** 执行 `docker compose logs --tail=50 mmzbot` 和 `docker compose logs --tail=50 napcat`。留意端口冲突、镜像下载失败或数据目录权限错误。

### 4. 配置本体

生成 token 并记下来：

```bash
TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
printf '%s\n' "$TOKEN"
```

名称默认为 `机魂小悦`，可按需自定。`agent.name` 和 `agent.wakeWords` 中的词出现在消息开头时会唤醒机魂小悦；`agent.wakeWords` 可以留空。首次配置时请先查看 `personality.md`，确认是否需要修改；登录面板后可以继续调整。在仓库目录运行，用真实 QQ 号、群号和模型密钥替换占位值：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set \
  bot.selfId=<真实QQ号> bot.groups=<真实群号> bot.token="$TOKEN" \
  agent.name=机魂小悦 agent.wakeWords=小悦 \
  napcat.baseUrl=http://napcat:3000 \
  llm.baseUrl=https://api.deepseek.com/v1 llm.model=deepseek-chat llm.apiKey=<真实模型密钥>
```

**预期结果：** `✓ 已保存（N 项），下一条消息就按新值走`。

**未通过时检查：** 确认命令在 compose 项目目录运行，容器里的数据目录是 `/data`。必须使用 `http://napcat:3000`；容器内的 `127.0.0.1` 指向本体容器本身。

### 5. 可选：配置网页搜索 API Key

配置搜索服务 API Key 后，网页搜索可使用百度千帆搜索。未配置时会回退到必应 RSS，搜索结果与能力可能有所不同。将 `<搜索服务 API Key>` 替换为你在搜索服务平台获取的密钥，在 Compose 项目目录执行：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set 'search.apiKey=<搜索服务API密钥>'
```

**预期结果：** `✓ 已保存（1 项），下一条消息就按新值走`。此项为可选配置；之后可用相同命令更新密钥。

### 5. 确认本体面板

```bash
curl -s http://127.0.0.1:17383/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17383/panel
```

**预期结果：** 根路径返回 `机魂小悦在跑。`，面板返回 `200`。

**未通过时检查：** `docker compose ps` 和 `docker compose logs --tail=50 mmzbot`。本体 `--set` 改配置后不用重启；`port`、`host` 或 `.py` 文件改动后要重启本体。

### 6. 配置 NapCat 并登录

打开 `http://<服务器IP>:6099/webui`，用 NapCat 日志中的 WebUI token 登录。在网络配置中添加：

| 项目 | 值 |
|---|---|
| HTTP 服务器 | 启用，端口 `3000`，token 填 `$TOKEN` |
| HTTP 上报 / HTTP 客户端 | 启用，地址 `http://mmzbot:17383/`，token 填 `$TOKEN` |

保存配置后重启 NapCat，再通过 WebUI 显示的实时二维码扫码。二维码约两分钟一换。

```bash
docker compose restart napcat
docker compose logs --tail=40 napcat
```

**预期结果：** NapCat 日志有 WebUI 信息和二维码生成记录；扫码后 API 返回 `retcode:0`。compose 默认映射 3000 和 6099 到宿主机所有接口，防火墙只放可信来源；不要把它们直接暴露到公网。

**未通过时检查：** NapCat 日志、WebUI 网络配置和登录状态。首页 `6099/` 会 `301` 到 `/webui`，用 `curl` 检查时加 `-L`。若端口映射存在但 API reset，NapCat 内可能还没有启用 HTTP 服务器。

## 修改配置

第 4 步已写入基本配置。之后可在面板或通过 `--set` 修改；两者写入同一份 `/data/local-config.json`。`--list-models` 会列出每个模型支持的思考强度：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --list-models <地址> <密钥>
```

### 设置思考强度

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set llm.effort=low
```

可选值为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。强度变更在后续请求生效。

### 处理端口冲突

如果默认端口 `17383` 已被占用，可改为 `17390`：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set port=17390
```

还需将 `docker-compose.yml` 的端口映射改为 `"17390:17390"`，并将 NapCat 上报地址改为 `http://mmzbot:17390/`。保存 NapCat 配置后重启 NapCat（可能需要重新扫码），再运行 `docker compose up -d` 重新创建容器。面板地址改为 `http://<服务器IP>:17390/panel`；后续检查命令中的 `17383` 也应替换为 `17390`。

### 允许局域网访问面板

若同一局域网设备打开面板返回 `403`，保留 Docker 网桥网段并追加本地网段（替换示例 CIDR）：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set bot.control.allowIps=172.16.0.0/12,192.168.1.0/24
```

不要使用 `0.0.0.0/0`。此设置仅用于局域网；公网访问应使用带登录保护的反向代理，见[反向代理说明](../../reverse-proxy.md)。

### 安装语义记忆模型（必需）

`docker compose up -d --build` 已在镜像构建时安装 `requirements.txt` 中的三个 Python 依赖。模型文件需另行下载到持久化数据卷：

```bash
docker compose exec -T mmzbot python3 tools/fetch_model.py
docker compose restart mmzbot
```

下载必须显示 3 个文件全部就位（约 24 MB）；失败可用 `--base <镜像根地址>` 重试。依赖或模型缺失时，程序可能启动，但记忆检索不可用，安装未完成。

在 QQ 中触发一次记忆查询或写入后，检查日志是否出现 `语义召回：模型加载好了`：

```bash
docker compose logs mmzbot | grep '语义召回：模型加载好了'
```

本体需要 QQ 号、共享 token、群号、模型与 API Key，以及人设正文；首次人设检查可能读取代码目录中的 `personality.md`。之后可在面板编辑人设，或用 `--persona-file` 指定。

`--set` 配置通常热加载；修改本体 `port`、`host` 或 Python 文件后，执行 `docker compose restart mmzbot`。NapCat 配置不热加载，重启可能使 QQ 掉线，网络配置应先完成再扫码。

### 混合部署：本体原生，NapCat 用容器

这时两个程序不在同一个容器网络。宿主机本体通过映射端口访问 NapCat：`napcat.baseUrl=http://127.0.0.1:3000`。NapCat 容器不能用 `127.0.0.1` 上报给宿主机，默认 Docker 网桥网关地址是 `172.17.0.1`。

本体配置加入：

```bash
sudo -u mmzbot env MMZBOT_DATA=/var/lib/mmzbot python3 /opt/mmzbot/phone-bot-v2.py --set \
  bot.control.allowIps=172.17.0.0/16 \
  napcat.baseUrl=http://127.0.0.1:3000
```

NapCat 容器映射端口并保留配置卷：

```bash
sudo docker run -d --name napcat --restart unless-stopped \
  -p 3000:3000 -p 6099:6099 \
  -e NAPCAT_UID=1000 -e NAPCAT_GID=1000 \
  -v napcat-config:/app/napcat/config \
  -v napcat-qq:/app/.config/QQ \
  mlikiowa/napcat-docker:latest
```

NapCat WebUI 中 HTTP 上报地址必须是 `http://172.17.0.1:17383/`，HTTP 服务器监听 3000；两项 token 都与 `bot.token` 相同。默认网桥网关可用 `ip -4 addr show docker0` 核对。没有 `bot.control.allowIps=172.17.0.0/16` 时，容器请求会被当成公网来源并收到 404。

## 启动并验证

```bash
docker compose ps
docker compose exec -T mmzbot python3 phone-bot-v2.py --check
printf 'exit=%s\n' "$?"
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
```

**预期结果：** 两个服务都是 `Up`；`--check` 六项全 ✓、退出码 `0`；NapCat 登录查询返回 `retcode:0`。再到目标群发一句，确认机魂小悦能回复。

`--check` 前五项只看填没填，第六项才真探测 NapCat。退出码 `1` 是还缺配置或通道不通，`2` 是参数错误。

## 出问题时

| 症状 | 原因 | 怎么办 |
|---|---|---|
| `docker compose exec` 提示不是 TTY | 命令运行在脚本或管道中 | 使用 `docker compose exec -T ...` |
| `mmzbot` 或 `napcat` 一直 `Restarting` | 容器启动失败 | 查对应服务的 `docker compose logs --tail=50` |
| NapCat API 连接失败 | 本体填了 `127.0.0.1:3000` | 同一 compose 用 `http://napcat:3000` |
| 容器里的 NapCat 上报返回 404 | 本体没允许 Docker 网桥来源 | 设置 `bot.control.allowIps=172.17.0.0/16` |
| 混合部署上报不到本体 | NapCat 地址填了容器内的 `127.0.0.1` | 使用 `http://172.17.0.1:17383/` |
| API 连接重置或 token 错 | NapCat HTTP 服务器没建，或 token 不一致 | WebUI 启用 HTTP 服务器，并核对两处 token |
| NapCat 改配置没反应 | NapCat 不热加载 | 保存配置后重启；需要时重新扫码 |
| 群文件下载失败 | QQ build 超过支持范围 | `packetBackend` 最高支持 QQ build `36580`；NapCat 升级不能改变该上限 |
| `--selftest` 读到实际配置 | 容器环境把真实 `/data` 暴露给测试 | 自检有 1155 条；不要让 `MMZBOT_DATA` 指向真实数据目录 |

## 卸载与回滚

先从运行中的容器读取 Compose 实际挂载的卷名，再停止服务。不要假设卷名就是 `mmzbot-data`：Compose 通常会在逻辑卷名前加项目名前缀。

```bash
set -e
MMZBOT_CID=$(docker compose ps -q mmzbot)
NAPCAT_CID=$(docker compose ps -q napcat)
test -n "$MMZBOT_CID" && test -n "$NAPCAT_CID" || { echo '容器未运行；请先确认卷名，不要继续删除卷'; exit 1; }
MMZBOT_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$MMZBOT_CID")
NAPCAT_CONFIG_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/napcat/config"}}{{.Name}}{{end}}{{end}}' "$NAPCAT_CID")
NAPCAT_QQ_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/.config/QQ"}}{{.Name}}{{end}}{{end}}' "$NAPCAT_CID")
printf 'MMZBOT=%s\nNapCat config=%s\nNapCat QQ=%s\n' "$MMZBOT_VOLUME" "$NAPCAT_CONFIG_VOLUME" "$NAPCAT_QQ_VOLUME"
test -n "$MMZBOT_VOLUME" && test -n "$NAPCAT_CONFIG_VOLUME" && test -n "$NAPCAT_QQ_VOLUME" || { echo '未能识别全部数据卷；停止并人工核对'; exit 1; }

docker compose down
docker run --rm -v "$MMZBOT_VOLUME:/source:ro" -v "$PWD:/backup" alpine tar czf /backup/mmzbot-data-backup.tar.gz -C /source .
docker run --rm -v "$NAPCAT_CONFIG_VOLUME:/source:ro" -v "$PWD:/backup" alpine tar czf /backup/napcat-config-backup.tar.gz -C /source .
docker run --rm -v "$NAPCAT_QQ_VOLUME:/source:ro" -v "$PWD:/backup" alpine tar czf /backup/napcat-qq-backup.tar.gz -C /source .
tar tzf mmzbot-data-backup.tar.gz >/dev/null && tar tzf napcat-config-backup.tar.gz >/dev/null && tar tzf napcat-qq-backup.tar.gz >/dev/null
```

确认三份归档均可读取并妥善保存后，才运行 `docker compose down -v`。该命令会删除机魂小悦的配置、密钥和记忆，以及 NapCat 配置与 QQ 数据；删除后无法直接撤回。仅回滚本体代码时恢复旧代码并运行 `docker compose up -d --build`，保留这三个数据卷。
