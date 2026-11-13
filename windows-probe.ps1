$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
$processors = @(Get-CimInstance Win32_Processor)
$cores = ($processors | Measure-Object NumberOfLogicalProcessors -Sum).Sum
$cpu = ($processors | Measure-Object LoadPercentage -Average).Average
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object { $_.Size -gt 0 } | ForEach-Object {
    @{ mount=$_.DeviceID; fs=$_.FileSystem; total=[long]$_.Size; free=[long]$_.FreeSpace; used=[long]($_.Size-$_.FreeSpace); percent=[math]::Round(100*($_.Size-$_.FreeSpace)/$_.Size,1) }
})
$total = [long]$os.TotalVisibleMemorySize * 1024
$available = [long]$os.FreePhysicalMemory * 1024
$result = @{
    platform='windows'; takenAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    system=@{hostname=$env:COMPUTERNAME; os=$os.Caption; kernel=$os.Version; cpuModel=$processors[0].Name; cores=$cores; uptime=[long]((Get-Date)-$os.LastBootUpTime).TotalSeconds}
    cpu=@{percent=[math]::Round($cpu,1); cores=$cores; load=@()}
    memory=@{total=$total; used=$total-$available; available=$available; swapTotal=0; swapUsed=0}
    disks=$disks; net=$null; processes=$null; agents=@{}; procs=@(); terminals=@(); tmux=@(); failed=@(); failedUser=@(); gpus=@(); containers=$null; temperature=$null
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$result | ConvertTo-Json -Depth 8 -Compress
