# Read only: no service/process actions, SMART self-tests, or persistent files.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$metricSource = 'wmi'
try {
    $os = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 4
    $processors = @(Get-CimInstance Win32_Processor -OperationTimeoutSec 4)
    $cores = ($processors | Measure-Object NumberOfLogicalProcessors -Sum).Sum
    $cpu = ($processors | Measure-Object LoadPercentage -Average).Average
    $disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -OperationTimeoutSec 4 | Where-Object { $_.Size -gt 0 } | ForEach-Object {
        @{ mount=$_.DeviceID; fs=$_.FileSystem; total=[long]$_.Size; free=[long]$_.FreeSpace; used=[long]($_.Size-$_.FreeSpace); percent=[math]::Round(100*($_.Size-$_.FreeSpace)/$_.Size,1) }
    })
    $total = [long]$os.TotalVisibleMemorySize * 1024
    $available = [long]$os.FreePhysicalMemory * 1024
} catch {
    # Standard users may lack WMI/performance-counter access. Read OS APIs instead;
    # never change namespace ACLs, groups or registry permissions to collect metrics.
    $metricSource = 'win32-readonly'
    if (-not ('RadarReadOnlyMetrics' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class RadarReadOnlyMetrics {
    [StructLayout(LayoutKind.Sequential)] public struct Memory {
        public uint length, load;
        public ulong total, available, pageTotal, pageAvailable, virtualTotal, virtualAvailable, extended;
    }
    [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref Memory m);
    [DllImport("kernel32.dll")] public static extern ulong GetTickCount64();
    [DllImport("kernel32.dll")] static extern bool GetSystemTimes(out long idle, out long kernel, out long user);
    public static Memory ReadMemory() {
        var m = new Memory(); m.length = (uint)Marshal.SizeOf(m);
        if (!GlobalMemoryStatusEx(ref m)) throw new InvalidOperationException("Memory metrics unavailable");
        return m;
    }
    public static double Cpu() {
        long i1,k1,u1,i2,k2,u2;
        if (!GetSystemTimes(out i1,out k1,out u1)) throw new InvalidOperationException("CPU metrics unavailable");
        System.Threading.Thread.Sleep(150); // one bounded sample, not a retry loop
        if (!GetSystemTimes(out i2,out k2,out u2)) throw new InvalidOperationException("CPU metrics unavailable");
        double elapsed = (k2-k1)+(u2-u1);
        if (elapsed <= 0) throw new InvalidOperationException("CPU sample unavailable");
        return Math.Max(0,Math.Min(100,100*(elapsed-(i2-i1))/elapsed));
    }
}
'@
    }
    $mem = [RadarReadOnlyMetrics]::ReadMemory()
    $total = [long]$mem.total
    $available = [long]$mem.available
    $cores = [Environment]::ProcessorCount
    $cpu = [RadarReadOnlyMetrics]::Cpu()
    $processors = @(@{Name=$env:PROCESSOR_IDENTIFIER})
    $os = @{Caption='Windows'; Version=[Environment]::OSVersion.Version.ToString(); LastBootUpTime=(Get-Date).AddMilliseconds(-[double][RadarReadOnlyMetrics]::GetTickCount64())}
    $disks = @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -eq 'Fixed' -and $_.TotalSize -gt 0 } | ForEach-Object {
        @{ mount=$_.Name.TrimEnd('\'); fs=$_.DriveFormat; total=[long]$_.TotalSize; free=[long]$_.AvailableFreeSpace; used=[long]($_.TotalSize-$_.AvailableFreeSpace); percent=[math]::Round(100*($_.TotalSize-$_.AvailableFreeSpace)/$_.TotalSize,1) }
    })
}
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
    platform='windows'; metricSource=$metricSource; takenAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    system=@{hostname=$env:COMPUTERNAME; os=$os.Caption; kernel=$os.Version; cpuModel=$processors[0].Name; cores=$cores; uptime=[long]((Get-Date)-$os.LastBootUpTime).TotalSeconds; bootAt=$os.LastBootUpTime.ToUniversalTime().ToString('o'); bootBrasilia=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($os.LastBootUpTime.ToUniversalTime(),'E. South America Standard Time').ToString('dd/MM/yyyy HH:mm')}
    cpu=@{percent=[math]::Round($cpu,1); cores=$cores; load=@()}
    memory=@{total=$total; used=$total-$available; available=$available; swapTotal=0; swapUsed=0}
    health=$health; disks=$disks; net=$null; processes=$null; agents=@{}; procs=@(); terminals=@(); tmux=@(); failed=@(); failedUser=@(); gpus=@(); containers=$null; temperature=$null
}
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$result | ConvertTo-Json -Depth 8 -Compress
