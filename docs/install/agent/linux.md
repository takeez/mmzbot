# Agent 步骤：Linux 原生 + systemd

## 0. 变量

先在 shell 里填真实值。`SELFID`、`GROUP`、`LLMKEY` 的示例值都是占位，不能照抄上线 —— 这三样在第 4 步问用户要。

```bash
SRC=/path/to/MMZBOT
MMZBOT_DIR=/opt/mmzbot
MMZBOT_DATA=/var/lib/mmzbot
MMZBOT_LOG=/var/log/mmzbot
RUN_USER=mmzbot
SELFID=填真实QQ号
GROUP=填真实群号
BOTNAME='机魂小悦'
WAKEWORDS='小悦'
TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
LLMKEY='填真实模型密钥'
LLMBASE=https://api.deepseek.com/v1
LLMMODEL=deepseek-chat
# 期望：printf '%s\n' "$TOKEN" 打印随机 token；其它变量均为实际路径和值
# 失败：python3 不存在时先装 Python 3.11+；不要继续使用任何示例占位值
```

## 1. 检查系统并安装依赖

```bash
cat /etc/os-release
df -h / ; free -m
sudo apt-get update -qq && sudo apt-get install -y python3 python3-venv curl rsync git
python3 --version
# 期望：Ubuntu 24.04.5 / Debian 12+，Python 3.11+，/ 空闲 ≥5 GB
# 失败：空间不够先扩容
```

## 2. 建服务用户和目录

```bash
id "$RUN_USER" >/dev/null 2>&1 || sudo useradd -r -M -s /usr/sbin/nologin "$RUN_USER"
sudo mkdir -p "$MMZBOT_DIR" "$MMZBOT_DATA" "$MMZBOT_LOG"
sudo chown -R "$RUN_USER:$RUN_USER" "$MMZBOT_DIR" "$MMZBOT_DATA" "$MMZBOT_LOG"
# 期望：id "$RUN_USER" 成功；三个目录存在且归运行用户所有
# 失败：核对 RUN_USER 和目录路径；不要用 useradd -m，避免 dotfiles 写进数据目录
```

## 3. 放置代码

代码得先上去。从 Windows 宿主机推进来（在宿主机跑）：

```powershell
scp -r C:\Users\<你>\MMZBOT <用户>@<服务器>:/tmp/MMZBOT
```

然后在服务器上放下：

```bash
sudo rsync -a --exclude=.git --exclude=__pycache__ "$SRC/" "$MMZBOT_DIR/"
sudo chown -R "$RUN_USER:$RUN_USER" "$MMZBOT_DIR"
sudo chmod 755 "$MMZBOT_DIR"
# 期望：ls "$MMZBOT_DIR/phone-bot-v2.py" "$MMZBOT_DIR/mmzbot.service" 成功
# 失败：检查 SRC 是否指向仓库根目录（默认 /path/to/MMZBOT，要改成你实际的路径）；
#       源目录可能带 700 权限，必须确认目标目录可进入
```

## 3.1 安装语义记忆依赖与模型（必需）

创建服务用户的虚拟环境，安装 `requirements.txt` 中的依赖，并下载模型到 `$MMZBOT_DATA`：

```bash
sudo -u "$RUN_USER" python3 -m venv "$MMZBOT_DIR/.venv"
sudo -u "$RUN_USER" "$MMZBOT_DIR/.venv/bin/python" -m pip install -r "$MMZBOT_DIR/requirements.txt"
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" "$MMZBOT_DIR/.venv/bin/python" "$MMZBOT_DIR/tools/fetch_model.py"
```

下载必须显示 3 个文件全部就位。模型约 24 MB，来自 GitHub Release，不在 Git 仓库内；下载失败时可加 `--base <镜像根地址>` 重试。依赖或模型缺失时，部署未完成。

systemd 的 `run.sh` 会自动使用 `.venv`。服务启动后，在 QQ 中触发一次记忆查询或写入，再检查 `/var/lib/mmzbot/bot.log` 是否出现 `语义召回：模型加载好了`。模型未安装时程序仍可能运行，但记忆检索不可用，会退回全量记忆并增加 token 消耗。

## 4. 确认初始配置（这一步集中询问，不猜值）

先读取 `$MMZBOT_DIR/personality.md`，把全文展示给用户并询问是否想调整。不要直接修改人格文件；用户可以在安装后的面板中自行编辑。

一次询问以下信息：

1. 名称：默认 `机魂小悦`，可自定义，写入 `agent.name`。
2. 唤醒词：写入 `agent.wakeWords`；名称或唤醒词出现在消息开头时会唤醒机魂小悦回复。默认唤醒词为 `小悦`，可提供多个，也可以留空。
3. 她的 QQ 号（小号，别用常用的）。
4. 目标群号（该群要已包含机器人 QQ 号）。
5. 模型 API Key。
6. 模型：取得 Key 后运行下方 `--list-models` 查询可用模型和思考强度，再让用户选择。

```bash
python3 "$MMZBOT_DIR/phone-bot-v2.py" --list-models <接口地址> <模型密钥>
# 期望：列出模型 id，每个后面跟着它能用的思考强度；最后一行给可选强度
# 失败：这家不是 OpenAI 兼容接口（/models 没开），让用户直接给模型名
```

记录面板地址 `http://<这台机器IP>:17383/panel` 和共享令牌 `TOKEN`。服务启动、NapCat 登录及群内回复验收通过后，按 Agent 安装入口的面板登录流程打开面板并粘贴令牌；若当前会话不能控制浏览器，则私下引导用户打开并粘贴。不要在群聊中发送令牌。

面板可管理初始化、设置、扩展包及其他配置。性格文件位于数据目录 `personality.md`；用户可在面板中修改，或通过 `--persona-file <文件>` 指定。首次启动时使用代码目录中的默认文件。

## 5. 写入本体配置（用第 4 步要来的值）

```bash
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set bot.selfId="$SELFID" bot.groups="$GROUP" bot.token="$TOKEN" agent.name="$BOTNAME" agent.wakeWords="$WAKEWORDS" napcat.baseUrl=http://127.0.0.1:3000 llm.baseUrl="$LLMBASE" llm.model="$LLMMODEL" llm.apiKey="$LLMKEY"
printf 'exit=%s\n' "$?"
# 期望：出现“✓ 已保存”，退出码 0；bot.token 同步写入 NapCat token 字段
# 失败：确认真实 QQ 号、群号、模型密钥与 MMZBOT_DATA；检查目录属主
```

## 6. 可选：配置增强网页搜索

推荐配置百度千帆搜索 API Key；未配置时将使用必应 RSS，搜索能力可能有所下降。将 `<搜索服务API密钥>` 替换为实际密钥：

```bash
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set search.apiKey=<搜索服务API密钥>
# 期望：出现“✓ 已保存（1 项）”
# 失败：确认使用与本体配置相同的运行用户和 MMZBOT_DATA
```

## 7. 安装并启动 systemd

```bash
sudo cp "$MMZBOT_DIR/mmzbot.service" /etc/systemd/system/mmzbot.service
sudo chmod 644 /etc/systemd/system/mmzbot.service && sudo systemctl daemon-reload && sudo systemctl enable --now mmzbot
systemctl is-active mmzbot && systemctl is-enabled mmzbot
# 期望：active 和 enabled
# 失败：sudo journalctl -u mmzbot -n 50 --no-pager；核对 unit 的代码、数据、日志路径
```

## 7. 探测本体 HTTP

```bash
curl -s http://127.0.0.1:17383/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17383/panel
ss -ltnp | grep 17383
# 期望：根路径为“机魂小悦在跑。”，面板 200，端口有 LISTEN
# 失败：检查 systemd 状态、journalctl 日志和 17383 端口占用
```

## 8. 启动 NapCat Docker

```bash
sudo apt-get install -y docker.io && sudo systemctl enable --now docker
sudo docker pull mlikiowa/napcat-docker:latest
# 期望：出进度行，最后 Downloaded newer image
# 失败：0 字节不动就换站：
#       sudo docker pull docker.1ms.run/mlikiowa/napcat-docker:latest
#       sudo docker tag  docker.1ms.run/mlikiowa/napcat-docker:latest mlikiowa/napcat-docker:latest

sudo docker run -d --name napcat --restart unless-stopped -p 3000:3000 -p 6099:6099 -e NAPCAT_UID=1000 -e NAPCAT_GID=1000 -v napcat-config:/app/napcat/config -v napcat-qq:/app/.config/QQ mlikiowa/napcat-docker:latest
sudo docker ps --filter name=napcat
# 期望：NapCat 容器 Up，映射 3000 和 6099
# 失败：sudo docker logs --tail=50 napcat；检查 Docker daemon 和宿主端口占用
```

## 9. 设混合部署白名单

```bash
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set bot.control.allowIps=172.17.0.0/16
ip -4 addr show docker0
sudo docker exec napcat bash -c 'timeout 5 bash -c "exec 3<>/dev/tcp/172.17.0.1/17383; printf \"GET / HTTP/1.0\\r\\n\\r\\n\" >&3; head -1 <&3"'
# 期望：配置保存成功；docker0 网关为 172.17.0.1；探测返回 HTTP/1.1 200 OK
# 失败：检查 allowIps、docker0 网桥与本体 17383 的监听地址
```

## 10. 配好 NapCat 的网络（agent 做），然后让用户扫码

顺序不能反：NapCat 重启会掉登录，所以先写配置再扫码。`systemctl restart docker` 一样会把 NapCat 带重启。

```bash
cat > /tmp/onebot11.json <<EOF
{"network":{"httpServers":[{"name":"mmzbot-http","enable":true,"host":"0.0.0.0","port":3000,"token":"$TOKEN","messagePostFormat":"array","enableCors":true}],"httpClients":[{"name":"mmzbot-report","enable":true,"url":"http://172.17.0.1:17383/","token":"$TOKEN","messagePostFormat":"array"}],"websocketServers":[],"websocketClients":[]}}
EOF
sudo docker cp /tmp/onebot11.json napcat:/app/napcat/config/onebot11_<她的QQ号>.json
sudo docker restart napcat
# 期望：容器 Up；docker logs napcat 里能看到 [WebUi] Token 和二维码已保存
# 失败：docker logs --tail=50 napcat 看启动报错；确认文件名字里的 QQ 号是对的
```

然后把二维码交给用户扫 —— 这是唯一需要他动手的地方：

```bash
sudo docker cp napcat:/app/napcat/cache/qrcode.png /tmp/qrcode.png
# 期望：拿到 png；同时把 http://<这台机器IP>:6099/webui?token=<WebUI令牌> 一起给用户
# 失败：二维码还没生成就等 10 秒再取；每张约两分钟过期，过期了重新取
```

对用户说的是：**用她的号扫这张图**（图给他，或让他开上面那个链接）。扫完他会说一声。

扫完再验：

```bash
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
# 期望：retcode 0，data.user_id 是她的号
# 失败：重新取二维码再扫；扫码之后再重启 NapCat 会掉登录，别重启
```

防火墙 / 云安全组只允许本机或管理网段访问 `3000`、`6099`；不要对公网开放。

## 11. 收尾验收命令

```bash
sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --check; RC=$?; printf 'exit=%s\n' "$RC"
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
systemctl is-active mmzbot && systemctl is-enabled mmzbot && ss -ltnp | grep 17383
# 期望：--check 六项全 ✓ 且退出码 0；NapCat retcode 0；服务 active/enabled、端口 LISTEN
# 失败：退出码 1 检查配置与 NapCat；退出码 2 检查参数；退出码 0 后还需人工在目标群发消息确认回复
```

## 运行限制与验收提醒

- `--check` 前五项只检查是否填写，第六项会探测 NapCat。占位值 `10000`、`1234567890`、`987654321`、`sk-PLACEHOLDER…` 不通过。
- `--set` 配置热加载；修改 `port`、`host` 或 Python 文件后，运行 `sudo systemctl restart mmzbot`。NapCat 配置需重启后生效，重启可能导致 QQ 重新登录。
- 端口 `17383` 被占用时，可改为 `17390`：
  ```bash
  sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set port=17390
  sudo systemctl restart mmzbot
  ```
  同时将 NapCat 上报地址改为 `http://172.17.0.1:17390/`，面板地址改用 `http://<服务器IP>:17390/panel`；后续端口检查命令中的 `17383` 也应改为 `17390`。
- 局域网中的其他设备访问面板返回 `403` 时，将自己的局域网 CIDR 加入白名单；混合部署需保留 Docker 网桥网段，例如设为 `172.17.0.0/16,192.168.1.0/24`：
  ```bash
  sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set bot.control.allowIps=172.17.0.0/16,192.168.1.0/24
  ```
  不要使用 `0.0.0.0/0`；公网访问应使用带登录保护的反向代理。
- 思考强度可设置为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。例如：
  ```bash
  sudo -u "$RUN_USER" env MMZBOT_DATA="$MMZBOT_DATA" python3 "$MMZBOT_DIR/phone-bot-v2.py" --set llm.effort=low
  ```
  `--list-models` 会列出各模型支持的强度档位。
- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；使用 `curl` 检查时加 `-L`。`packetBackend` 最高支持 QQ build `36580`，超出后群文件下载不可用。
- `--selftest` 有 1155 条断言；不要让 `MMZBOT_DATA` 指向真实数据目录。

## 验收清单

- [ ] `--check` 六项全 ✓，退出码 `0`。
- [ ] NapCat `get_login_info` 返回 `retcode:0`。
- [ ] systemd 为 `active` / `enabled`，17383 正在监听。
- [ ] 人工在目标群发消息，她能回复。
