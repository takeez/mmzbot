# Agent 步骤：Docker / compose

## 0. 变量

在仓库根目录执行。把身份和模型密钥换成真实值。

```bash
MMZBOT_DIR="$PWD"
SELFID='填真实QQ号'
GROUP='填真实群号'
BOTNAME='机魂小悦'
WAKEWORDS='小悦'
TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
LLMKEY='填真实模型密钥'; LLMBASE='https://api.deepseek.com/v1'; LLMMODEL='deepseek-chat'
printf '%s\n' "$TOKEN"; ls "$MMZBOT_DIR/docker-compose.yml"
# 期望：打印随机 token，仓库有 docker-compose.yml；变量为真实值
# 失败：从仓库根目录重跑；没有 python3 时用安全方式生成并记录共享 token
```

## 1. 检查 Docker 和 Compose

```bash
docker --version && docker compose version
docker info >/dev/null
# 期望：Docker Engine 与 Compose v2 版本可用，daemon 可访问
# 失败：启动 Docker daemon；permission denied 时改用 sudo 执行后续 docker 命令
```

## 2. 检查仓库文件

```bash
cd "$MMZBOT_DIR"
ls docker-compose.yml docker/Dockerfile phone-bot-v2.py
# 期望：三个文件都存在
# 失败：MMZBOT_DIR 必须指向仓库根目录
```

## 3. 构建并启动 compose

```bash
docker compose pull
# 期望：出进度行
# 失败：0 字节不动就换站：
#       sudo docker pull docker.1ms.run/mlikiowa/napcat-docker:latest
#       sudo docker tag docker.1ms.run/mlikiowa/napcat-docker:latest mlikiowa/napcat-docker:latest

docker compose up -d --build
docker compose ps
# 期望：mmzbot 与 napcat 均为 Up
# 失败：docker compose logs --tail=50 mmzbot 与 napcat；检查端口、镜像拉取、Docker daemon
```

## 4. 确认初始配置（这一步集中询问，不猜值）

先读取代码目录的 `personality.md`，把全文展示给用户并询问是否想调整。不要直接修改人格文件；用户可以在安装后的面板中自行编辑。

一次询问以下信息：

1. 名称：默认 `机魂小悦`，可自定义，写入 `agent.name`。
2. 唤醒词：写入 `agent.wakeWords`；名称或唤醒词出现在消息开头时会唤醒机魂小悦回复。默认唤醒词为 `小悦`，可提供多个，也可以留空。
3. 她的 QQ 号（小号，别用常用的）。
4. 目标群号（该群要已包含机器人 QQ 号）。
5. 模型 API Key。
6. 模型：取得 Key 后运行下方 `--list-models` 查询可用模型和思考强度，再让用户选择。

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --list-models <接口地址> <模型密钥>
# 期望：列出模型 id，每个后面跟着它能用的思考强度；最后一行给可选强度
# 失败：这家不是 OpenAI 兼容接口（/models 没开），让用户直接给模型名
```

记录面板地址 `http://<服务器IP>:17383/panel` 和共享令牌 `TOKEN`。服务启动、NapCat 登录及群内回复验收通过后，按 Agent 安装入口的面板登录流程打开面板并粘贴令牌；若当前会话不能控制浏览器，则私下引导用户打开并粘贴。不要在群聊中发送令牌。

面板可管理初始化、设置、扩展包及其他配置。性格文件位于数据目录 `/data/personality.md`；用户可在面板中修改，或通过 `--persona-file <文件>` 指定。首次启动前使用代码目录中的默认文件。

## 5. 写入本体配置（用第 4 步要来的值）

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set "bot.selfId=$SELFID" "bot.groups=$GROUP" "bot.token=$TOKEN" "agent.name=$BOTNAME" "agent.wakeWords=$WAKEWORDS" napcat.baseUrl=http://napcat:3000 "llm.baseUrl=$LLMBASE" "llm.model=$LLMMODEL" "llm.apiKey=$LLMKEY"
printf 'exit=%s\n' "$?"
# 期望：出现“✓ 已保存”，退出码 0；容器内数据目录为 /data
# 失败：检查真实 QQ 号、群号、密钥和键名；容器之间访问 NapCat 用服务名 napcat
```

## 5.1 可选：配置增强网页搜索

推荐配置百度千帆搜索 API Key；未配置时将使用必应 RSS，搜索能力可能有所下降。将 `<搜索服务API密钥>` 替换为实际密钥：

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --set 'search.apiKey=<搜索服务API密钥>'
printf 'exit=%s\n' "$?"
# 期望：出现“✓ 已保存（1 项）”，退出码 0
# 失败：确认命令在 Compose 项目目录执行，并检查密钥
```

## 5.2 安装语义记忆模型（必需）

`docker compose up -d --build` 已在镜像构建时按 `requirements.txt` 安装三个 Python 依赖。下载模型到持久化数据卷：

```bash
docker compose exec -T mmzbot python3 tools/fetch_model.py
docker compose restart mmzbot
```

必须确认下载脚本显示 3 个文件全部就位。模型约 24 MB，来自 GitHub Release；失败时可用 `--base <镜像根地址>` 重试。依赖或模型缺失表示安装未完成。

首次启动后，在 QQ 中触发一次记忆查询或写入，再检查日志是否出现 `语义召回：模型加载好了`：

```bash
docker compose logs mmzbot | grep '语义召回：模型加载好了'
```

模型未安装时程序仍可能运行，但记忆检索不可用，会退回全量记忆并增加 token 消耗。

## 6. 检查本体 HTTP

```bash
curl -s http://127.0.0.1:17383/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17383/panel
docker compose ps
# 期望：根路径为“机魂小悦在跑。”，面板 200，两个容器 Up
# 失败：docker compose logs --tail=50 mmzbot；检查宿主机 17383 是否被占
```

## 7. 配好 NapCat 的网络（agent 做），然后让用户扫码

顺序不能反：NapCat 一重启就可能掉登录，所以网络配置要在扫码之前写完。

```bash
cat > /tmp/onebot11.json <<EOF
{"network":{"httpServers":[{"name":"mmzbot-http","enable":true,"host":"0.0.0.0","port":3000,"token":"$TOKEN","messagePostFormat":"array","enableCors":true}],"httpClients":[{"name":"mmzbot-report","enable":true,"url":"http://mmzbot:17383/","token":"$TOKEN","messagePostFormat":"array"}],"websocketServers":[],"websocketClients":[]}}
EOF
docker compose cp /tmp/onebot11.json napcat:/app/napcat/config/onebot11_<她的QQ号>.json
docker compose restart napcat
# 期望：docker compose ps 两个容器 Up；docker compose logs napcat 里能看到 [WebUi] Token 和二维码已保存
# 失败：docker compose logs --tail=50 napcat 看报错；确认文件名里的 QQ 号是对的
```

然后把二维码交给用户扫 —— 这是唯一需要他动手的地方：

```bash
docker compose cp napcat:/app/napcat/cache/qrcode.png /tmp/qrcode.png
# 期望：拿到 png；同时把 http://<服务器IP>:6099/webui?token=<WebUI令牌> 一起给用户
# 失败：二维码还没生成就等 10 秒再取；每张约两分钟过期，过期了重新取
```

对用户说的是：**用她的号扫这张图**（图给他，或让他开上面那个链接）。扫完他会说一声。

扫完再验：

```bash
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
# 期望：retcode 0，data.user_id 是她的号
# 失败：重新取二维码再扫；扫码之后再重启 NapCat 会掉登录，别重启
```

compose 映射的 3000 / 6099 只允许本机或管理网段访问；不要对公网开放。

## 8. 收尾验收命令

```bash
docker compose exec -T mmzbot python3 phone-bot-v2.py --check; RC=$?; printf 'exit=%s\n' "$RC"
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
docker compose ps
# 期望：--check 六项全 ✓、退出码 0；NapCat retcode 0；两个容器 Up
# 失败：退出码 1 检查配置、服务名和 NapCat HTTP 服务器；退出码 2 检查参数；人工在群里验证回复
```

## 混合部署：本体原生，NapCat 用容器

本节用于本体由 Linux systemd 运行、NapCat 单独 Docker 运行的情况，不要套用 compose 内部服务名。

```bash
MMZBOT_DATA=/var/lib/mmzbot
MMZBOT_DIR=/opt/mmzbot
RUN_USER=mmzbot
TOKEN='使用与 bot.token 相同的 token'
sudo docker run -d --name napcat --restart unless-stopped -p 3000:3000 -p 6099:6099 -e NAPCAT_UID=1000 -e NAPCAT_GID=1000 -v napcat-config:/app/napcat/config -v napcat-qq:/app/.config/QQ mlikiowa/napcat-docker:latest
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set bot.control.allowIps=172.17.0.0/16 napcat.baseUrl=http://127.0.0.1:3000
# 期望：NapCat 容器 Up；本体配置保存；宿主本体用 127.0.0.1:3000 访问 API
# 失败：确认宿主机 3000/6099 没占用，docker0 网桥存在，MMZBOT_DATA 属主正确
```

```bash
ip -4 addr show docker0
sudo docker exec napcat bash -c 'timeout 5 bash -c "exec 3<>/dev/tcp/172.17.0.1/17383; printf \"GET / HTTP/1.0\\r\\n\\r\\n\" >&3; head -1 <&3"'
# 期望：docker0 默认网关为 172.17.0.1；探测返回 HTTP/1.1 200 OK
# 失败：本体要允许 172.17.0.0/16，且监听在容器可访问的地址
```

需要人工在 NapCat WebUI 设置 HTTP 服务器 `3000`，token=`$TOKEN`；HTTP 上报 URL=`http://172.17.0.1:17383/`，token=`$TOKEN`。保存后再重启 NapCat 并扫码。

## 运行限制与验收提醒

- Compose 网络内，本体访问 NapCat 使用 `http://napcat:3000`，NapCat 上报地址为 `http://mmzbot:17383/`。
- 混合部署时，本体访问 NapCat 使用 `http://127.0.0.1:3000`；NapCat 上报至 `http://172.17.0.1:17383/`，本体需设置 `bot.control.allowIps=172.17.0.0/16`。
- `--check` 前五项检查是否填写，第六项探测 NapCat；退出码 `0/1/2` 分别表示通过、配置缺失或探测失败、参数错误。示例占位值不通过。
- `--set` 配置热加载；修改本体 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置需重启后生效，重启可能导致 QQ 重新登录。
- 端口冲突时执行：
  ```bash
  docker compose exec -T mmzbot python3 phone-bot-v2.py --set port=17390
  ```
  同时将 `docker-compose.yml` 中的端口映射改为 `17390:17390`，将 NapCat 上报地址改为 `http://mmzbot:17390/`；保存 NapCat 配置并重启 NapCat，再运行 `docker compose up -d` 重新创建容器。面板地址也改用端口 `17390`。
- 局域网其他设备访问面板返回 `403` 时，保留 Docker 网桥网段并追加本机网段：
  ```bash
  docker compose exec -T mmzbot python3 phone-bot-v2.py --set bot.control.allowIps=172.16.0.0/12,192.168.1.0/24
  ```
  不要使用 `0.0.0.0/0`；公网访问应使用带登录保护的反向代理。
- 思考强度可设置为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。例如：
  ```bash
  docker compose exec -T mmzbot python3 phone-bot-v2.py --set llm.effort=low
  ```
  `--list-models` 会列出各模型支持的强度档位。
- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；使用 `curl` 检查时加 `-L`。二维码约两分钟刷新一次。`packetBackend` 最高支持 QQ build `36580`，超出后群文件下载不可用。
- `--selftest` 有 1155 条断言；不要让 `MMZBOT_DATA` 指向真实数据目录。

## 验收清单

- [ ] `--check` 六项全 ✓，退出码 `0`。
- [ ] NapCat `get_login_info` 返回 `retcode:0`。
- [ ] compose 里的 `mmzbot` 和 `napcat` 均为 `Up`。
- [ ] 人工在目标群发消息，她能回复。
