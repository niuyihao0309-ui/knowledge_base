@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 知识库 · 一键启动

REM ==========================================================================
REM  知识库 · 一键启动
REM    · 第 1 步：Docker 数据服务（Milvus + etcd + MinIO + MongoDB）
REM    · 第 2 步：文档导入 API（127.0.0.2:8005）+ 知识问答 API（127.0.0.1:8003）
REM    · 第 3 步：等服务就绪
REM    · 第 4 步：自动拉起浏览器，打开「统一入口」门户页
REM              （导入页不单独开，从门户里点「文档导入」卡片进）
REM  维护提示：改端口必须同步改这 4 处 ——
REM    web/api/import_service.py(uvicorn.run)、web/page/import.html(API_BASE)、
REM    web/page/index.html(模块 href + port)、本脚本下方的 IMP_PORT / QRY_PORT。
REM  另：两个后端返回 HTML 时已带 Cache-Control: no-store；此外第 4 步打开门户时
REM      还会在地址后挂一个随机参数(?t=xxxx)，双保险防止浏览器拿旧页面来坑人。
REM  ⚠️【写 echo 的铁律】echo 的文本里禁止出现 > < & | ( ) ^ 这些 cmd 元字符。
REM     尤其别用 "^>" 转义箭头 —— 一旦哪层解析出了偏差，cmd 会把它当重定向符，
REM     在项目根凭空生成名为「文档导入」「知识问答」的垃圾文件（2026-10-16 真踩过）。
REM     要表达"箭头/括号"请直接用全角符号：→ ← （） 【】 ★，绝对安全。
REM ==========================================================================

set "ROOT=%~dp0"
set "IMP_PORT=8005"
set "QRY_PORT=8003"
set "IMP_URL=http://127.0.0.2:8005"
set "QRY_URL=http://127.0.0.1:8003"

echo.
echo   ==========================================================
echo     知识库 · 一键启动
echo     Docker 数据服务 + 后端 API + 前端页面 + 自动开浏览器
echo     项目目录：%ROOT%
echo   ==========================================================
echo.

REM ================================================================
REM  第 1 步：Docker 数据服务
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
pushd "%ROOT%docker"
docker compose version >nul 2>nul
if errorlevel 1 goto DC_OLD
REM --remove-orphans：把「已从 compose 里移除、容器却还在跑」的服务一并清掉，
REM 否则像已注释掉的 attu 会继续占着 8000 端口。
docker compose up -d --remove-orphans
goto DC_DONE
:DC_OLD
echo         （未找到 docker compose 子命令，退回 docker-compose）
docker-compose up -d --remove-orphans
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
docker ps --format "         · {{.Names}}  {{.Status}}" --filter "name=milvus-" --filter "name=mongo"
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
echo   [2/4] 启动后端服务（前端页面由后端一并托管）...
if exist "%ROOT%.venv\Scripts\python.exe" goto USE_VENV
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
REM 端口占用检测：上一次启动留下的黑窗口还开着时，这里会判定「已在运行」并跳过启动。
REM ⚠️ 陷阱：跳过之后再手动关掉那些旧窗口，服务就没了，而本脚本已经跑完 —— 表现为
REM    「点卡片打不开 / 连接被拒绝」。所以下面的提示写得很醒目，并且最后会汇总谁是新起的、谁是复用的。
set "REUSED="
set "SKIP1=0"
netstat -ano | findstr "LISTENING" | findstr ":%IMP_PORT% " >nul 2>nul
if not errorlevel 1 set "SKIP1=1"
set "SKIP2=0"
netstat -ano | findstr "LISTENING" | findstr ":%QRY_PORT% " >nul 2>nul
if not errorlevel 1 set "SKIP2=1"

echo         [1/2] 文档导入  →  %IMP_URL%
if "%SKIP1%"=="1" goto KEEP1
start "知识库 · 文档导入 %IMP_PORT%" cmd /k %PY% -m web.api.import_service
goto STEP2
:KEEP1
echo               [跳过] %IMP_PORT% 端口已被占用，不重复启动「文档导入」
echo                      ★★★ 它由上一次启动的那个黑窗口在跑，请别关掉它 ★★★
set "REUSED=%REUSED% 文档导入"
:STEP2

echo         [2/2] 知识问答  →  %QRY_URL%
if "%SKIP2%"=="1" goto KEEP2
echo               提示：要加载重依赖，约 25 秒才就绪，属正常
start "知识库 · 知识问答 %QRY_PORT%" cmd /k %PY% -m web.api.query_service
goto WAIT
:KEEP2
echo               [跳过] %QRY_PORT% 端口已被占用，不重复启动「知识问答」
echo                      ★★★ 它由上一次启动的那个黑窗口在跑，请别关掉它 ★★★
set "REUSED=%REUSED% 知识问答"

REM ================================================================
REM  第 3 步：等服务就绪 + 第 4 步 打开浏览器
REM ================================================================
:WAIT
echo.
echo   [3/4] 等待服务就绪...
where curl >nul 2>nul
if errorlevel 1 goto WAIT_PLAIN

set /a N=0
:WAIT_LOOP
ping -n 3 127.0.0.1 >nul
curl -s -o nul --max-time 2 %QRY_URL%/health
if errorlevel 1 goto WAIT_NEXT
curl -s -o nul --max-time 2 %IMP_URL%/import.html
if not errorlevel 1 goto OPEN
:WAIT_NEXT
set /a N+=1
if %N% lss 30 goto WAIT_LOOP
goto TIMEOUT

:WAIT_PLAIN
echo         未找到 curl，改为固定等待 30 秒...
ping -n 31 127.0.0.1 >nul

:OPEN
echo   [4/4] 服务已就绪，正在打开浏览器...
REM 只开「统一入口」这一个页面（地址 127.0.0.1:8003）。
REM 导入页不用单独开 —— 在统一入口里点「文档导入」卡片即可，
REM 那张卡片的 href 就是 http://127.0.0.2:8005/import.html（见 web/page/index.html）。
REM
REM 【防「旧页面」】URL 末尾挂一个每次都不同的随机参数。
REM   浏览器（尤其 Chrome）的缓存/「恢复上次标签页」是按 URL 复用的：
REM   地址一字不差 → 它可能直接还原上次渲染出来的那份 DOM，
REM   而那份 DOM 里卡片 href 还停在老端口（例如 8001），点下去就跳进死链。
REM   换成随机地址后浏览器必须重新向服务器取，从根上杜绝这类问题。
REM   注：FastAPI 的 @app.get("/") 不校验查询参数，多带 ?t=xxx 不影响路由。
set "CACHEBUST=%RANDOM%%RANDOM%%RANDOM%"
set "OPEN_URL=%QRY_URL%/?t=%CACHEBUST%"
start "" "%OPEN_URL%"
echo.
echo   ----------------------------------------------------------
echo   全部启动完成（浏览器已打开「统一入口」，点卡片进各功能）
if not "%REUSED%"=="" echo   【复用】本次未重启的服务：%REUSED%  （它们由之前的黑窗口在跑，别关）
echo   统一入口    %OPEN_URL%   ←← 打开的就是这个
echo     文档导入    %IMP_URL%/import.html  （统一入口 → 文档导入 卡片）
echo     知识问答    %QRY_URL%/chat.html    （统一入口 → 知识问答 卡片）
echo     MinIO 控制台 http://localhost:9001/   （minioadmin / minioadmin）
echo     Milvus 健康  http://localhost:9091/healthz
echo.
echo   关闭本窗口不影响服务；但上面那两个服务黑窗口一关，服务就停了。
echo   要停止服务：关掉上面打开的两个服务命令行窗口，然后依次执行
echo     cd docker
echo     docker compose down
echo   ----------------------------------------------------------
ping -n 8 127.0.0.1 >nul
exit /b 0

:TIMEOUT
echo.
echo   [警告] 等待超时，服务还没起来。
echo          请查看上面打开的那两个服务命令行窗口里的报错信息。
if not "%REUSED%"=="" echo.
if not "%REUSED%"=="" echo          另外：本次「%REUSED%」是按「端口已占用」跳过的（见上方 [跳过] 提示），
if not "%REUSED%"=="" echo          如果占用端口的旧窗口已经被你关掉，就会出现这种「端口占着但没响应」。
if not "%REUSED%"=="" echo          处理办法：把占用 %IMP_PORT% / %QRY_PORT% 的旧窗口关干净，再重跑本脚本。
echo.
pause
exit /b 1
