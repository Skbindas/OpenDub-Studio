param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$LogPath
)

$Host.UI.RawUI.WindowTitle = 'OpenDub - Live Dubbing Progress'
$progressPath = Join-Path $ProjectRoot 'work_progress.json'
$statusPath = Join-Path $ProjectRoot 'auto_dub_status.json'
while ($true) {
    try {
        $work = Get-Content -LiteralPath $progressPath -Raw -ErrorAction Stop | ConvertFrom-Json
        $state = Get-Content -LiteralPath $statusPath -Raw -ErrorAction Stop | ConvertFrom-Json
        Clear-Host
        Write-Host 'OpenDub | test 2 | LIVE PROGRESS' -ForegroundColor Cyan
        Write-Host ('Updated: ' + (Get-Date -Format 'HH:mm:ss'))
        Write-Host ''
        Write-Host ('Project status: ' + $state.status)
        Write-Host ('Current phase:  ' + $work.phase)
        Write-Host ('Completed:      ' + $work.completed + ' / ' + $work.total + ' ' + $work.unit) -ForegroundColor Green
        Write-Host ('Remaining:      ' + $work.remaining) -ForegroundColor Yellow
        if ($work.total -gt 0) {
            Write-Host ('Phase progress: ' + [math]::Round(100 * $work.completed / $work.total, 1) + '%')
        }
        if ($null -ne $work.eta_seconds -and $work.eta_seconds -gt 0) {
            $estimate = [TimeSpan]::FromSeconds([double]$work.eta_seconds)
            Write-Host ('Estimated time for this phase: ' + $estimate.ToString('hh\:mm\:ss') + ' (changes as work progresses)')
        }
        if ($state.error) { Write-Host ('Error: ' + $state.error) -ForegroundColor Red }
        Write-Host ''
        Write-Host 'Recent worker output:' -ForegroundColor Cyan
        Get-Content -LiteralPath $LogPath -Tail 8 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        Write-Host ''
        Write-Host 'Refreshes every 2 seconds. Closing this monitor does not stop dubbing.' -ForegroundColor DarkGray
    } catch {
        Write-Host ('Waiting for progress update: ' + $_.Exception.Message) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 2
}
