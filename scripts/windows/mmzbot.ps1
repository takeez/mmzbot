<#
.SYNOPSIS
  启动 MMZBOT（Windows 原生）。

.DESCRIPTION
  数据目录：-DataDir 参数 > 环境变量 MMZBOT_DATA > %LOCALAPPDATA%\MMZBOT
  代码目录：这个脚本所在的目录（把仓库 / 解压出来的目录放哪都行）。

  已经在跑（端口通）就不重复启动。日志：
    <数据目录>\bot.log         程序自己写的（她说话、工具调用都在这）
    <数据目录>\mmzbot-stdout.log  控制台输出 / traceback（排错先看这个）

.PARAMETER DataDir
  数据目录。不给就用 %LOCALAPPDATA%\MMZBOT。

.PARAMETER Port
  只用来判断"是不是已经在跑"（默认读 $env:MMZBOT_PORT 或者 17383）。

.PARAMETER Foreground
  前台跑（调试用，Ctrl+C 结束）。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File C:\opt\mmzbot\mmzbot.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\mmzbot.ps1 -DataDir D:\mmzbot-data -Foreground
#>
param(
    [string]$DataDir = "",
    [int]$Port = 0,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $DataDir) { $DataDir = $env:MMZBOT_DATA }
if (-not $DataDir) { $DataDir = Join-Path $env:LOCALAPPDATA "MMZBOT" }
$DataDir = [System.IO.Path]::GetFullPath($DataDir)
$env:MMZBOT_DATA = $DataDir
if (-not $env:MMZBOT_TZ) { $env:MMZBOT_TZ = "Asia/Shanghai" }

if (-not $Port) {
    if ($env:MMZBOT_PORT) { $Port = [int]$env:MMZBOT_PORT } else { $Port = 17383 }
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "✗ 找不到 python。装 Python 3.11+（装的时候勾选 Add to PATH）。" -ForegroundColor Red
    exit 1
}

function Test-Port([int]$p) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $p)
        $c.Close()
        return $true
    } catch { return $false }
}

if (Test-Port $Port) {
    Write-Host "✓ 她已经在跑（端口 $Port 通），不重复启动。"
    Write-Host "  数据目录：$DataDir"
    exit 0
}

$stdout = Join-Path $DataDir "mmzbot-stdout.log"
if (Test-Path $stdout) {
    $len = (Get-Item $stdout).Length
    if ($len -gt 1MB) { Move-Item -Force $stdout "$stdout.1" }
}

$pyPath = $py.Source
Write-Host "启动 MMZBOT"
Write-Host "  代码目录：$root"
Write-Host "  数据目录：$DataDir"
Write-Host "  解释器：  $pyPath"
Write-Host "  端口：    $Port"

if ($Foreground) {
    Set-Location $root
    & $pyPath "phone-bot-v2.py"
    exit $LASTEXITCODE
}

# 后台跑：标准输出/错误重定向到数据目录（她自己的 bot.log 也在那儿）
$proc = Start-Process -FilePath $pyPath -ArgumentList "phone-bot-v2.py" `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError "$stdout.err" -PassThru
Start-Sleep -Seconds 3
if ($proc.HasExited) {
    Write-Host "✗ 起来就退了（退出码 $($proc.ExitCode)）。看：" -ForegroundColor Red
    Write-Host "    $stdout.err"
    exit 1
}
Set-Content -Path (Join-Path $DataDir "mmzbot.pid") -Value $proc.Id -Encoding ascii
Write-Host "✓ 已启动（PID $($proc.Id)）"
Write-Host "  日志：$stdout"
Write-Host "  面板：http://127.0.0.1:$Port/panel"
