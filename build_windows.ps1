$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 3.12 虚拟环境' }
}

& '.venv\Scripts\python.exe' -m pip install -r requirements.txt 'pyinstaller>=6,<7'
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }

& '.venv\Scripts\python.exe' -m unittest discover -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw '测试未通过，已停止打包' }

& '.venv\Scripts\flet.exe' pack main.py --name RoommatePantry --yes
if ($LASTEXITCODE -ne 0) { throw 'Windows 打包失败' }

Write-Host '完成：dist\RoommatePantry.exe'
