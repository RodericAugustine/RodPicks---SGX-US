# RodPicks AutoTrader - Windows Task Scheduler Setup
# Run once as Administrator to register all automated tasks.

$Python  = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { Write-Host "Python not found." -ForegroundColor Red; pause; exit }

$Script         = "C:\Users\vibra\Claude\Projects\iNVESTMENT\rodpicks_autotrader.py"
$ReminderScript = "C:\Users\vibra\Claude\Projects\iNVESTMENT\send_reminder.py"
$Dir            = "C:\Users\vibra\Claude\Projects\iNVESTMENT"

Write-Host ""
Write-Host "Registering RodPicks AutoTrader scheduled tasks..." -ForegroundColor Cyan

# Connect to Task Scheduler via COM (works on all Windows versions)
$svc = New-Object -ComObject "Schedule.Service"
$svc.Connect()

# Create \RodPicks\ folder if it doesn't exist
$root = $svc.GetFolder("\")
try {
    $folder = $svc.GetFolder("\RodPicks")
} catch {
    $root.CreateFolder("RodPicks") | Out-Null
    $folder = $svc.GetFolder("\RodPicks")
}

function New-MonthlyTrigger($task, $Day, $Time) {
    $trigger = $task.Triggers.Create(4)  # TASK_TRIGGER_MONTHLY = 4
    $trigger.DaysOfMonth  = [int][Math]::Pow(2, $Day - 1)  # bitmask
    $trigger.MonthsOfYear = 4095  # all 12 months
    $trigger.StartBoundary = (Get-Date -Format "yyyy-MM-dd") + "T" + $Time + ":00"
    $trigger.Enabled = $true
}

function Make-Task($Name, $Days, $Time, $ScriptPath, $Args) {
    # Delete existing task
    try { $folder.DeleteTask($Name, 0) } catch {}

    $task = $svc.NewTask(0)
    $task.RegistrationInfo.Description   = "RodPicks AutoTrader: $Name"
    $task.Settings.StartWhenAvailable    = $true
    $task.Settings.RunOnlyIfNetworkAvailable = $true
    $task.Settings.ExecutionTimeLimit    = "PT2H"
    $task.Settings.MultipleInstances     = 2  # IgnoreNew
    $task.Principal.RunLevel             = 1  # Highest

    # Add one trigger per day (supports multiple days for reminder)
    foreach ($Day in $Days) {
        New-MonthlyTrigger $task $Day $Time
    }

    # Action
    $action = $task.Actions.Create(0)  # TASK_ACTION_EXEC = 0
    $action.Path             = $Python
    $action.Arguments        = "`"$ScriptPath`" $Args"
    $action.WorkingDirectory = $Dir

    # Register (6 = create or update, 3 = run whether logged in or not)
    $folder.RegisterTaskDefinition($Name, $task, 6, $null, $null, 3) | Out-Null
    Write-Host "  [OK] $Name - days $($Days -join ',') at $Time" -ForegroundColor Green
}

# Reminder fires on days 28, 30, 31 — Python script only sends email if tomorrow is the 1st
Make-Task "RodPicks-Reminder"  @(28,30,31) "09:00" $ReminderScript ""
Make-Task "RodPicks-Signal"    @(1)        "08:00" $Script "--rebalance --dry"
Make-Task "RodPicks-SGX-Trade" @(1)        "09:05" $Script "--rebalance --market SGX"
Make-Task "RodPicks-US-Trade"  @(1)        "21:35" $Script "--rebalance --market US"

Write-Host ""
Write-Host "4 tasks registered under Task Scheduler -> RodPicks\" -ForegroundColor Cyan
Write-Host "Reminder : 28th of each month at 9:00am" -ForegroundColor Cyan
Write-Host "Rebalance: 1st of each month (SGX 9:05am, US 9:35pm SGT)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Verify with:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask | Where-Object {`$_.TaskName -like 'RodPicks*'}" -ForegroundColor White
pause
