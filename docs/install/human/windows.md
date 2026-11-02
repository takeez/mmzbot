# Windows 10/11 部署

## 适用范围

本指南适用于 Windows 10/11，介绍机魂小悦本体、`mmzbot.ps1` 启动脚本和任务计划开机启动。QQ 通道使用 Windows 版 QQ 与 NapCat；WSL、Docker 和 Android 设备请参阅对应指南。

## 准备条件

| 项目 | 要求 | 怎么确认 |
|---|---|---|
| 系统 | Windows 10 或 11，64 位 | `winver` |
| Python | 3.11+，安装时勾选 Add python.exe to PATH | `python --version` |
| 内存 / 磁盘 | 建议 4 GB 内存起；本体、数据和 NapCat/QQ 留约 1 GB 余量 | 任务管理器、资源管理器 |
| 公网 IP | 不需要。本机浏览器访问 `127.0.0.1` 即可 | — |
| 图形界面 | 需要，用于运行 Windows QQ 并扫码 | — |
| 权限 | 普通运行不用管理员；注册开机任务用管理员 PowerShell | — |
| 端口 | 机魂小悦 `17383`；NapCat API `3000`；WebUI `6099` | `netstat -ano | findstr :17383` |

Python 下载：[python.org](https://www.python.org/downloads/)。安装第一屏勾选 Add python.exe to PATH。Windows QQ 从 [QQ PC 官网](https://im.qq.com/pcqq/) 获取；NapCat Windows 包从 [NapCatQQ Releases](https://github.com/NapNeko/NapCatQQ/releases) 下载。两者版本要匹配，按 release 说明选包。

## 部署注意事项

- QQ 通道不能省。先手动登录官方 QQ，再启动 NapCat。NapCat 的 HTTP API、上报和本体的 `bot.token` 使用同一个 token。
- Python 和 NapCat 等依赖按官方发布的最新稳定版安装。NapCat 配置要重启才生效，重启可能让 QQ 掉登录；先配好网络，再扫码。

## 部署步骤

### 1. 确认 Python

在 PowerShell 运行：

```powershell
python --version
```

**预期结果：** `Python 3.11.x` 或更高。

**未通过时检查：** 如果找不到 `python`，重新安装 Python 并勾选 Add python.exe to PATH，再开一个新的 PowerShell 窗口。

### 2. 放好代码并确定数据目录

推荐代码放 `C:\opt\mmzbot`，数据放 `%LOCALAPPDATA%\MMZBOT`。把仓库目录整体复制过去，然后：

```powershell
$MMZBOT_DIR = 'C:\opt\mmzbot'
$MMZBOT_DATA = Join-Path $env:LOCALAPPDATA 'MMZBOT'
Test-Path "$MMZBOT_DIR\phone-bot-v2.py"
Test-Path "$MMZBOT_DIR\mmzbot.ps1"
```

**预期结果：** 两个 `Test-Path` 都是 `True`。

**未通过时检查：** 修改 `$MMZBOT_DIR` 指向真正包含这两个文件的目录。若用 `deploy.py` 默认把代码推到数据目录，启动脚本也要指向那份代码；别更新一份、运行另一份。

### 3. 写本体配置

先在 PowerShell 生成 token 并记下来：

```powershell
$TOKEN = [guid]::NewGuid().ToString('N')
$TOKEN
```

名称默认为 `机魂小悦`，可按需自定。`agent.name` 和 `agent.wakeWords` 中的词出现在消息开头时会唤醒机魂小悦；`agent.wakeWords` 可以留空。首次配置时请先查看 `personality.md`，确认是否需要修改；登录面板后可以继续调整。用真实 QQ 号、群号和模型密钥替换示例中的值：

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python "$MMZBOT_DIR\phone-bot-v2.py" --set `
  bot.selfId=<真实QQ号> bot.groups=<真实群号> bot.token=$TOKEN `
  agent.name=机魂小悦 agent.wakeWords=小悦 `
  napcat.baseUrl=http://127.0.0.1:3000 `
  llm.baseUrl=https://api.deepseek.com/v1 llm.model=deepseek-chat llm.apiKey=<真实模型密钥>
"exit=$LASTEXITCODE"
```

**预期结果：** `✓ 已保存（N 项），下一条消息就按新值走`，随后 `exit=0`。

**未通过时检查：** 确认 `$env:MMZBOT_DATA` 是绝对路径，并且之后 `--check`、启动脚本和任务计划都使用这个数据目录。`--set bot.token` 会同步更新 `bot.token`、`bot.napcatToken`、`napcat.token`。

### 4. 前台启动本体

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$MMZBOT_DIR\mmzbot.ps1" -DataDir "$MMZBOT_DATA" -Foreground
```

**预期结果：** 窗口开始输出日志并保持运行。另开一个 PowerShell 窗口检查：

```powershell
curl.exe -s http://127.0.0.1:17383/
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:17383/panel
```

期望根路径返回 `机魂小悦在跑。`，面板为 `200`。

**未通过时检查：** 看当前窗口的错误输出，以及 `$MMZBOT_DATA\mmzbot-stdout.log.err`。防火墙弹窗只在需要局域网访问时允许专用网络。

### 5. 安装 Windows QQ 和 NapCat

从 QQ 官网安装 Windows QQ，先手动登录一次并确认正常。随后从 NapCat Releases 下载匹配当前 QQ 版本的 Windows 包，解压到固定目录，例如 `C:\napcat`。按包内说明运行实际的 Windows 启动器；包名和启动器文件名会随 release 变化，不要猜文件名。

**预期结果：** QQ 和 NapCat 窗口正常运行。浏览器打开 `http://127.0.0.1:6099/` 可以进入 NapCat WebUI；如果要求 token，用 NapCat 启动器窗口或日志里显示的 WebUI token。

**未通过时检查：** 看启动器和 QQ 的报错，核对所选 NapCat release 支持的 QQ 版本。6099 首页会 `301` 跳转到 `/webui`；`curl` 检查时用 `curl.exe -L`。

### 6. 配置 NapCat 网络并扫码

先在 NapCat WebUI 的网络配置中加入两项。NapCat API 和 WebUI 仅供本机或可信管理网段访问，不要对公网开放：

| 项目 | 值 |
|---|---|
| HTTP 服务器 | 启用，端口 `3000`，token 填 `$TOKEN` |
| HTTP 上报 / HTTP 客户端 | 启用，地址 `http://127.0.0.1:17383/`，token 填 `$TOKEN` |

保存后重启 NapCat，再打开 WebUI 用实时二维码扫码登录。二维码约两分钟一换。

**预期结果：** 扫码后 NapCat 显示 QQ 已登录；API 的 `get_login_info` 返回 `retcode:0`。

**未通过时检查：** WebUI 配置和 NapCat 日志。先配网络再扫码；NapCat 配置不热重载，重启会让登录掉线。

### 7. 安装语义记忆依赖与模型（必需）

在运行机魂小悦的同一 Python 环境中安装依赖，并将模型文件下载到数据目录：

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python -m pip install -r "$MMZBOT_DIR\requirements.txt"
python "$MMZBOT_DIR\tools\fetch_model.py"
```

下载输出必须显示 3 个文件全部就位；模型总量约 24 MB，来源为 GitHub Release（不在 Git 仓库）。下载失败可用 `--base <镜像根地址>` 重试；依赖或模型缺失表示安装未完成。

下一步会停止前台进程并通过任务计划重新启动。启动后在 QQ 中触发一次记忆查询或写入，再检查日志：

```powershell
Select-String -Path "$MMZBOT_DATA\bot.log" -Pattern '语义召回：模型加载好了'
```

程序在依赖或模型缺失时仍可能启动，但记忆检索不可用并会退回全量记忆，增加 token 消耗。

### 8. 注册开机任务

先停止刚才前台运行的本体（在运行窗口按 `Ctrl+C`）。用管理员 PowerShell 注册任务。`-DataDir` 要指向绝对路径：

```powershell
$MMZBOT_DIR = 'C:\opt\mmzbot'
$MMZBOT_DATA = Join-Path $env:LOCALAPPDATA 'MMZBOT'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$MMZBOT_DIR\mmzbot.ps1`" -DataDir `"$MMZBOT_DATA`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'MMZBOT' -Action $action -Trigger $trigger `
  -Settings $settings -User $env:USERNAME -RunLevel Highest -Force
Start-ScheduledTask -TaskName 'MMZBOT'
Get-ScheduledTask -TaskName 'MMZBOT' | Get-ScheduledTaskInfo
```

**预期结果：** `LastTaskResult` 是 `0` 或 `267009`（任务正在运行），本体端口仍有回应。

**未通过时检查：** 检查任务 Action 是否写对脚本路径和 `-DataDir`。注册任务要管理员权限；登录账户要能访问该数据目录。

## 修改配置

第 3 步已写入基本配置。之后可在面板或通过 `--set` 修改；两者写入同一份 `local-config.json`。`--list-models` 会列出各模型支持的思考强度：

```powershell
python "$MMZBOT_DIR\phone-bot-v2.py" --list-models <地址> <密钥>
```

### 设置思考强度

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python "$MMZBOT_DIR\phone-bot-v2.py" --set llm.effort=low
```

可选值为 `none`、`low`、`medium`、`high`；未设置时默认为 `high`。强度变更在后续请求生效。

### 处理端口冲突

如果 `17383` 已被占用，可改为 `17390`：

```powershell
python "$MMZBOT_DIR\phone-bot-v2.py" --set port=17390
```

停止当前本体进程并确认端口已释放后，再通过任务计划或 `mmzbot.ps1` 重启。若由任务计划启动，需将 Action 中 `mmzbot.ps1` 的参数加入 `-Port 17390`，否则启动脚本仍会按默认 `17383` 检查运行状态。NapCat 上报地址同步改为 `http://127.0.0.1:17390/`，面板地址为 `http://127.0.0.1:17390/panel`；后续端口检查命令中的 `17383` 也应改为 `17390`。

### 允许局域网访问面板

如果同一局域网中的其他设备打开面板返回 `403`，将示例网段替换成自己的局域网 CIDR：

```powershell
python "$MMZBOT_DIR\phone-bot-v2.py" --set bot.control.allowIps=192.168.1.0/24
```

该设置仅适用于可信局域网；不要使用 `0.0.0.0/0`。公网访问应使用带登录保护的反向代理，见[反向代理说明](../../reverse-proxy.md)。

本体需要 QQ 号、共享 token、群号、模型与 API Key，以及人设正文；NapCat 的 HTTP 服务器和上报 token 必须与 `bot.token` 一致。配置通常热加载；修改 `port`、`host` 或 Python 文件后需重启本体。NapCat 配置不热加载，重启可能使 QQ 掉线，网络配置应先完成再扫码。

## 启动并验证

```powershell
$env:MMZBOT_DATA = $MMZBOT_DATA
python "$MMZBOT_DIR\phone-bot-v2.py" --check
"exit=$LASTEXITCODE"
netstat -ano | findstr :17383
curl.exe -sL -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3000/get_login_info
```

**预期结果：** `--check` 六项全 ✓，`exit=0`；NapCat 返回 `retcode:0` 和已登录 QQ 信息。任务计划中本体保持运行。最后到目标群发一句消息，确认机魂小悦能回复。

`--check` 前五项只验有没有填，第六项才实际探测 NapCat。退出码 `0` 是通过，`1` 是还缺配置或 NapCat 不通，`2` 是参数错误。

## 出问题时

| 症状 | 原因 | 怎么办 |
|---|---|---|
| PowerShell 找不到 `python` | Python 没进 PATH | 重装时勾 Add python.exe to PATH，再开新窗口 |
| `--check` 显示全 ✗，但刚才保存成功 | 检查和配置用了不同数据目录 | 设好 `$env:MMZBOT_DATA`，启动和任务都指定同一个 `-DataDir` |
| WebUI 端口通但 `--check` 报连接重置 | 3000 没启用 NapCat HTTP 服务器 | WebUI 网络配置里启用 HTTP 服务器，端口 3000 |
| API 返回 401/403 或上报鉴权失败 | NapCat token 与 `bot.token` 不同 | 两个 NapCat 网络项都改成同一 token，保存并重启 NapCat |
| 群里发消息没反应 | 上报地址、群号或登录状态不对 | 上报应为 `http://127.0.0.1:17383/`；确认群号已配置，QQ 已登录 |
| 群文件下载不可用 | QQ build 超过 `packetBackend` 支持上限 | 支持最高到 QQ build `36580`；升级 NapCat 不能解决超范围版本 |
| `--selftest` 读错配置或中途崩 | `MMZBOT_DATA` 指向真实数据目录 | 跑 1155 条自检时不要让 `MMZBOT_DATA` 指向真实数据目录 |

## 卸载与回滚

先停止开机任务，并确认机魂小悦已退出（本机 `17383` 端口不再监听）：

```powershell
Stop-ScheduledTask -TaskName 'MMZBOT' -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 17383 -State Listen -ErrorAction SilentlyContinue
```

若命令仍显示监听端口，请先在任务管理器中确认并结束机魂小悦对应的 Python 进程，再重新检查。确认端口已停止后，注销任务并备份数据：

```powershell
Unregister-ScheduledTask -TaskName 'MMZBOT' -Confirm:$false
$MMZBOT_DATA = Join-Path $env:LOCALAPPDATA 'MMZBOT'
Copy-Item -Recurse $MMZBOT_DATA "$env:USERPROFILE\Desktop\MMZBOT-backup"
```

确认备份目录和文件可读后，再删除代码和数据目录。删除数据会清掉配置、密钥和记忆；NapCat 解压目录和 QQ 按各自卸载方式处理。

回滚本体时恢复旧代码目录，保留数据目录，再启动 `mmzbot.ps1` 或任务计划。回滚 NapCat 前先备份配置；重启 NapCat 可能需要重新扫码。
