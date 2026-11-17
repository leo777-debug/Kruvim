# A loopback-only static server for the separate verification artifact. No uploads,
# package installs, account changes, administrator access or cloud deployment.
$ErrorActionPreference = 'Stop'
$localRoot = [IO.Path]::GetFullPath($PSScriptRoot)
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class KruvimHardware {
 [StructLayout(LayoutKind.Sequential)] public struct Memory {public uint length;public uint load;public ulong totalPhys,availPhys,totalPage,availPage,totalVirtual,availVirtual,availExtended;}
 [DllImport("kernel32.dll", SetLastError=true)] static extern bool GlobalMemoryStatusEx(ref Memory m);
 public static ulong Total() {Memory m=new Memory();m.length=(uint)Marshal.SizeOf(typeof(Memory));if(!GlobalMemoryStatusEx(ref m))throw new Exception("Unable to read physical memory");return m.totalPhys;}
}
'@
$localHardware = @{ physicalMemoryBytes = [KruvimHardware]::Total(); operatingSystem = [Environment]::OSVersion.VersionString; measuredBy = 'Windows GlobalMemoryStatusEx'; capturedAt = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json -Compress
$localListener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 5188)
$localListener.Start()
Write-Host 'Open http://127.0.0.1:5188/hardware-check/index.html in Chrome or Edge.'
Write-Host 'Only local file processing is tested. Press Ctrl+C here to stop the diagnostic server.'
try {
 while ($true) {
  $localClient = $localListener.AcceptTcpClient()
  try {
   $localClient.ReceiveTimeout = 5000
   $localStream = $localClient.GetStream()
   $localReader = New-Object IO.StreamReader($localStream, [Text.Encoding]::ASCII, $false, 1024, $true)
   $localFirst = $localReader.ReadLine()
   if (-not $localFirst) { continue }
   while ($localReader.ReadLine()) { }
   $localParts = $localFirst.Split(' ')
   if ($localParts[0] -ne 'GET') { throw 'Only static GET requests are accepted' }
   $localRequest = [Uri]::UnescapeDataString($localParts[1].Split('?')[0])
   $localStatus = '200 OK'
   if ($localRequest -eq '/hardware.json') {
    $localData = [Text.Encoding]::UTF8.GetBytes($localHardware)
    $localMime = 'application/json'
   } else {
    $localPath = [IO.Path]::GetFullPath((Join-Path $localRoot $localRequest.TrimStart('/')))
    if (-not $localPath.StartsWith($localRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid static path' }
    if (-not [IO.File]::Exists($localPath)) { $localStatus = '404 Not Found'; $localData = [Text.Encoding]::UTF8.GetBytes('Not found'); $localMime = 'text/plain' }
    else {
     $localMime = switch ([IO.Path]::GetExtension($localPath)) { '.html' { 'text/html' } '.js' { 'text/javascript' } '.mjs' { 'text/javascript' } '.wasm' { 'application/wasm' } default { 'application/octet-stream' } }
     $localData = [IO.File]::ReadAllBytes($localPath)
    }
   }
   $localCache = if ($localRequest -eq "/hardware.json" -or $localRequest.EndsWith(".html")) { "no-store" } else { "public, max-age=3600" }
   $localHeaders = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 $localStatus`r`nContent-Type: $localMime`r`nContent-Length: $($localData.Length)`r`nConnection: close`r`nCache-Control: $localCache`r`n`r`n")
   $localStream.Write($localHeaders, 0, $localHeaders.Length)
   $localStream.Write($localData, 0, $localData.Length)
   $localStream.Flush()
  } catch { Write-Warning 'A static diagnostic request failed; no file content was accepted.' }
  finally { $localClient.Dispose() }
 }
} finally { $localListener.Stop() }
