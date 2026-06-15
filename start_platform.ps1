#requires -Version 5.1
param(
    [ValidateSet('start','stop','restart','status','test','test-backend','test-frontend','build','help')]
    [string]$Command = 'start'
)

$ErrorActionPreference = 'Stop'

function Write-Info  { Write-Host "  [INFO] $args" -ForegroundColor Cyan }
function Write-Ok    { Write-Host "  [OK]   $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "  [WARN]  $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "  [ERR]   $args" -ForegroundColor Red }

$Root = $PSScriptRoot
$BackendDir  = Join-Path $Root 'news-web\backend'
$FrontendDir = Join-Path $Root 'news-web\frontend'
$LogsDir     = Join-Path $Root 'logs'
$PidDir      = Join-Path $Root 'pids'

$Port = if ($env:PORT) { [int]$env:PORT } else { 8081 }

New-Item -ItemType Directory -Force -Path $LogsDir, $PidDir | Out-Null
$BackendLog = Join-Path $LogsDir 'backend.log'
$BackendPid = Join-Path $PidDir 'backend.pid'

function Get-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return 'python3' }
    return $null
}

function Test-PortInUse {
    param([int]$PortNum)
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $conn = Get-NetTCPConnection -LocalPort $PortNum -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $foundPid = $conn[0].OwningProcess
            # 确认进程真实存活（避免孤儿 TCP 条目误判）
            $proc = Get-Process -Id $foundPid -ErrorAction SilentlyContinue
            if ($proc) { return $true }
        }
    }
    $lines = netstat -ano | Select-String ":$PortNum\s" | Where-Object { $_ -match 'LISTENING' }
    foreach ($line in $lines) {
        $parts = ($line -split '\s+') -ne ''
        $foundPid = $parts[-1]
        if (Get-Process -Id $foundPid -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Get-PidByPort {
    param([int]$PortNum)
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $conn = Get-NetTCPConnection -LocalPort $PortNum -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $foundPid = $conn[0].OwningProcess
            if (Get-Process -Id $foundPid -ErrorAction SilentlyContinue) { return $foundPid }
        }
    }
    $lines = netstat -ano | Select-String ":$PortNum\s" | Where-Object { $_ -match 'LISTENING' }
    foreach ($line in $lines) {
        $parts = ($line -split '\s+') -ne ''
        $foundPid = $parts[-1]
        if (Get-Process -Id $foundPid -ErrorAction SilentlyContinue) { return $foundPid }
    }
    return $null
}

function Build-Frontend {
    Write-Info "构建前端..."
    Push-Location $FrontendDir
    try {
        npm install --silent 2>$null
        npx tsc
        if ($LASTEXITCODE -ne 0) { throw "TypeScript 编译失败" }
        npx vite build
        if ($LASTEXITCODE -ne 0) { throw "Vite 构建失败" }
    }
    finally { Pop-Location }
    Write-Ok "前端构建完成 $FrontendDir\dist"
}

function Start-Backend {
    if (Test-PortInUse -PortNum $Port) {
        $existingPid = Get-PidByPort -PortNum $Port
        Write-Warn "端口 $Port 已被进程 $existingPid 占用 - 后端可能已在运行"
        $existingPid | Out-File -FilePath $BackendPid -Encoding ascii -Force
        return
    }

    Write-Info "启动后端 http://localhost:$Port ..."
    $py = Get-Python
    if (-not $py) { Write-Err "未找到 Python"; exit 1 }

    Push-Location $BackendDir
    try {
        Start-Process -FilePath $py -ArgumentList 'main.py' `
            -RedirectStandardOutput $BackendLog `
            -RedirectStandardError "${BackendLog}.err" `
            -NoNewWindow -PassThru | Select-Object -ExpandProperty Id |
            Out-File -FilePath $BackendPid -Encoding ascii -Force
    }
    finally { Pop-Location }

    $startedPid = (Get-Content $BackendPid -ErrorAction SilentlyContinue).Trim()

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($resp.StatusCode -eq 200) {
                Write-Ok "后端就绪 (PID: $startedPid)"
                return
            }
        } catch {}
    }
    Write-Err "后端启动超时 - 查看 $BackendLog"
    exit 1
}

function Stop-Backend {
    $procId = $null

    if (Test-Path $BackendPid) {
        $procId = (Get-Content $BackendPid -ErrorAction SilentlyContinue).Trim()
    }
    if (-not $procId) {
        $procId = Get-PidByPort -PortNum $Port
    }
    if (-not $procId) {
        Write-Info "后端未运行"
        return
    }

    Write-Info "停止后端 (PID: $procId)..."
    try {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        $alive = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($alive) {
            Write-Warn "未响应，强制终止..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    Remove-Item -Path $BackendPid -Force -ErrorAction SilentlyContinue
    Write-Ok "后端已停止"
}

function Show-Status {
    Write-Host ""
    Write-Host "===== LapTalk 服务状态 =====" -ForegroundColor Cyan
    Write-Host ""

    if (Test-PortInUse -PortNum $Port) {
        $statusPid = Get-PidByPort -PortNum $Port
        Write-Host "  后端 API   " -NoNewline; Write-Host "● 运行中" -ForegroundColor Green -NoNewline; Write-Host "  port:$Port  pid:$statusPid"
    } else {
        Write-Host "  后端 API   " -NoNewline; Write-Host "● 未启动" -ForegroundColor Red
    }

    $db = Join-Path $BackendDir 'data\news.db'
    if (Test-Path $db) {
        $py = Get-Python
        if ($py) {
            $countFile = Join-Path $LogsDir '_count.txt'
            $dbcountPy = Join-Path $Root 'tools\dbcount.py'
            if (Test-Path $dbcountPy) {
                & $py $dbcountPy $db $countFile 2>$null
                $count = if (Test-Path $countFile) { (Get-Content $countFile -ErrorAction SilentlyContinue).Trim() } else { '?' }
                Remove-Item -Path $countFile -Force -ErrorAction SilentlyContinue
            } else {
                $count = '? (dbcount.py not found)'
            }
            Write-Host "  数据库     " -NoNewline; Write-Host "$count" -ForegroundColor Green -NoNewline; Write-Host " 篇文章"
        }
    } else {
        Write-Host "  数据库     " -NoNewline; Write-Host "未找到" -ForegroundColor Yellow
    }

    if (Test-Path (Join-Path $FrontendDir 'dist\index.html')) {
        Write-Host "  前端构建   " -NoNewline; Write-Host "已就绪" -ForegroundColor Green
    } else {
        Write-Host "  前端构建   " -NoNewline; Write-Host "未构建" -ForegroundColor Yellow -NoNewline; Write-Host " — .\start_platform.ps1 build"
    }

    Write-Host ""
    Write-Host "  主页       " -NoNewline; Write-Host "http://localhost:$Port" -ForegroundColor Green
    Write-Host "  API 文档   " -NoNewline; Write-Host "http://localhost:$Port/docs" -ForegroundColor Green
    Write-Host "  日志       " -NoNewline; Write-Host "$BackendLog" -ForegroundColor Yellow
    Write-Host ""
}

function Invoke-TestAll {
    Write-Host ""
    Write-Host "===== 后端测试 (pytest) =====" -ForegroundColor Cyan
    Push-Location (Join-Path $Root 'news-web')
    & (Get-Python) -m pytest tests/backend/test_api.py -v --tb=short
    Pop-Location

    Write-Host ""
    Write-Host "===== 前端测试 (vitest) =====" -ForegroundColor Cyan
    Push-Location $FrontendDir
    npm test
    Pop-Location
}

function Invoke-TestBackend {
    Push-Location (Join-Path $Root 'news-web')
    & (Get-Python) -m pytest tests/backend/test_api.py -v --tb=short
    Pop-Location
}

function Invoke-TestFrontend {
    Push-Location $FrontendDir
    npm test
    Pop-Location
}

function Show-Help {
    Write-Host "LapTalk 启动脚本" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "用法: .\start_platform.ps1 <命令>"
    Write-Host ""
    Write-Host "命令:"
    Write-Host "  start          启动后端 (需前端已构建)"
    Write-Host "  stop           停止后端"
    Write-Host "  restart        重启后端"
    Write-Host "  status         查看服务 / 数据库 / 前端状态"
    Write-Host "  test           运行全部测试 (pytest + vitest)"
    Write-Host "  test-backend   仅后端测试"
    Write-Host "  test-frontend  仅前端测试"
    Write-Host "  build          仅构建前端"
    Write-Host ""
    Write-Host "环境变量:"
    Write-Host "  `$env:PORT=8081  自定义后端端口"
    Write-Host ""
}

switch ($Command) {
    'start' {
        if (-not (Test-Path (Join-Path $FrontendDir 'dist\index.html'))) {
            Write-Warn "前端未构建，自动构建..."
            Build-Frontend
        }
        Start-Backend
        Show-Status
    }
    'stop' {
        Stop-Backend
    }
    'restart' {
        Stop-Backend
        Start-Sleep -Seconds 2
        if (-not (Test-Path (Join-Path $FrontendDir 'dist\index.html'))) {
            Build-Frontend
        }
        Start-Backend
        Show-Status
    }
    'status' {
        Show-Status
    }
    'test' {
        Invoke-TestAll
    }
    'test-backend' {
        Invoke-TestBackend
    }
    'test-frontend' {
        Invoke-TestFrontend
    }
    'build' {
        Build-Frontend
    }
    'help' {
        Show-Help
    }
}
