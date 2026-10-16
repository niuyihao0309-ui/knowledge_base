@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 知识库 · 一键启动

REM ==========================================================================
REM  知识库 · 一键启动（2026-10-16 重写版）
REM
REM  四步走：
REM    第 1 步  Docker 数据服务：Milvus + etcd + MinIO + MongoDB
REM    第 2 步  后端 API：文档导入 127.0.0.2:8005 ＋ 知识问答 127.0.0.1:8003
REM    第 3 步  前端页面：由上面两个后端直接托管，这里只做就绪校验
REM    第 4 步  自动拉起默认浏览器，打开「统一入口」门户页并挂随机参数防缓存
REM
REM  相比旧版的四处改进：
REM    一、判断「服务是否已在运行」不再只看端口占没占，而是发一次真实 HTTP 请求：
REM        通了才复用；端口被占却不通，会打印占用进程的命令行并给出处理选项，
REM        从根上治好了「端口占着、服务却是死的」这个老坑。
REM    二、占用进程如果正是本项目上次启动的残留，直接自动清掉，不用手工确认。
REM    三、每个服务起完都等它真的能响应，最后汇总谁新起、谁复用、谁失败。
REM    四、问答服务没起来时，浏览器改开导入门户，不至于开出个白页。
REM
REM  改端口必须同步改这 6 处：
REM    web/api/import_service.py 的 uvicorn.run
REM    web/api/query_service.py  的 uvicorn.run
REM    web/page/import.html      的 API_BASE
REM    web/page/chat.html        的 API_BASE 兜底
REM    web/page/index.html       的 PORTAL_CONFIG 模块 href / port / stamp
REM    本脚本下面的 IMP_PORT、QRY_PORT、IMP_URL、QRY_URL
REM
REM  【写 echo 的铁律】echo 文本里禁止出现 ASCII 的 大于号 小于号 与号 竖线 括号 脱字符，
REM     尤其别用脱字符转义箭头 —— 解析一旦出偏差，cmd 会把它当重定向符，
REM     在项目根凭空生成名为「文档导入」的垃圾文件（2026-10-16 真踩过）。
REM     要表达箭头、括号请直接用全角符号：→ ← （） 【】 ★ 则绝对安全。
REM  同理，下面所有可能带符号的变量都用 type 或 powershell 直接输出，不走 echo 拼接。
REM ==========================================================================

set "ROOT=%~dp0"
set "IMP_PORT=8005"
set "QRY_PORT=8003"
set "IMP_URL=http://127.0.0.2:8005"
set "QRY_URL=http://127.0.0.1:8003"
set "IMP_NAME=文档导入"
set "QRY_NAME=知识问答"
set "STAMP=2026-10-16 · 导入 8005 / 问答 8003"
set "WORK=%TEMP%\kb_launch"
if not exist "%WORK%" md "%WORK%" >nul 2>nul

echo.
echo   ==========================================================
echo     知识库 · 一键启动
echo     Docker 数据服务  →  后端 API  →  前端页面  →  浏览器
echo     项目目录：%ROOT%
echo     配置指纹：%STAMP%
echo   ==========================================================
echo.

REM ================================================================
REM  第 1 步：Docker 数据服务
REM ================================================================
echo   [1/4] Docker 数据服务
docker info >nul 2>nul
if not errorlevel 1 goto DK_ENGINE_OK

echo         引擎没在跑，正在拉起 Docker Desktop ...
set "DD_EXE=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if exist "%DD_EXE%" goto DK_START
set "DD_EXE=%LOCALAPPDATA%\Docker\Docker Desktop.exe"
if exist "%DD_EXE%" goto DK_START
echo         [警告] 找不到 Docker Desktop.exe，跳过 Docker 步骤
goto DK_SKIP

:DK_START
start "" "%DD_EXE%"
echo         已拉起，等待引擎就绪，最长 3 分钟 ...
call :WAIT_ENGINE
if not errorlevel 1 goto DK_ENGINE_OK
echo         [警告] 等了 3 分钟引擎仍未就绪，跳过 Docker 步骤
goto DK_SKIP

:DK_ENGINE_OK
echo         引擎正常，启动数据容器 ...
pushd "%ROOT%docker"
docker compose up -d --remove-orphans
set "DCERR=%errorlevel%"
popd
if not "%DCERR%"=="0" goto DK_UPFAIL
echo         容器已创建，等待 Milvus 与 MongoDB 真正就绪 ...
call :WAIT_CONTAINERS
if errorlevel 1 goto DK_HCSLOW
echo         Milvus 与 MongoDB 均已就绪
docker ps --format "         · {{.Names}}  {{.Status}}" --filter "name=milvus-" --filter "name=mongo"
goto PY_ENV

:DK_UPFAIL
echo         [警告] docker compose up 失败，退出码 %DCERR%，继续启动后端
goto PY_ENV

:DK_HCSLOW
echo         [警告] 容器健康检查未在时限内通过，继续启动后端
goto PY_ENV

:DK_SKIP
echo         [警告] 已跳过 Docker。Milvus 与 MongoDB 没在跑的话，问答和导入都会报连接错误；
echo                而且 MongoDB 不可达时知识问答服务在 import 阶段就会崩，根本起不来。
echo.
echo         按任意键继续启动后端，关掉本窗口即取消 ...
pause >nul

REM ================================================================
REM  第 2 步：后端 API（前端页面由它们一并托管）
REM ================================================================
:PY_ENV
echo.
echo   [2/4] 后端 API
if exist "%ROOT%.venv\Scripts\python.exe" goto USE_VENV
where uv >nul 2>nul
if errorlevel 1 goto NO_ENV
set "PY=uv run python"
set "PYSRC=uv 命令（自动使用 .venv）"
goto HAVE_PY
:USE_VENV
set "PY=.venv\Scripts\python.exe"
set "PYSRC=.venv 虚拟环境"
goto HAVE_PY

:NO_ENV
echo   [错误] 既找不到 .venv\Scripts\python.exe，也找不到 uv 命令。
echo          请先在本目录执行：  uv sync
echo.
pause
exit /b 1

:HAVE_PY
echo         解释器：%PYSRC%
set "STARTED="
set "REUSED="
set "FAILED="

echo.
echo         [1/2] 文档导入  →  %IMP_URL%/import.html
set "SVC_MODULE=web.api.import_service"
set "SVC_TITLE=知识库 · 文档导入 %IMP_PORT%"
set "SVC_PORT=%IMP_PORT%"
set "SVC_PROBE=%IMP_URL%/import.html"
set "SVC_LABEL=%IMP_NAME%"
call :ENSURE_SERVICE

echo.
echo         [2/2] 知识问答  →  %QRY_URL%/chat.html
echo               提示：要加载重依赖，约 25 秒才就绪，属正常
set "SVC_MODULE=web.api.query_service"
set "SVC_TITLE=知识库 · 知识问答 %QRY_PORT%"
set "SVC_PORT=%QRY_PORT%"
set "SVC_PROBE=%QRY_URL%/health"
set "SVC_LABEL=%QRY_NAME%"
call :ENSURE_SERVICE

REM ================================================================
REM  第 3 步：前端页面就绪校验（页面由后端托管，这里只确认能取到）
REM ================================================================
echo.
echo   [3/4] 前端页面（由后端托管）
call :PROBE "%IMP_URL%/import.html"
if errorlevel 1 goto P3_IMP_BAD
echo         文档导入页  %IMP_URL%/import.html   就绪
goto P3_QRY
:P3_IMP_BAD
echo         文档导入页  %IMP_URL%/import.html   未就绪
:P3_QRY
call :PROBE "%QRY_URL%/chat.html"
if errorlevel 1 goto P3_QRY_BAD
echo         知识问答页  %QRY_URL%/chat.html   就绪
goto P3_PORTAL
:P3_QRY_BAD
echo         知识问答页  %QRY_URL%/chat.html   未就绪

REM 门户页优先挂在问答服务上，问答没起来就退回导入服务
:P3_PORTAL
set "PORTAL="
call :PROBE "%QRY_URL%/"
if not errorlevel 1 set "PORTAL=%QRY_URL%/"
if defined PORTAL goto P4_OPEN
call :PROBE "%IMP_URL%/"
if not errorlevel 1 set "PORTAL=%IMP_URL%/"

REM ================================================================
REM  第 4 步：拉起浏览器
REM ================================================================
:P4_OPEN
echo.
if not defined PORTAL goto P4_NOPORTAL

echo   [4/4] 打开浏览器 ...
REM URL 末尾挂随机参数：浏览器（尤其 Chrome）的缓存/「恢复上次标签页」是按 URL 复用的，
REM 地址一字不差时它可能直接还原上次那份 DOM，而那份 DOM 里的卡片 href 还停着老端口。
REM 换随机地址后必须重新向服务器取，从根上杜绝「点卡片跳死链」。
REM 注：FastAPI 的 GET / 不校验查询参数，多带 ?t=xxx 不影响路由。
set "OPEN_URL=%PORTAL%?t=%RANDOM%%RANDOM%%RANDOM%"
start "" "%OPEN_URL%"
goto P_SUMMARY

:P4_NOPORTAL
echo   [4/4] [警告] 两个服务都没能响应，不开浏览器了。
echo         请看标题带「知识库」的那两个黑窗口里的报错信息。

:P_SUMMARY
echo.
echo   ----------------------------------------------------------
if defined PORTAL echo   统一入口    %OPEN_URL%
echo     文档导入    %IMP_URL%/import.html
echo     知识问答    %QRY_URL%/chat.html
echo     MinIO 控制台   http://localhost:9001/    账号密码 minioadmin / minioadmin
echo     Milvus 健康    http://localhost:9091/healthz
echo.
if defined STARTED echo   【本次新起】%STARTED%
if defined REUSED echo   【直接复用】%REUSED%
if defined FAILED echo   【启动失败】%FAILED%
echo.
if defined REUSED echo   复用的服务是之前那个黑窗口在跑，别把那些窗口关掉，否则服务就停了。
echo   本窗口可以直接关掉，不影响服务。
echo   停止服务：先关掉带「知识库」标题的服务黑窗口，再到 docker 目录执行  docker compose down
echo   ----------------------------------------------------------
echo.

if defined FAILED goto P_END_PAUSE
echo   10 秒后自动关闭本窗口 ...
ping -n 11 127.0.0.1 >nul
exit /b 0

:P_END_PAUSE
echo   有服务启动失败，本窗口保持打开，看清报错后按任意键关闭 ...
pause >nul
exit /b 1


REM ================================================================
REM  以下为子过程
REM ================================================================

REM ----------------------------------------------------------------
REM  确保一个后端服务在跑
REM    入参变量：SVC_MODULE / SVC_TITLE / SVC_PORT / SVC_PROBE / SVC_LABEL
REM    出参变量：SVC_RESULT = started / reused / failed / skipped
REM ----------------------------------------------------------------
:ENSURE_SERVICE
set "SVC_RESULT=failed"

call :PROBE "%SVC_PROBE%"
if not errorlevel 1 goto ES_ALIVE

REM 探测不通 —— 看端口是不是被别人占着
set "SVC_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:"LISTENING" ^| findstr /c:":%SVC_PORT% "') do set "SVC_PID=%%p"
if not defined SVC_PID goto ES_START

echo               [注意] 端口 %SVC_PORT% 已被占用，但这个服务没有响应
echo                      占用进程 PID：%SVC_PID%
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter 'ProcessId=%SVC_PID%' | Select-Object -ExpandProperty CommandLine" > "%WORK%\pidcmd.txt" 2>nul
echo                      该进程命令行：
type "%WORK%\pidcmd.txt" 2>nul

REM 是本项目上次启动的残留就自动清掉；不是就交给用户决定
findstr /i /c:"%SVC_MODULE%" "%WORK%\pidcmd.txt" >nul 2>nul
if not errorlevel 1 goto ES_KILL
echo.
choice /c YN /n /t 30 /d N /m "                      这不是本项目的进程，仍要结束它吗? Y=结束 N=跳过 "
if errorlevel 2 goto ES_SKIP

:ES_KILL
echo                      [自动] 正在结束该占用进程 ...
taskkill /PID %SVC_PID% /F >nul 2>nul
ping -n 3 127.0.0.1 >nul
goto ES_START

:ES_SKIP
echo                      [跳过] 未处理占用进程。若服务确实没起来，请手动关掉占用 %SVC_PORT% 的程序后重跑本脚本。
set "SVC_RESULT=skipped"
exit /b 1

:ES_ALIVE
echo               [复用] 服务已在运行，不重复启动
set "SVC_RESULT=reused"
set "REUSED=%REUSED% %SVC_LABEL%"
exit /b 0

:ES_START
echo               正在启动 ...
start "%SVC_TITLE%" cmd /k %PY% -m %SVC_MODULE%
call :WAIT_HTTP "%SVC_PROBE%" 60
if errorlevel 1 goto ES_NOTREADY
echo               [就绪] %SVC_PROBE%
set "SVC_RESULT=started"
set "STARTED=%STARTED% %SVC_LABEL%"
exit /b 0

:ES_NOTREADY
echo               [失败] 等待超时，服务没有起来，请看标题为「%SVC_TITLE%」的黑窗口
set "SVC_RESULT=failed"
set "FAILED=%FAILED% %SVC_LABEL%"
exit /b 1


REM ----------------------------------------------------------------
REM  等 Docker 引擎就绪：最多 60 轮 × 约 3 秒 ≈ 3 分钟
REM ----------------------------------------------------------------
:WAIT_ENGINE
set /a WE_N=0
:WE_LOOP
ping -n 4 127.0.0.1 >nul
docker info >nul 2>nul
if not errorlevel 1 exit /b 0
set /a WE_N+=1
if %WE_N% lss 60 goto WE_LOOP
exit /b 1


REM ----------------------------------------------------------------
REM  等容器健康：milvus-standalone 与 mongo 都要 healthy，最多 90 轮 × 3 秒
REM ----------------------------------------------------------------
:WAIT_CONTAINERS
set /a HC_N=0
:HC_LOOP
set "HC_M=unknown"
for /f "usebackq delims=" %%i in (`docker inspect -f "{{.State.Health.Status}}" milvus-standalone 2^>nul`) do set "HC_M=%%i"
set "HC_D=unknown"
for /f "usebackq delims=" %%i in (`docker inspect -f "{{.State.Health.Status}}" mongo 2^>nul`) do set "HC_D=%%i"
if /i "%HC_M%"=="healthy" if /i "%HC_D%"=="healthy" exit /b 0
set /a HC_N+=1
if %HC_N% gtr 90 goto HC_SLOW
ping -n 3 127.0.0.1 >nul
goto HC_LOOP
:HC_SLOW
echo         [警告] 等待超时 —— Milvus=%HC_M%  MongoDB=%HC_D%
exit /b 1


REM ----------------------------------------------------------------
REM  等 HTTP 就绪
REM    入参：%1 = 探测地址   %2 = 最大轮数（每轮约 2 秒）
REM ----------------------------------------------------------------
:WAIT_HTTP
set "WH_URL=%~1"
set "WH_MAX=%~2"
set /a WH_N=0
:WH_LOOP
ping -n 3 127.0.0.1 >nul
call :PROBE "%WH_URL%"
if not errorlevel 1 exit /b 0
set /a WH_N+=1
if %WH_N% lss %WH_MAX% goto WH_LOOP
exit /b 1


REM ----------------------------------------------------------------
REM  探测一个 HTTP 地址通不通
REM    入参：%1 = 探测地址    返回：0 = 通，1 = 不通
REM ----------------------------------------------------------------
:PROBE
if not defined HAVE_CURL call :DETECT_CURL
if "%HAVE_CURL%"=="1" goto PROBE_CURL
REM 兜底：没有 curl 时用 PowerShell 探测，同样先掐掉系统代理
powershell -NoProfile -Command "[System.Net.WebRequest]::DefaultWebProxy = $null; try { $r = Invoke-WebRequest -Uri '%~1' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) { exit 0 } else { exit 1 } } catch { exit 1 }"
exit /b %errorlevel%
:PROBE_CURL
REM --noproxy "*"：本机若开着 Clash 或设了 http_proxy 环境变量，curl 会把 127.0.0.1 也丢给代理，
REM              代理对 localhost 一律应答失败 —— 就会造成「服务明明是活的、探测却说死了」。
REM               强制绕过代理，探测的才是真后端。
REM -f          ：HTTP 4xx/5xx 也算失败，避免端口被别的程序占着、随手回个 404 被误判成「服务已在运行」。
curl -s -f -o nul --noproxy "*" --max-time 3 "%~1" >nul 2>nul
exit /b %errorlevel%

:DETECT_CURL
set "HAVE_CURL=0"
where curl >nul 2>nul
if not errorlevel 1 set "HAVE_CURL=1"
exit /b 0
