$ErrorActionPreference = "Stop"
$base = "HKCU:\Software\Classes"
New-Item -Force -Path "$base\.hdox" | Out-Null
Set-ItemProperty "$base\.hdox" -Name "(default)" -Value "HDOX.Document.1"
Set-ItemProperty "$base\.hdox" -Name "Content Type" -Value "application/vnd.hdox+zip"
New-Item -Force -Path "$base\HDOX.Document.1" | Out-Null
New-Item -Force -Path "$base\HDOX.Document.1\shell\open\command" | Out-Null
Set-ItemProperty "$base\HDOX.Document.1\shell\open\command" -Name "(default)" -Value '"%SystemRoot%\System32\notepad.exe" "%1"'
