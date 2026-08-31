# Windows 版常驻服务安装器 —— 对应 macOS 的 scripts/install-launchd.sh。
#
# 三个服务与 macOS 一一对应（名字、职责、参数都保持一致，闸在 tests/test_installers_agree.py）：
#   proxy     轮换代理，常驻，崩溃自动重启
#   quotad    额度守护，常驻，崩溃自动重启
#   autosync  新号入池
#
# ★★ 与 macOS 的**三处真实差异**，都是平台限制不是偷懒：
#
# ① autosync 从「文件变化触发」降级为「每分钟轮询」。
#    launchd 的 `WatchPaths` 盯着 ~/.codex/auth.json，`codex login` 后**秒级**入池；
#    Task Scheduler **没有文件监视触发器**（要走文件系统审计事件，得开审计策略、
#    权限和噪音都不可接受）。所以改成每分钟跑一次 `codex-rotate sync`。
#    代价：新号入池最慢延迟 1 分钟，不再是秒级。`sync` 本身很便宜（读一个 json 比对）。
#
# ② 必须用 pythonw.exe 而不是 python.exe。
#    计划任务跑 python.exe 会弹一个控制台窗口 —— 常驻服务就是一个永远杵在那里的黑窗，
#    重启一次弹一次。pythonw 是无窗口版本，配合 <Hidden>true</Hidden> 才真的看不见。
#    ⚠️ 这也意味着**标准输出没有终端可去**，所以下面显式重定向到日志文件。
#
# ③ launchd 的 KeepAlive 是「退出就立刻重启」；Task Scheduler 的
#    RestartOnFailure 只在**非零退出码**时触发，且有次数上限。已设成 1 分钟间隔 ×
#    999 次（约 16 小时的连续崩溃才耗尽），并额外挂一个每 5 分钟的补拉触发器兜底。
#
# 用法（普通用户权限即可，任务装在当前用户下）：
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Uninstall

param([switch]$Uninstall)

$ErrorActionPreference = "Stop"

$Repo   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Prefix = "com.doushutangmu.codex-rotate"
$LogDir = Join-Path $env:LOCALAPPDATA "CodexBar\logs"

# ---- 解释器 ----------------------------------------------------------------
# ★ Windows 版 CPython 链的是 OpenSSL，**不存在** macOS 上那个 LibreSSL 被 Cloudflare
#   按 TLS 指纹拦成 403 的问题，所以这里不做 OpenSSL 校验（macOS 那份必须做）。
#   要校验的是另一件事：pythonw 真的存在且能跑 —— `python.exe` 在未安装 Python 时
#   是应用商店的占位存根，存在、能启动、什么都不做。
function Find-Pythonw {
    foreach ($c in @("pythonw.exe", "pythonw3.exe")) {
        $p = (Get-Command $c -ErrorAction SilentlyContinue)
        if ($p) { return $p.Source }
    }
    # py 启动器：问它 python.exe 在哪，再换成同目录的 pythonw.exe
    $py = (Get-Command "py.exe" -ErrorAction SilentlyContinue)
    if ($py) {
        $exe = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            $w = Join-Path (Split-Path $exe) "pythonw.exe"
            if (Test-Path $w) { return $w }
        }
    }
    return $null
}

if ($Uninstall) {
    foreach ($n in @("proxy", "quotad", "autosync")) {
        schtasks /Delete /TN "$Prefix.$n" /F 2>$null | Out-Null
        Write-Host "  x $n"
    }
    Write-Host "`n已卸载。数据(state.json / auth/)未删除。"
    exit 0
}

$Pythonw = Find-Pythonw
if (-not $Pythonw) {
    Write-Error @"
找不到 pythonw.exe。

请安装 Python 3.9+ (https://www.python.org/downloads/) 并勾选 "Add python.exe to PATH"。
⚠️ 不要依赖 Microsoft Store 那个 python.exe 占位存根 —— 它存在、能启动、但什么都不做，
   症状是每条命令都返回空输出，看起来像"没有数据"而不是"没装 Python"。
"@
    exit 1
}
# 真的跑一次，排除占位存根
$ver = & $Pythonw -c "import sys;print(sys.version_info[:2])" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "pythonw 跑不起来: $Pythonw"
    exit 1
}
Write-Host "==> 解释器: $Pythonw"
Write-Host "==> 仓库:   $Repo"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ---- 任务 XML --------------------------------------------------------------
function New-TaskXml {
    param(
        [string]$Name,
        [string[]]$ScriptArgs,   # 传给 pythonw 的参数
        [string]$Trigger,        # 触发器 XML
        [hashtable]$Env = @{}
    )
    $log = Join-Path $LogDir "$Name.log"
    # 输出没有终端可去（pythonw 无控制台），显式重定向；用 cmd /c 才能做重定向。
    $inner = ($ScriptArgs | ForEach-Object { '"' + $_ + '"' }) -join " "
    $envPrefix = ($Env.GetEnumerator() | ForEach-Object { "set $($_.Key)=$($_.Value)&& " }) -join ""
    # ★ 强制 UTF-8：Windows 上 Python 的 stdout 默认是本地代码页，日志里的中文会变乱码
    #   （与 app 内 spawn_cmd 那条同源，那边是 Rust 读 stdout，这边是写日志文件）。
    $envPrefix = "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& " + $envPrefix
    $cmd = "$envPrefix`"$Pythonw`" $inner >> `"$log`" 2>&1"

    @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>CodexBar $Name (mirrors the macOS launchd service of the same name)</Description>
  </RegistrationInfo>
  <Triggers>
$Trigger
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c $([System.Security.SecurityElement]::Escape($cmd))</Arguments>
      <WorkingDirectory>$Repo</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

# 登录即起 + 每 5 分钟补拉一次（RestartOnFailure 只认非零退出码，这条兜底"进程没了但退出码是 0"）
$PersistentTrigger = @"
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
"@

# autosync：launchd 那边是文件变化触发，这里只能每分钟轮询（见文件头 ①）
$PollTrigger = @"
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
    <TimeTrigger>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
"@

$tasks = @(
    @{ Name = "proxy";    Args = @((Join-Path $Repo "proxy\proxy.py"));        Trig = $PersistentTrigger; Env = @{ CRP_PORT = "8011" } },
    @{ Name = "quotad";   Args = @((Join-Path $Repo "daemon\quota_daemon.py")); Trig = $PersistentTrigger; Env = @{} },
    @{ Name = "autosync"; Args = @((Join-Path $Repo "codex-rotate"), "sync");   Trig = $PollTrigger;       Env = @{} }
)

foreach ($t in $tasks) {
    $xml  = New-TaskXml -Name $t.Name -ScriptArgs $t.Args -Trigger $t.Trig -Env $t.Env
    $tmp  = Join-Path $env:TEMP "codexbar-$($t.Name).xml"
    # Task Scheduler 要求 UTF-16
    [System.IO.File]::WriteAllText($tmp, $xml, [System.Text.Encoding]::Unicode)
    schtasks /Delete /TN "$Prefix.$($t.Name)" /F 2>$null | Out-Null
    schtasks /Create /TN "$Prefix.$($t.Name)" /XML $tmp | Out-Null
    Remove-Item $tmp -Force
    schtasks /Run /TN "$Prefix.$($t.Name)" 2>$null | Out-Null
    Write-Host "  + $($t.Name)"
}

Write-Host "`n==> 已注册:"
foreach ($t in $tasks) {
    $s = (schtasks /Query /TN "$Prefix.$($t.Name)" /FO LIST 2>$null | Select-String "^Status:").ToString()
    Write-Host ("  {0,-10} {1}" -f $t.Name, $s.Trim())
}
Write-Host @"

日志: $LogDir
停止: powershell -File scripts\install-windows.ps1 -Uninstall

⚠️ 与 macOS 的差异（不是 bug，是平台限制）：
   · autosync 是**每分钟轮询**而不是文件变化即触发 —— 新号入池最慢延迟 1 分钟。
   · 进程被非零退出码以外的方式终止时，靠每 5 分钟那条补拉触发器恢复，不是立刻。
"@
