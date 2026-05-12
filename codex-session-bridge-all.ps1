$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonScript = Join-Path $ScriptDir "tools\codex_session_path_bridge_all_win_safe.py"
$BridgeArgs = $args

if (-not (Test-Path $PythonScript)) {
    throw "Python bridge script not found: $PythonScript"
}

$pythonCommand = $null
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} else {
    throw "Windows Python was not found. Install Python or make py/python available in PATH."
}

& $pythonCommand @pythonArgs $PythonScript @BridgeArgs
exit $LASTEXITCODE
