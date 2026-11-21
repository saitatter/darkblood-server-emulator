@echo off
setlocal
pushd "%~dp0"
echo [*] Building modular client proxy DLL (steam_api.dll)...
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat" >nul || goto fail
if exist steam_api.dll del /q steam_api.dll
cl.exe /nologo /LD /MD /O1 ^
    steam_api_hook.c ^
    common.c ^
    patches\network_redirect.c ^
    patches\borderless_fullscreen.c ^
    patches\auto_reconnect.c ^
    patches\peer_update_interval.c ^
    patches\skip_logos.c ^
    patches\skip_tutorial_always.c ^
    patches\diagnostic_hooks.c ^
    patches\debug_tools.c ^
    /Fe:steam_api.dll ws2_32.lib user32.lib || goto fail
echo [+] Built steam_api.dll successfully.
popd
exit /b 0
:fail
echo [!] Build failed.
popd
exit /b 1
