@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 知识库 · 一键启动

echo.
echo   ==========================================================
echo     知识库 · 一键启动
echo     Docker 数据服务 + 后端 API + 前端页面 + 自动开浏览器
echo     项目目录：%~dp0
echo   ==========================================================
echo.

REM ================================================================
REM  第 1 步：Docker 数据服务（Milvus / etcd / MinIO / Attu / MongoDB）
REM ================================================================
echo   [1/4] 检查 Docker 引擎...
set "DD_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not exist "%DD_EXE%" set "DD_EXE=%LOCALAPPDATA%\Docker\Docker Desktop.exe"

docker info >nul 2>nul
if not errorlevel 1 goto DOCKER_READY

echo         Docker 引擎没在跑，正在启动 Docker Desktop...
if not exist "%DD_EXE%" goto DOCKER_SKIP
start "" "%DD_EXE%"
echo         已拉起 Docker Desktop（首次较慢，最多等 3 分钟）...
set /a DN=0
:DW
ping -n 4 127.0.0.1 >nul
docker info >nul 2>nul
if not errorlevel 1 goto DOCKER_READY
set /a DN+=1
if %DN% lss 60 goto DW
echo         [警告] 等了 3 分钟引擎仍未就绪，跳过 Docker。
goto DOCKER_SKIP

:DOCKER_READY
echo         引擎正常，正在启动数据容器...
pushd "%~dp0docker"
docker compose version >nul 2>nul
if errorlevel 1 goto DC_OLD
docker compose up -d
goto DC_DONE
:DC_OLD
echo         (未找到 docker compose 子命令，退回 docker-compose)
docker-compose up -d
:DC_DONE
set "DCERR=%errorlevel%"
popd
if not "%DCERR%"=="0" goto DOCKER_UPFAIL
echo         容器已拉起，等待 Milvus / MongoDB 就绪...
set /a HN=0
:HCLOOP
set "HC_M=unknown"
for /f "usebackq delims=" %%i in (`docker inspect -f "{{.State.Health.Status}}" milvus-standalone 2^>nul`) do set "HC_M=%%i"
set "HC_D=unknown"
for /f "usebackq delims=" %%i in (`docker inspect -f "{{.State.Health.Status}}" mongo 2^>nul`) do set "HC_D=%%i"
if /i "%HC_M%"=="healthy" if /i "%HC_D%"=="healthy" goto DOCKER_ALL_OK
set /a HN+=1
if %HN% gtr 90 goto HC_TIMEOUT
ping -n 3 127.0.0.1 >nul
goto HCLOOP

:DOCKER_ALL_OK
echo         Milvus 与 MongoDB 均已就绪。
goto PY_ENV

:HC_TIMEOUT
echo         [警告] 等待超时（Milvus=%HC_M% / MongoDB=%HC_D%），先继续启动后端。
goto PY_ENV

:DOCKER_UPFAIL
echo         [警告] docker compose up -d 失败（退出码 %DCERR%），先继续启动后端。
goto PY_ENV

:DOCKER_SKIP
echo         已跳过 Docker。若 Milvus / MongoDB 没在跑，问答和导入会报连接错误。
echo.
echo         按任意键继续启动后端（关掉本窗口则取消）...
pause >nul

REM ================================================================
REM  第 2 步：挑选 Python 解释器 + 启动两个后端 API
REM ================================================================
:PY_ENV
echo.
echo   [2/4] 启动后端服务（前端页面由问答服务一并托管）...
if exist ".venv\Scripts\python.exe" goto USE_VENV
where uv >nul 2>nul
if errorlevel 1 goto NO_ENV
set "PY=uv run python"
set "PYSRC=uv 命令（自动使用 .venv）"
goto CHECK_PORT
:USE_VENV
set "PY=.venv\Scripts\python.exe"
set "PYSRC=.venv 虚拟环境"
goto CHECK_PORT

:NO_ENV
echo.
echo   [错误] 既找不到 .venv\Scripts\python.exe，也找不到 uv 命令。
echo          请先在本目录执行：  uv sync
echo.
pause
exit /b 1

:CHECK_PORT
echo         使用解释器：%PYSRC%
set "SKIP1=0"
netstat -ano | findstr "LISTENING" | findstr ":8001 " >nul 2>nul
if not errorlevel 1 set "SKIP1=1"
set "SKIP2=0"
netstat -ano | findstr "LISTENING" | findstr ":8003 " >nul 2>nul
if not errorlevel 1 set "SKIP2=1"

echo         [1/2] 文档导入  →  http://127.0.0.2:8001
if "%SKIP1%"=="1" goto KEEP1
start "知识库 · 文档导入 8001" cmd /k %PY% -m web.api.import_service
goto STEP2
:KEEP1
echo               已跳过：8001 端口被占用，服务可能已在运行
:STEP2

echo         [2/2] 知识问答  →  http://127.0.0.1:8003
if "%SKIP2%"=="1" goto KEEP2
echo               提示：要加载重依赖，约 25 秒才就绪，属正常
start "知识库 · 知识问答 8003" cmd /k %PY% -m web.api.query_service
goto WAIT
:KEEP2
echo               已跳过：8003 端口被占用，服务可能已在运行

REM ================================================================
REM  第 3 步：等服务就绪 + 自动打开浏览器
REM ================================================================
:WAIT
echo.
echo   [3/4] 等待服务就绪...
where curl >nul 2>nul
if errorlevel 1 goto WAIT_PLAIN

set /a N=0
:WAIT_LOOP
ping -n 3 127.0.0.1 >nul
curl -s -o nul --max-time 2 http://127.0.0.1:8003/health
if not errorlevel 1 goto OPEN
set /a N+=1
if %N% lss 30 goto WAIT_LOOP
goto TIMEOUT

:WAIT_PLAIN
echo         未找到 curl，改为固定等待 30 秒...
ping -n 31 127.0.0.1 >nul

:OPEN
echo   [4/4] 服务已就绪，正在打开浏览器...
start "" http://127.0.0.1:8003/
echo.
echo   ----------------------------------------------------------
echo   全部启动完成
echo     门户页面    http://127.0.0.1:8003/
echo     文档导入    http://127.0.0.2:8001/import.html
echo     Milvus UI   http://localhost:8000/     (Attu)
echo     MinIO 控制台 http://localhost:9001/     (minioadmin / minioadmin)
echo.
echo   关闭本窗口不影响服务。
echo   要停止服务：关掉上面打开的两个命令行窗口，然后执行
echo     cd docker  ^&^&  docker compose down
echo   ----------------------------------------------------------
ping -n 8 127.0.0.1 >nul
exit /b 0

:TIMEOUT
echo.
echo   [警告] 等待超时，服务还没起来。
echo          请查看上面打开的那两个命令行窗口里的报错信息。
echo.
pause
exit /b 1
