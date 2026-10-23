param(
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$BuildRoot = Join-Path $ProjectRoot '.build-portable'
$DistRoot = Join-Path $ProjectRoot 'dist'
$PackageName = 'chsi-idphoto-swap-windows-x64'
$PackageDir = Join-Path $DistRoot $PackageName
$ZipPath = Join-Path $DistRoot ($PackageName + '.zip')

function Remove-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $projectFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
    $targetFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $targetFull.StartsWith($projectFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝删除项目目录外的路径：$targetFull"
    }
    if (Test-Path -LiteralPath $targetFull) {
        Remove-Item -LiteralPath $targetFull -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw '未找到 .venv。请先在项目目录运行“启动网页控制台.bat”，让它创建构建环境。'
}

if (-not $SkipDependencyInstall) {
    & $Python -c 'import PyInstaller' 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $Python -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 安装失败。' }
    }
}

Remove-ProjectPath -Path $BuildRoot
Remove-ProjectPath -Path $PackageDir
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

New-Item -ItemType Directory -Path $BuildRoot, $DistRoot -Force | Out-Null
$WorkDir = Join-Path $BuildRoot 'work'
$SpecDir = Join-Path $BuildRoot 'spec'
$PyInstallerDist = Join-Path $BuildRoot 'dist'

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --noupx `
    --name 'chsi-idphoto-swap' `
    --distpath $PyInstallerDist `
    --workpath $WorkDir `
    --specpath $SpecDir `
    --paths $ProjectRoot `
    --add-data "$ProjectRoot\web;web" `
    --add-data "$ProjectRoot\mitm_replace_photo.py;." `
    --collect-all mitmproxy `
    --collect-all aioquic `
    --exclude-module pydivert `
    --exclude-module mitmproxy_windows `
    --hidden-import mitmproxy.tools.main `
    "$ProjectRoot\web_app.py"

if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败。' }

Move-Item -LiteralPath (Join-Path $PyInstallerDist 'chsi-idphoto-swap') -Destination $PackageDir
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'PORTABLE_README.txt') -Destination (Join-Path $PackageDir '使用说明.txt')
Set-Content -LiteralPath (Join-Path $PackageDir '启动.bat') -Encoding Ascii -Value "@echo off`r`ncd /d `"%~dp0`"`r`nchsi-idphoto-swap.exe`r`npause`r`n"

Compress-Archive -LiteralPath $PackageDir -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "便携版目录：$PackageDir"
Write-Host "发布压缩包：$ZipPath"
