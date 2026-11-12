# Read only: no service/process actions, SMART self-tests, or persistent files.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$os = Get-CimInstance Win32_OperatingSystem
$processors = @(Get-CimInstance Win32_Processor)
$cores = ($processors | Measure-Object NumberOfLogicalProcessors -Sum).Sum
$cpu = ($processors | Measure-Object LoadPercentage -Average).Average
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.Size -gt 0 } | ForEach-Object {
    @{ mount=$_.DeviceID; fs=$_.FileSystem; total=[long]$_.Size; free=[long]$_.FreeSpace; used=[long]($_.Size-$_.FreeSpace); percent=[math]::Round(100*($_.Size-$_.FreeSpace)/$_.Size,1) }
})
$total = [long]$os.TotalVisibleMemorySize * 1024
$available = [long]$os.FreePhysicalMemory * 1024
$health = @{ smart199=@(); smartAvailable=$false; unexpectedShutdowns=@(); eventsAvailable=$false; eventWindowDays=30 }
try {
    $health.smart199 = @(Get-CimInstance -Namespace root/wmi -ClassName MSStorageDriver_FailurePredictData -OperationTimeoutSec 4 | ForEach-Object {
        $bytes = $_.VendorSpecific
        for ($offset=2; $offset+11 -lt $bytes.Length; $offset+=12) {
            if ($bytes[$offset] -eq 199) {
                [uint64]$raw=0
                for ($j=0; $j -lt 6; $j++) { $raw=$raw -bor ([uint64]$bytes[$offset+5+$j] -shl (8*$j)) }
                @{disk=$_.InstanceName; raw=$raw}
            }
        }
    })
    $health.smartAvailable = $health.smart199.Count -gt 0
} catch { } # Unsupported/denied is unknown, never zero errors.
try {
    # Bounded query: at most 10 events, last 30 days. No event message/customer data.
    $query = '*[System[(EventID=41 or EventID=6008) and TimeCreated[timediff(@SystemTime) <= 2592000000]]]'
    $health.unexpectedShutdowns = @(Get-WinEvent -LogName System -FilterXPath $query -MaxEvents 10 -ErrorAction Stop | ForEach-Object {
        @{id=$_.Id; at=$_.TimeCreated.ToUniversalTime().ToString('o'); atBrasilia=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($_.TimeCreated.ToUniversalTime(),'E. South America Standard Time').ToString('dd/MM/yyyy HH:mm'); provider=$_.ProviderName}
    })
    $health.eventsAvailable = $true
} catch {
    if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $health.eventsAvailable = $true }
}
$result = @{
    platform='windows'; takenAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    system=@{hostname=$env:COMPUTERNAME; os=$os.Caption; kernel=$os.Version; cpuModel=$processors[0].Name; cores=$cores; uptime=[long]((Get-Date)-$os.LastBootUpTime).TotalSeconds; bootAt=$os.LastBootUpTime.ToUniversalTime().ToString('o'); bootBrasilia=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($os.LastBootUpTime.ToUniversalTime(),'E. South America Standard Time').ToString('dd/MM/yyyy HH:mm')}
    cpu=@{percent=[math]::Round($cpu,1); cores=$cores; load=@()}
    memory=@{total=$total; used=$total-$available; available=$available; swapTotal=0; swapUsed=0}
    health=$health; disks=$disks; net=$null; processes=$null; agents=@{}; procs=@(); terminals=@(); tmux=@(); failed=@(); failedUser=@(); gpus=@(); containers=$null; temperature=$null
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$result | ConvertTo-Json -Depth 8 -Compress
