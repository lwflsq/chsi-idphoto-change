param(
    [switch]$Check,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function Test-PythonVersion([string]$Executable) {
    try {
        & $Executable -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python {
    $Candidates = @()
    if ($env:IDPHOTO_PYTHON) { $Candidates += $env:IDPHOTO_PYTHON }
    foreach ($Name in @("py", "python3", "python")) {
        $Command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
        if ($Command -and $Command.Source -notlike "*\Microsoft\WindowsApps\*") {
            $Candidates += $Command.Source
        }
    }
    # 本机已有可用的 Python 时，可用于创建项目独立虚拟环境。
    $Candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if ((Test-Path -LiteralPath $Candidate) -and (Test-PythonVersion $Candidate)) {
            return $Candidate
        }
    }
    throw "找不到 Python 3.12+。请安装 Python 并勾选 Add Python to PATH，或设置 IDPHOTO_PYTHON 为 python.exe 的完整路径。"
}

try {
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        $Bootstrap = Find-Python
        Write-Host "首次运行：创建项目虚拟环境..." -ForegroundColor Cyan
        & $Bootstrap -m venv (Join-Path $ProjectRoot ".venv")
        if ($LASTEXITCODE -ne 0) { throw "虚拟环境创建失败，请检查上方错误。" }
    }
    if (-not (Test-PythonVersion $Python)) {
        throw "项目 .venv 的 Python 无法运行或版本低于 3.12，请检查虚拟环境。"
    }

    $DependenciesReady = $false
    try {
        & $Python -c "import mitmproxy, segno" 2>$null
        $DependenciesReady = $LASTEXITCODE -eq 0
    } catch { $DependenciesReady = $false }
    if (-not $DependenciesReady) {
        Write-Host "安装项目依赖..." -ForegroundColor Cyan
        & $Python -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw "pip 初始化失败，请检查上方错误。" }
        & $Python -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "依赖安装失败，请检查网络后重新运行。" }
    }
    if ($Check) {
        Write-Host "启动检查通过：Python、mitmproxy 和二维码依赖均可用。" -ForegroundColor Green
        exit 0
    }
    & $Python -u (Join-Path $ProjectRoot "web_app.py") --port $Port
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
