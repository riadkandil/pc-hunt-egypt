# Registers (or updates) the Windows task "PC Hunt daily scrape": every day at 06:00, also runs later if the PC was off.
# Remove it with:  Unregister-ScheduledTask -TaskName "PC Hunt daily scrape" -Confirm:$false
param([string]$At = "06:00")
$cmd = Join-Path $PSScriptRoot "daily_scrape.cmd"
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot "data\logs") | Out-Null
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$cmd`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "PC Hunt daily scrape" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Scrapes every Egyptian PC store into egypt_pc_stores\data\pchunt.db" -Force | Out-Null
Get-ScheduledTask -TaskName "PC Hunt daily scrape" | Select-Object TaskName, State,
    @{n = "Next run"; e = { (Get-ScheduledTaskInfo $_).NextRunTime } }
