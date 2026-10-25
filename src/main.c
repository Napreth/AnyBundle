#include "anybundle.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#ifdef _MSC_VER
#pragma comment(lib, "shell32.lib")
#endif
#endif

void ab_print_help(FILE *out) {
    fprintf(out,
        "AnyBundle %s\n"
        "\n"
        "Build one sh/PowerShell polyglot self-extracting launcher containing\n"
        "native payloads for Windows, Linux, and macOS.\n"
        "\n"
        "Usage:\n"
        "  anybundle build [options] -o OUTPUT.sh.ps1\n"
        "  anybundle --help\n"
        "\n"
        "Build options:\n"
        "  --name NAME              Bundle/application name\n"
        "  --version VERSION        Bundle/application version\n"
        "  --entry NAME             Entry file name after extraction; defaults to input basename\n"
        "  --win-x64 FILE           Windows x64 payload\n"
        "  --win-x86 FILE           Windows x86 payload\n"
        "  --win-arm64 FILE         Windows ARM64 payload\n"
        "  --linux-x64 FILE         Linux x64 payload\n"
        "  --linux-x86 FILE         Linux x86 payload\n"
        "  --linux-arm64 FILE       Linux ARM64 payload\n"
        "  --macos-x64 FILE         macOS x64 payload\n"
        "  --macos-arm64 FILE       macOS ARM64 payload\n"
        "  -o, --output FILE         Output polyglot .sh.ps1 file\n"
        "\n"
        "Generated bundle usage:\n"
        "  sh ./app-any-platform.sh.ps1 list\n"
        "  sh ./app-any-platform.sh.ps1 -- arg1 arg2\n"
        "  powershell ./app-any-platform.sh.ps1 -- arg1 arg2\n"
        "  powershell ./app-any-platform.sh.ps1 unpack -o app.exe --platform win-x64\n",
        AB_VERSION);
}

static int ab_main(int argc, char **argv) {
    if (argc < 2 || strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0) {
        ab_print_help(stdout);
        return argc < 2 ? 1 : 0;
    }
    if (strcmp(argv[1], "--version") == 0 || strcmp(argv[1], "version") == 0) {
        puts(AB_VERSION);
        return 0;
    }
    if (strcmp(argv[1], "build") == 0) {
        return ab_build(argc - 2, argv + 2);
    }
    fprintf(stderr, "anybundle: unknown command: %s\n\n", argv[1]);
    ab_print_help(stderr);
    return 2;
}

int main(int argc, char **argv) {
#ifdef _WIN32
    wchar_t **wide = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!wide) { fputs("anybundle: cannot read Unicode command line\n", stderr); return 1; }
    argv = (char **)calloc((size_t)argc + 1, sizeof(*argv));
    if (!argv) { LocalFree(wide); fputs("anybundle: out of memory\n", stderr); return 1; }
    int result = 1;
    for (int i = 0; i < argc; ++i) {
        argv[i] = ab_wide_to_utf8(wide[i]);
        if (!argv[i]) { fputs("anybundle: cannot convert command line to UTF-8\n", stderr); goto cleanup; }
    }
    result = ab_main(argc, argv);
cleanup:
    for (int i = 0; i < argc; ++i) free(argv[i]);
    free(argv);
    LocalFree(wide);
    return result;
#else
    return ab_main(argc, argv);
#endif
}
