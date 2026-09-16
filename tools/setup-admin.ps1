$ErrorActionPreference = 'Stop'

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Este script precisa de um PowerShell ELEVADO." -ForegroundColor Red
    Write-Host "Abra o Terminal como administrador e rode de novo." -ForegroundColor Yellow
    exit 1
}

$exe = @(
    'C:\Program Files\OpenRGB\OpenRGB.exe',
    'C:\Program Files (x86)\OpenRGB\OpenRGB.exe'
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $exe) { throw "OpenRGB.exe nao encontrado." }

$name = 'Spectra - OpenRGB SDK Server'
Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$action    = New-ScheduledTaskAction -Execute $exe -Argument '--server --startminimized'
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $id.Name
$principal = New-ScheduledTaskPrincipal -UserId $id.Name -LogonType Interactive `
                                        -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
                -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description 'Servidor SDK do OpenRGB elevado, usado pelo Spectra.' | Out-Null

Write-Host "Tarefa '$name' criada." -ForegroundColor Green

Get-Process OpenRGB -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
Start-ScheduledTask -TaskName $name
Write-Host "Servidor reiniciado com privilegio maximo." -ForegroundColor Green
Write-Host "Aguarde ~20s e abra o Spectra: a RAM, o SSD e a GPU devem aparecer."
