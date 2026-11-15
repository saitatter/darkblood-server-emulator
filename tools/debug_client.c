/* Bounded x86 debugger for the local client. Dumps the loaded image at exit,
 * fatal exceptions, or timeout. Does not patch client instructions. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>

static HANDLE process;
static DWORD base;
static const char *output;
static DWORD client_pid;

static BOOL CALLBACK child_window(HWND w, LPARAM unused) {
    wchar_t text[2048]; (void)unused;
    if(GetWindowTextW(w,text,2048)) {
        char utf8[8192]; WideCharToMultiByte(CP_UTF8,0,text,-1,utf8,sizeof(utf8),NULL,NULL);
        printf("WINDOW %s\n",utf8);
    }
    return TRUE;
}
static BOOL CALLBACK top_window(HWND w, LPARAM unused) {
    DWORD pid; (void)unused; GetWindowThreadProcessId(w,&pid);
    if(pid==client_pid) {child_window(w,0); EnumChildWindows(w,child_window,0);}
    return TRUE;
}

static void dump_image(void) {
    BYTE header[4096]; SIZE_T n; DWORD size; BYTE *data; FILE *f;
    if (!base || !ReadProcessMemory(process, (void*)base, header, sizeof(header), &n)) return;
    size = ((IMAGE_NT_HEADERS*)(header + ((IMAGE_DOS_HEADER*)header)->e_lfanew))->OptionalHeader.SizeOfImage;
    if (!size || size > 128*1024*1024) return;
    data = calloc(1, size);
    for (DWORD off = 0; off < size; off += 4096)
        ReadProcessMemory(process, (void*)(base+off), data+off, min(4096,size-off), &n);
    f = fopen(output, "wb");
    if (f) { fwrite(data, 1, size, f); fclose(f); printf("DUMP base=%08lx size=%08lx path=%s\n",base,size,output); }
    free(data);
}

static void context(DWORD tid) {
    HANDLE t = OpenThread(THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, tid);
    CONTEXT c = {0}; DWORD stack[64] = {0}; SIZE_T n;
    c.ContextFlags = CONTEXT_FULL;
    if (t && GetThreadContext(t, &c)) {
        printf("EIP=%08lx ESP=%08lx EBP=%08lx EAX=%08lx\n",c.Eip,c.Esp,c.Ebp,c.Eax);
        ReadProcessMemory(process,(void*)c.Esp,stack,sizeof(stack),&n);
        for (int i=0;i<64;i++) printf("%08lx%c",stack[i],i%8==7?'\n':' ');
    }
    if(t) CloseHandle(t);
}

int main(int argc, char **argv) {
    STARTUPINFOA si = {sizeof(si)}; PROCESS_INFORMATION pi = {0}; DEBUG_EVENT ev;
    DWORD start, duration = 15000; int dumped = 0;
    if(argc < 4) { fprintf(stderr,"usage: debug_client.exe CLIENT CWD DUMP [milliseconds] [arguments]\n"); return 2; }
    output = argv[3]; if(argc > 4) duration = strtoul(argv[4],NULL,0);
    char command[4096]; _snprintf_s(command,sizeof(command),_TRUNCATE,"\"%s\" %s",argv[1],argc>5?argv[5]:"");
    setvbuf(stdout,NULL,_IONBF,0);
    int normal = getenv("DB_NO_DEBUG") != NULL;
    if(!CreateProcessA(argv[1],command,NULL,NULL,FALSE,normal?0:DEBUG_ONLY_THIS_PROCESS,NULL,argv[2],&si,&pi)) {
        fprintf(stderr,"CreateProcess failed: %lu\n",GetLastError()); return 1;
    }
    process = pi.hProcess; client_pid = pi.dwProcessId; start = GetTickCount();
    if(normal) {
        base=0x400000;
        WaitForSingleObject(process,duration);
        HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE,pi.dwProcessId);
        MODULEENTRY32 me={sizeof(me)};
        if(Module32First(snap,&me)) do {printf("MODULE %p %08lx %s\n",me.modBaseAddr,me.modBaseSize,me.szExePath);} while(Module32Next(snap,&me));
        CloseHandle(snap);
        snap=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
        THREADENTRY32 te={sizeof(te)};
        if(Thread32First(snap,&te)) do {if(te.th32OwnerProcessID==pi.dwProcessId) {
            HANDLE thread=OpenThread(THREAD_SUSPEND_RESUME,FALSE,te.th32ThreadID);
            SuspendThread(thread); context(te.th32ThreadID); ResumeThread(thread); CloseHandle(thread);
        }} while(Thread32Next(snap,&te));
        CloseHandle(snap);
        EnumWindows(top_window,0); dump_image();
        TerminateProcess(process,0); WaitForSingleObject(process,5000);
        CloseHandle(pi.hThread); CloseHandle(process); return 0;
    }
    while(GetTickCount()-start < duration) {
        if(!WaitForDebugEvent(&ev,200)) continue;
        DWORD status=DBG_CONTINUE;
        if(ev.dwDebugEventCode==CREATE_PROCESS_DEBUG_EVENT) {
            base=(DWORD)ev.u.CreateProcessInfo.lpBaseOfImage;
            printf("PROCESS pid=%lu base=%08lx\n",pi.dwProcessId,base);
            if(ev.u.CreateProcessInfo.hFile) CloseHandle(ev.u.CreateProcessInfo.hFile);
        } else if(ev.dwDebugEventCode==LOAD_DLL_DEBUG_EVENT) {
            char path[MAX_PATH]="?";
            if(ev.u.LoadDll.hFile) { GetFinalPathNameByHandleA(ev.u.LoadDll.hFile,path,sizeof(path),0); CloseHandle(ev.u.LoadDll.hFile); }
            printf("DLL %08lx %s\n",(DWORD)ev.u.LoadDll.lpBaseOfDll,path);
        } else if(ev.dwDebugEventCode==EXCEPTION_DEBUG_EVENT) {
            DWORD code=ev.u.Exception.ExceptionRecord.ExceptionCode;
            if(!ev.u.Exception.dwFirstChance || code==EXCEPTION_BREAKPOINT)
                printf("EXCEPTION %08lx at=%p first=%lu tid=%lu\n",code,ev.u.Exception.ExceptionRecord.ExceptionAddress,ev.u.Exception.dwFirstChance,ev.dwThreadId);
            if(code!=EXCEPTION_BREAKPOINT && code!=0x4000001f) {
                if(!ev.u.Exception.dwFirstChance) context(ev.dwThreadId);
                status=DBG_EXCEPTION_NOT_HANDLED;
                if(!ev.u.Exception.dwFirstChance) { dump_image(); dumped=1; }
            }
        } else if(ev.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT) {
            printf("EXIT %08lx\n",ev.u.ExitProcess.dwExitCode);
            ContinueDebugEvent(ev.dwProcessId,ev.dwThreadId,status);
            CloseHandle(pi.hThread); CloseHandle(process); return 0;
        }
        ContinueDebugEvent(ev.dwProcessId,ev.dwThreadId,status);
    }
    printf("TIMEOUT %lu ms\n",duration);
    EnumWindows(top_window,0);
    if(!dumped) dump_image();
    TerminateProcess(process,0);
    while(WaitForDebugEvent(&ev,1000)) {
        ContinueDebugEvent(ev.dwProcessId,ev.dwThreadId,DBG_CONTINUE);
        if(ev.dwDebugEventCode==EXIT_PROCESS_DEBUG_EVENT) break;
    }
    CloseHandle(pi.hThread); CloseHandle(process); return 0;
}
