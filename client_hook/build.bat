@echo off
echo [*] Building client proxy DLL (steam_api.dll)...
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat"
cl.exe /LD /MD steam_api_hook.c /Fe:steam_api.dll ws2_32.lib
if %ERRORLEVEL% EQU 0 (
    echo [+] Built steam_api.dll successfully.
) else (
    echo [!] Build failed.
)
