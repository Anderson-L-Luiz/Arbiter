param(
    [Parameter(Mandatory=$true)][string]$ProjectDir,
    [Parameter(Mandatory=$true)][string]$Task,
    [int]$Rounds = 5,
    [double]$StopScore = 9.0,
    [string]$ClaudeModel = "sonnet",
    [string]$GeminiModel = "gemini-2.5-pro"
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
& "C:\Users\ander\AppData\Local\Python\bin\python.exe" -m arbiter.app `
    $ProjectDir -t $Task -n $Rounds --stop-score $StopScore `
    --claude-model $ClaudeModel --gemini-model $GeminiModel
