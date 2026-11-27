param(
    [string]$TaskName = "ReliabilityAgent",
    [string]$Time = "08:00",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已删除计划任务: $TaskName"
    exit 0
}

$bat = Join-Path $root "run_once.bat"
if (-not (Test-Path $bat)) {
    throw "找不到 $bat"
}

$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$description = "可靠性分析自动化：同步飞书多维表格数据、执行分析、生成 Excel 并回写飞书表格"

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Description $description -Force | Out-Null

Write-Host "已注册 Windows 计划任务: $TaskName"
Write-Host "执行时间: 每天 $Time"
Write-Host "执行脚本: $bat"
Write-Host "提示: 需要以管理员身份运行 PowerShell；如需开机即跑可再加 -Trigger (New-ScheduledTaskTrigger -AtStartup)"
