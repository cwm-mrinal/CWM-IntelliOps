system_command = """
# Enhanced Windows System Diagnostics Script

function Print-Header {
    param ([string]$title)
    Write-Host "`n===== $title =====`n" -ForegroundColor Cyan
}

# OS Info
Print-Header "OPERATING SYSTEM"
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsArchitecture | Format-Table -AutoSize

# Uptime
Print-Header "SYSTEM UPTIME"
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$uptime = (Get-Date) - $bootTime
[PSCustomObject]@{
    'Last Boot Time' = $bootTime
    'Uptime (Days)'  = [math]::Round($uptime.TotalDays, 2)
} | Format-Table -AutoSize

# CPU Info with Usage
Print-Header "CPU INFO"
$cpu = Get-CimInstance Win32_Processor
$cpuUsage = (Get-Counter "\Processor(_Total)\% Processor Time" -SampleInterval 1 -MaxSamples 2 | Select-Object -ExpandProperty CounterSamples | Select-Object -Last 1).CookedValue
$cpu | Select-Object Name, NumberOfCores, @{Name='Usage%';Expression={[math]::Round(100-$cpuUsage,2)}} | Format-Table -AutoSize

# Memory Usage
Print-Header "MEMORY USAGE"
$os = Get-CimInstance Win32_OperatingSystem
$totalMemoryGB = [math]::Round($os.TotalVisibleMemorySize/1MB, 2)
$freeMemoryGB = [math]::Round($os.FreePhysicalMemory/1MB, 2)
$usedMemoryGB = [math]::Round($totalMemoryGB - $freeMemoryGB, 2)
$memoryUsagePercent = [math]::Round(($usedMemoryGB / $totalMemoryGB) * 100, 2)

[PSCustomObject]@{
    'Total Memory (GB)' = $totalMemoryGB
    'Used Memory (GB)'  = $usedMemoryGB
    'Free Memory (GB)'  = $freeMemoryGB
    'Usage %'           = $memoryUsagePercent
} | Format-Table -AutoSize

# Top-Level Disk Usage
Print-Header "DISK USAGE (Top Folders)"
Get-ChildItem "C:\" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $size = (Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if (-not $size) { $size = 0 }
    [PSCustomObject]@{Folder=$_.Name; SizeMB=[math]::Round($size/1MB,1)}
} | Sort-Object SizeMB -Descending | Select-Object -First 5 | Format-Table -AutoSize

# Filesystem usage summary with usage percentages
Print-Header "FILESYSTEM USAGE"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID, 
    @{Name='Size(GB)';Expression={[math]::Round($_.Size/1GB,2)}}, 
    @{Name='Free(GB)';Expression={[math]::Round($_.FreeSpace/1GB,2)}},
    @{Name='Used%';Expression={[math]::Round((($_.Size - $_.FreeSpace) / $_.Size) * 100, 2)}} | Format-Table -AutoSize

# Top CPU Processes with CPU percentage
Print-Header "TOP CPU PROCESSES"
Get-Process | Where-Object {$_.CPU -gt 0} | Sort-Object CPU -Descending | Select-Object -First 5 Name, Id, 
    @{Name='CPU Time';Expression={[math]::Round($_.CPU,2)}},
    @{Name='CPU%';Expression={
        $proc = $_
        try {
            $cpuPercent = (Get-Counter "\Process($($proc.Name))\% Processor Time" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples).CookedValue
            if ($cpuPercent) { [math]::Round($cpuPercent, 2) } else { "N/A" }
        } catch { "N/A" }
    }} | Format-Table -AutoSize

# Top Memory Processes with memory percentage
Print-Header "TOP MEMORY PROCESSES"
$totalMemoryBytes = (Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize * 1KB
Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 5 Name, Id, 
    @{Name='MemoryMB';Expression={[math]::Round($_.WorkingSet/1MB,1)}},
    @{Name='Memory%';Expression={[math]::Round(($_.WorkingSet / $totalMemoryBytes) * 100, 2)}} | Format-Table -AutoSize

# System Performance Summary
Print-Header "SYSTEM PERFORMANCE SUMMARY"
$allDrives = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"
$driveUsageString = ($allDrives | ForEach-Object { 
    "$($_.DeviceID) $([math]::Round((($_.Size - $_.FreeSpace) / $_.Size) * 100, 2))%" 
}) -join ", "

[PSCustomObject]@{
    'CPU Usage %'     = [math]::Round(100-$cpuUsage,2)
    'Memory Usage %'  = $memoryUsagePercent
    'All Drives Usage' = $driveUsageString
} | Format-Table -AutoSize

# End Marker
Print-Header "END OF ENHANCED REPORT"
"""