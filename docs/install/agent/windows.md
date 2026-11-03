# Agent 步骤：Windows 10/11

## 0. 变量

在 PowerShell 中填实际路径和账号。把样例身份与密钥改成真实值。

```powershell
$MMZBOT_DIR = 'C:\opt\mmzbot'
$MMZBOT_DATA = Join-Path $env:LOCALAPPDATA 'MMZBOT'
$SELFID = '填真实QQ号'; $GROUP = '填真实群号'; $LLMKEY = '填真实模型密钥'
$BOTNAME = '机魂小悦'; $WAKEWORDS = '小悦'
$TOKEN = [guid]::NewGuid().ToString('N'); $LLMBASE = 'https://api.deepseek.com/v1'; $LLMMODEL = 'deepseek-chat'
$env:MMZBOT_DATA = $MMZBOT_DATA; $TOKEN
# 期望：输出一串随机 token；目录为绝对路径，账号和密钥为真实值
# 失败：如果 $env:LOCALAPPDATA 为空，使用可写的绝对数据目录并同步更新所有步骤
```

## 1. 检查 Python

```powershell
python --version
# 期望：Python 3.11 或更高
# 失败：安装 Python 时勾选 Add python.exe to PATH，再启动新 PowerShell
```

## 2. 检查代码目录

```powershell
Test-Path "$MMZBOT_DIR\phone-bot-v2.py"; Test-Path "$MMZBOT_DIR\mmzbot.ps1"
# 期望：两项均为 True
# 失败：将仓库整体放入目录，或修正 $MMZBOT_DIR 指向实际代码目录
```

## 3. 确认初始配置（这一步集中询问，不猜值）

先读取 `$MMZBOT_DIR\personality.md`，把全文展示给用户并询问是否想调整。不要直接修改人格文件；用户可以在安装后的面板中自行编辑。

一次询问以下信息：

1. 名称：默认 `机魂小悦`，可自定义，写入 `agent.name`。
2. 唤醒词：写入 `agent.wakeWords`；名称或唤醒词出现在消息开头时会唤醒机魂小悦回复。默认唤醒词为 `小悦`，可提供多个，也可以留空。
3. 她的 QQ 号（小号，别用常用的）。
4. 目标群号（该群要已包含机器人 QQ 号）。
5. 模型 API Key。
6. 模型：取得 Key 后运行下方 `--list-models` 查询可用模型和思考强度，再让用户选择。

```powershell
python "$MMZBOT_DIR\phone-bot-v2.py" --list-models <接口地址> <模型密钥>
# 期望：列出模型 id，每个后面跟着它能用的思考强度；最后一行给可选强度
# 失败：这家不是 OpenAI 兼容接口（/models 没开），让用户直接给模型名
```

记录面板地址 `http://127.0.0.1:17383/panel` 和共享令牌 `$TOKEN`。服务启动、NapCat 登录及群内回复验收通过后，按 Agent 安装入口的面板登录流程打开面板并粘贴令牌；若当前会话不能控制浏览器，则私下引导用户打开并粘贴。不要在群聊中发送令牌。

面板可管理初始化、设置、扩展包及其他配置。性格文件位于数据目录 `personality.md`；用户可在面板中修改，或通过 `--persona-file <文件>` 指定。首次启动前使用代码目录中的默认文件。

## 4. 写入本体配置（用第 3 步要来的值）
```powershell
python "$MMZBOT_DIR\phone-bot-v2.py" --set "bot.selfId=$SELFID" "bot.groups=$GROUP" "bot.token=$TOKEN" "agent.name=$BOTNAME" "agent.wakeWords=$WAKEWORDS" 'napcat.baseUrl=http://127.0.0.1:3000' "llm.baseUrl=$LLMBASE" "llm.model=$LLMMODEL" "llm.apiKey=$LLMKEY"
"exit=$LASTEXITCODE"
# 期望：出现“✓ 已保存”，exit=0；bot.token 同步写入 NapCat token 字段
# 失败：确认数据目录、键名、真实 QQ 号/群号/密钥；占位值不能用于验收
```

## 4.1 可选：配置增强网页搜索

推荐配置百度千帆搜索 API Key；未配置时将使用必应 RSS，搜索能力可能有所下降。将 `<搜索服务API密钥>` 替换为实际密钥：

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python "$MMZBOT_DIR\phone-bot-v2.py" --set "search.apiKey=<搜索服务API密钥>"
"exit=$LASTEXITCODE"
# 期望：出现“✓ 已保存（1 项）”，exit=0
# 失败：确认使用与本体配置相同的 Python、数据目录和密钥
```

## 4.2 安装语义记忆依赖与模型（必需）

在运行 MMZBOT 的同一 Python 环境中安装依赖，并下载模型到数据目录：

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python -m pip install -r "$MMZBOT_DIR\requirements.txt"
python "$MMZBOT_DIR\tools\fetch_model.py"
```

必须确认下载脚本显示 3 个文件全部就位。模型约 24 MB，来自 GitHub Release；失败时可用 `--base <镜像根地址>` 重试。依赖或模型缺失表示安装未完成。

首次启动后，在 QQ 中触发一次记忆查询或写入，再检查 `$MMZBOT_DATA\bot.log` 是否出现 `语义召回：模型加载好了`。模型未安装时程序仍可能运行，但记忆检索不可用，会退回全量记忆并增加 token 消耗。

## 5. 启动本体

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$MMZBOT_DIR\mmzbot.ps1" -DataDir "$MMZBOT_DATA"
# 期望：脚本后台启动本体并返回；下一步查询根路径返回 机魂小悦在跑。
# 失败：检查 $MMZBOT_DATA\mmzbot-stdout.log.err、Python PATH 与目录权限
```

## 6. 检查本体 HTTP

```powershell
curl.exe -s http://127.0.0.1:17383/; curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:17383/panel
# 期望：根路径为“机魂小悦在跑。”，面板 HTTP 200
# 失败：检查 $MMZBOT_DATA\mmzbot-stdout.log.err；确认 17383 未被占用且脚本选中的代码目录正确
```

## 7. QQ 与 NapCat：agent 配网络，最后让用户扫码

Windows 上 QQ 必须是人登录的（扫码或账号密码），agent 替不了：

```powershell
Get-Process QQ -ErrorAction SilentlyContinue | Select-Object -First 1 Id, MainWindowTitle
# 期望：能看到 QQ 进程和窗口标题 → 说明用户已经登录
# 失败：先让用户打开 QQ 登录（这一步停下来等他），登录完再往下走
```

用户登录后，起 NapCat（用 release 里的启动器，它会注入到已运行的 QQ）：

```powershell
Start-Process "$NAPCAT_DIR\NapCatWinBootMain.exe"
Start-Sleep -Seconds 20
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:6099/
# 期望：301 或 200（301 是跳到 /webui，正常）；3000 这会儿还不通是正常的
# 失败：看 NapCat 目录里的 napcat.out.log；QQ 和 NapCat 版本不匹配时注入不进
```

然后 agent 直接写 NapCat 的网络配置，再重启 NapCat：

```powershell
$cfg = @'
{"network":{"httpServers":[{"name":"mmzbot-http","enable":true,"host":"0.0.0.0","port":3000,"token":"<TOKEN>","messagePostFormat":"array","enableCors":true}],"httpClients":[{"name":"mmzbot-report","enable":true,"url":"http://127.0.0.1:17383/","token":"<TOKEN>","messagePostFormat":"array"}],"websocketServers":[],"websocketClients":[]}}
'@
Set-Content -Path "$NAPCAT_DIR\config\onebot11_<她的QQ号>.json" -Value $cfg -Encoding UTF8
# 期望：文件写进去；接着重开 NapCat 启动器（先关掉旧窗口）
# 失败：目录不对时找 NapCat 目录下的 config\ 子目录；文件名里的 QQ 号必须对
```

最后把二维码交给用户 —— 这是唯一需要他动手的一步：

```powershell
curl.exe -sL -o "$env:TEMP\qrcode.png" "http://127.0.0.1:6099/webui?token=<WebUI令牌>"
# 期望：浏览器里能看到的实时二维码；把窗口给他扫，或直接把图打开给他
# 失败：6099 没起来说明 NapCat 没注入成功；二维码约两分钟换一张，过期重新打开
```

扫完再验：

```powershell
curl.exe -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
# 期望：retcode 0，data.user_id 是她的号
# 失败：重新扫码；扫码之后别重启 NapCat，会掉登录
```

## 8. 管理员 PowerShell 注册任务

若有遗留的试运行进程，先停止本体；再以管理员身份运行：

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$MMZBOT_DIR\mmzbot.ps1`" -DataDir `"$MMZBOT_DATA`""
$trigger = New-ScheduledTaskTrigger -AtStartup; $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'MMZBOT' -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -RunLevel Highest -Force; Start-ScheduledTask -TaskName 'MMZBOT'
Get-ScheduledTask -TaskName 'MMZBOT' | Get-ScheduledTaskInfo
# 期望：任务存在，LastTaskResult 为 0 或 267009；-DataDir 是绝对路径
# 失败：确认管理员权限、Action 路径、任务运行账户与数据目录访问权
```

## 9. 收尾验收命令

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA; python "$MMZBOT_DIR\phone-bot-v2.py" --check; "exit=$LASTEXITCODE"
curl.exe -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
Get-ScheduledTask -TaskName 'MMZBOT' | Get-ScheduledTaskInfo; netstat -ano | findstr :17383
# 期望：--check 六项全 ✓ 且退出码 0；NapCat retcode 0；任务运行且 17383 LISTENING
# 失败：退出码 1 检查配置或 NapCat；退出码 2 检查参数；人工在目标群发消息确认实际回复
```

## 运行限制与验收提醒

- `--check` 前五项检查是否填写，第六项探测 NapCat；退出码 `0` 表示通过、`1` 表示配置缺失或探测失败、`2` 表示参数错误。`10000`、`1234567890`、`987654321`、`sk-PLACEHOLDER…` 等占位值不通过。
- 配置、检查和任务必须使用同一 `MMZBOT_DATA`。任务计划不会继承当前 PowerShell 的临时环境，必须通过 `-DataDir` 指定数据目录。
- `--set` 配置热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能导致 QQ 重新登录。
- 端口 `17383` 被占用时，可改为 `17390`：
  ```powershell
  $env:MMZBOT_DATA = $MMZBOT_DATA
  python "$MMZBOT_DIR\phone-bot-v2.py" --set port=17390
  ```
  停止当前本体后再启动；计划任务调用 `mmzbot.ps1` 时需将 `-Port` 参数同步改为 `17390`。NapCat 上报地址改为 `http://127.0.0.1:17390/`，面板地址改为 `http://127.0.0.1:17390/panel`；后续端口检查命令中的 `17383` 也应改为 `17390`。
- 局域网其他设备访问面板返回 `403` 时，将本机网段加入白名单：
  ```powershell
  $env:MMZBOT_DATA = $MMZBOT_DATA
  python "$MMZBOT_DIR\phone-bot-v2.py" --set bot.control.allowIps=192.168.1.0/24
  ```
  不要使用 `0.0.0.0/0`；公网访问应使用带登录保护的反向代理。
- 思考强度可设置为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。例如：
  ```powershell
  $env:MMZBOT_DATA = $MMZBOT_DATA
  python "$MMZBOT_DIR\phone-bot-v2.py" --set llm.effort=low
  ```
  `--list-models` 会列出各模型支持的强度档位。
- NapCat WebUI 的 `6099/` 会重定向到 `/webui`；使用 `curl` 检查时加 `-L`。二维码约两分钟刷新一次。`packetBackend` 最高支持 QQ build `36580`，超出后群文件下载不可用。
- `--selftest` 有 1155 条断言；不要让 `MMZBOT_DATA` 指向真实数据目录。

## 验收清单

- [ ] `--check` 六项全 ✓，退出码 `0`。
- [ ] NapCat `get_login_info` 返回 `retcode:0`。
- [ ] MMZBOT 任务运行，17383 正在监听。
- [ ] 人工在目标群发消息，她能回复。
