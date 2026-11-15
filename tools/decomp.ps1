# Focused Ghidra decompile of the static-analysis fixture; prints filtered C.
# Usage: tools\decomp.ps1 OUT.c 0xADDR [0xADDR ...]
param([Parameter(Mandatory)][string]$Output, [Parameter(ValueFromRemainingArguments)][string[]]$Addresses)
$root = Split-Path -Parent $PSScriptRoot
if (-not $env:GHIDRA_INSTALL_DIR) { $env:GHIDRA_INSTALL_DIR = 'C:\Users\saita\tools\ghidra_12.1.4_PUBLIC' }
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = 'C:\Users\saita\.jdks\ms-21.0.9' }
$proj = Join-Path $root 'research\ghidra-focused'
New-Item -ItemType Directory $proj -Force | Out-Null
$name = 'P' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$out = [IO.Path]::GetFullPath($Output)
& "$env:GHIDRA_INSTALL_DIR\support\analyzeHeadless.bat" $proj $name -import (Join-Path $root 'research\unpacked.analysis.exe') `
  -noanalysis -scriptPath (Join-Path $root 'tools') -postScript FocusedDecompile.java $out @Addresses -deleteProject *> $null
Get-Content $out | Select-String -NotMatch '^\s*undefined[0-9]* |^\s*$|unaff_FS_OFFSET|aiStack_|WARNING: Globals' | ForEach-Object Line
