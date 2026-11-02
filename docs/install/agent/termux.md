# Agent 步骤：Termux + proot Debian

## 准备工作：授权手机存储

在 Termux App 中先运行并等待用户授权；后续要读取 `/sdcard/Download`：

```bash
termux-setup-storage
```

## 0. 变量（Termux 侧）

以下命令在 Termux App 里运行。身份与密钥必须换成真实值。

```bash
DISTRO=debian
SOURCE=/sdcard/Download/MMZBOT
MMZBOT_DIR=/root/mmzbot
MMZBOT_DATA=/root/mmzbot
SELFID='填真实QQ号'; GROUP='填真实群号'
BOTNAME='机魂小悦'; WAKEWORDS='小悦'
TOKEN="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
LLMKEY='填真实模型密钥'; LLMBASE='https://api.deepseek.com/v1'; LLMMODEL='deepseek-chat'
printf '%s\n' "$TOKEN"
# 期望：生成并记录 token；路径为容器内绝对路径；账号与密钥均为真实值
# 失败：命令必须在 Termux App 里执行；不要使用 sudo 或保留示例占位值
```

## 1. 安装 Termux 侧工具

```bash
pkg update -y && pkg install -y proot-distro curl
proot-distro list
# 期望：命令成功，发行版列表中有 debian
# 失败：`pkg: command not found` 表示不在 Termux；检查 Termux 源与网络
```

## 2. 安装 Debian 并装依赖

```bash
proot-distro install "$DISTRO"
proot-distro login "$DISTRO" -- bash -lc 'cat /etc/debian_version && apt update && apt install -y python3 python3-venv curl ca-certificates unzip'
proot-distro login "$DISTRO" -- bash -lc 'python3 --version'
# 期望：Debian 版本可读，Python 3.11 或更高
# 失败：确认 proot-distro list 中有该别名；容器内用 apt，不用 sudo
```

## 3. 放置仓库代码

先将仓库放入 Debian 的 `$MMZBOT_DIR`，再检查关键文件：

```bash
proot-distro login "$DISTRO" --bind /sdcard:/sdcard -- bash -lc "mkdir -p '$MMZBOT_DIR' && cp -a '$SOURCE/.' '$MMZBOT_DIR/' && ls '$MMZBOT_DIR/phone-bot-v2.py' '$MMZBOT_DIR/fg-bot-v2-start.sh' '$MMZBOT_DIR/mmzbot-watchdog.sh'"
# 期望：代码复制完成，三个关键文件均存在
# 失败：确认 SOURCE 指向手机存储中的仓库目录；检查 proot 是否绑定 /sdcard
```

## 3.1 安装语义记忆依赖与模型（必需）

在 Debian 中创建虚拟环境、安装依赖并下载模型到 `$MMZBOT_DATA`：

```bash
proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && MMZBOT_DATA='$MMZBOT_DATA' .venv/bin/python tools/fetch_model.py"
```

下载脚本必须显示 3 个文件全部就位。模型约 24 MB，来自 GitHub Release；失败时可用 `--base <镜像根地址>` 重试。依赖或模型缺失表示安装未完成。启动脚本会优先使用 `.venv` 中的 Python。

本体启动后，在 QQ 中触发一次记忆查询或写入，然后从 Termux 运行以下命令检查 Debian 数据目录日志：

```bash
proot-distro login "$DISTRO" -- bash -lc "grep -F '语义召回：模型加载好了' '$MMZBOT_DATA/bot.log'"
```

模型缺失时程序仍可能运行，但记忆检索不可用，会退回全量记忆并增加 token 消耗。

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
proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && python3 phone-bot-v2.py --list-models <接口地址> <模型密钥>"
# 期望：列出模型 id，每个后面跟着它能用的思考强度；最后一行给可选强度
# 失败：这家不是 OpenAI 兼容接口（/models 没开），让用户直接给模型名
```

记录面板地址 `http://<手机IP>:17383/panel` 和共享令牌 `TOKEN`。服务启动、NapCat 登录及群内回复验收通过后，按 Agent 安装入口的面板登录流程打开面板并粘贴令牌；若当前会话不能控制浏览器，则私下引导用户打开并粘贴。不要在群聊中发送令牌。

面板可管理初始化、设置、扩展包及其他配置。性格文件位于数据目录 `personality.md`；用户可在面板中修改，或通过 `--persona-file <文件>` 指定。首次启动前使用代码目录中的默认文件。

## 5. 配置本体（用第 4 步要来的值）
```bash
proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --set bot.selfId='$SELFID' bot.groups='$GROUP' bot.token='$TOKEN' agent.name='$BOTNAME' agent.wakeWords='$WAKEWORDS' napcat.baseUrl=http://127.0.0.1:3000 llm.baseUrl='$LLMBASE' llm.model='$LLMMODEL' llm.apiKey='$LLMKEY'"
# 期望：出现“✓ 已保存”；bot.token 同步写入 NapCat token 字段
# 失败：检查数据目录、真实 QQ 号/群号/模型密钥；配置与启动时必须指向同一目录
```

## 6. 建立 Termux 入口并启动本体

```bash
ROOTFS="$PREFIX/var/lib/proot-distro/installed-rootfs/$DISTRO"
cat > ~/runinc.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
exec proot-distro login debian -- bash -lc "$1"
EOF
chmod +x ~/runinc.sh && cp "$ROOTFS$MMZBOT_DIR/fg-bot-v2-start.sh" ~/fg-bot-v2-start.sh && cp "$ROOTFS$MMZBOT_DIR/mmzbot-watchdog.sh" ~/mmzbot-watchdog.sh && chmod +x ~/fg-bot-v2-start.sh ~/mmzbot-watchdog.sh
MMZBOT_DIR="$MMZBOT_DIR" MMZBOT_DATA="$MMZBOT_DATA" bash ~/fg-bot-v2-start.sh
# 期望：入口脚本可执行，本体启动；curl -s http://127.0.0.1:17383/ 返回“机魂小悦在跑。”
# 失败：检查 ROOTFS 路径、runinc.sh 发行版别名和启动日志 ~/mmzbot-stdout.log
```

## 7. 准备 Linux arm64 QQ / NapCat 文件

NapCat 与 QQ 压缩包需由人工下载并放在 `/sdcard/Download/`。确认文件名后继续：

```bash
proot-distro login "$DISTRO" --bind /sdcard:/sdcard -- bash -lc 'uname -m && ls /sdcard/Download/linuxqq_*.deb /sdcard/Download/NapCat*.zip'
# 期望：aarch64，两个安装包都能列出
# 失败：确认设备 arm64、存储权限已授权、安装包下载完整且位于指定目录
```

```bash
proot-distro login "$DISTRO" --bind /sdcard:/sdcard -- bash -lc 'apt update && apt install -y xvfb libgbm1 libnss3 libxss1 libxtst6 fonts-noto-cjk ca-certificates unzip && if apt-cache show libasound2t64 >/dev/null 2>&1; then apt install -y libasound2t64; else apt install -y libasound2; fi && apt install -y /sdcard/Download/linuxqq_*.deb && ls -l /opt/QQ/qq'
# 期望：依赖安装完成，/opt/QQ/qq 存在
# 失败：Ubuntu 24.04 / Debian 13 用 libasound2t64；Debian 12 用 libasound2；确认 deb 架构为 arm64
```

## 8. 安装 NapCat 注入入口并启动

NapCat Shell zip 没有 Linux 启动器。必须把 NapCat 注入到 QQ 资源目录，不能直接启动裸 QQ。

```bash
proot-distro login "$DISTRO" --bind /sdcard:/sdcard -- bash -lc '
mkdir -p /opt/QQ/resources/app/napcat
unzip -o /sdcard/Download/NapCat*.zip -d /opt/QQ/resources/app/napcat
cat > /opt/QQ/resources/app/loadNapCat.cjs <<"EOF"
const path = require("path");
(async () => { await import("file://" + path.join(__dirname, "./napcat/napcat.mjs")); })();
EOF
sed -i "s#\"main\": \".*index.js\"#\"main\": \"./loadNapCat.cjs\"#" /opt/QQ/resources/app/package.json
grep -n "\"main\"" /opt/QQ/resources/app/package.json
'
# 期望：package.json 的 main 字段指向 ./loadNapCat.cjs
# 失败：检查 zip 是否完整、napcat.mjs 是否解压到资源目录；main 未变时按包内结构修正路径
```

```bash
proot-distro login "$DISTRO" -- bash -lc 'xvfb-run -a -s "-screen 0 1080x720x24" /opt/QQ/qq --no-sandbox'
# 期望：NapCat 启动并监听 3000 / 6099
# 失败：查看启动输出，核对 QQ 与 NapCat 版本以及 Xvfb / 系统依赖
```

## 9. 配好 NapCat 的网络（agent 做），然后让用户扫码

顺序不能反：NapCat 一重启就可能掉登录，所以网络配置要在扫码之前写完。

```bash
proot-distro login "$DISTRO" -- bash -lc 'cat > /root/napcat/config/onebot11_<她的QQ号>.json <<EOF
{"network":{"httpServers":[{"name":"mmzbot-http","enable":true,"host":"0.0.0.0","port":3000,"token":"'"$TOKEN"'","messagePostFormat":"array","enableCors":true}],"httpClients":[{"name":"mmzbot-report","enable":true,"url":"http://127.0.0.1:17383/","token":"'"$TOKEN"'","messagePostFormat":"array"}],"websocketServers":[],"websocketClients":[]}}
EOF'
# 期望：文件写进容器里的 NapCat config 目录；然后重开 NapCat（先杀掉再起）
# 失败：config 目录名随版本变，找不到就 ls /root/napcat 看实际结构
```

然后把二维码交给用户扫 —— 这是唯一需要他动手的地方：

```bash
proot-distro login "$DISTRO" -- bash -lc 'ls -l /root/napcat/cache/qrcode.png'
# 期望：拿到 png 的路径；把图传给用户看，同时给 WebUI 链接 http://<手机IP>:6099/webui?token=<WebUI令牌>
# 失败：二维码还没生成就等 10 秒再看；每张约两分钟过期，过期了重新看
```

对用户说的是：**用她的号扫这张图**。扫完他会说一声。

扫完再验：

```bash
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
# 期望：retcode 0，data.user_id 是她的号
# 失败：重新取二维码再扫；扫码之后再重启 NapCat 会掉登录，别重启
```

## 10. 收尾验收命令

```bash
proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --check"; RC=$?; printf 'exit=%s\n' "$RC"
curl -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
curl -s http://127.0.0.1:17383/
# 期望：--check 六项全 ✓、退出码 0；NapCat retcode 0；根路径返回“机魂小悦在跑。”
# 失败：退出码 1 检查配置 / NapCat；退出码 2 检查参数；请人到目标群发消息验证回复
```

## 运行限制与验收提醒

- `--check` 前五项检查是否填写，第六项探测 NapCat；退出码 `0/1/2` 分别表示通过、配置缺失或探测失败、参数错误。占位值 `10000`、`1234567890`、`987654321`、`sk-PLACEHOLDER…` 不通过。
- `--set` 配置热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能导致 QQ 重新登录。
- 端口 `17383` 被占用时，可在 Debian 中执行：
  ```bash
  proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --set port=17390"
  ```
  停止当前实例再启动；NapCat 上报地址改为 `http://127.0.0.1:17390/`，面板和验收地址也改用 `17390`。
- 局域网其他设备访问面板返回 `403` 时，将本机网段加入 `bot.control.allowIps`：
  ```bash
  proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --set bot.control.allowIps=192.168.1.0/24"
  ```
  不要使用 `0.0.0.0/0`；公网访问应使用带登录保护的反向代理。
- 思考强度可设置为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。例如：
  ```bash
  proot-distro login "$DISTRO" -- bash -lc "cd '$MMZBOT_DIR' && MMZBOT_DATA='$MMZBOT_DATA' python3 phone-bot-v2.py --set llm.effort=low"
  ```
  `--list-models` 会列出各模型支持的强度档位。
- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；使用 `curl` 检查时加 `-L`。二维码约两分钟刷新一次。`packetBackend` 最高支持 QQ build `36580`，超出后群文件下载不可用。
- `--selftest` 有 1155 条断言；不要让 `MMZBOT_DATA` 指向真实数据目录。

## 验收清单

- [ ] `--check` 六项全 ✓，退出码 `0`。
- [ ] NapCat `get_login_info` 返回 `retcode:0`。
- [ ] 本体根路径可访问，Termux 后台未被系统杀掉。
- [ ] 人工在目标群发消息，她能回复。
