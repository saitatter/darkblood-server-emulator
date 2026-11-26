@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
if errorlevel 1 exit /b 1
if not exist research mkdir research
cl /nologo /W4 /O2 tools\reverse\debug_client.c /Fo:research\debug_client.obj /Fe:research\debug_client.exe user32.lib
exit /b %errorlevel%
