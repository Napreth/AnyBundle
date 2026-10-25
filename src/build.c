#ifndef _WIN32
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#else
#ifndef _CRT_RAND_S
#define _CRT_RAND_S
#endif
#endif
#include "anybundle.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <unistd.h>
#endif

typedef struct {
    const char *platform;
    const char *path;
    const char *entry;
    size_t size;
    char sha[65];
    char *data;
    char *b64;
    size_t b64_len;
} Payload;

static int valid_platform_opt(const char *s, const char **platform_out) {
    static const struct { const char *opt; const char *platform; } map[] = {
        {"--win-x64", "win-x64"}, {"--win-x86", "win-x86"}, {"--win-arm64", "win-arm64"},
        {"--linux-x64", "linux-x64"}, {"--linux-x86", "linux-x86"}, {"--linux-arm64", "linux-arm64"},
        {"--macos-x64", "macos-x64"}, {"--macos-arm64", "macos-arm64"},
    };
    for (size_t i = 0; i < sizeof(map)/sizeof(map[0]); ++i) {
        if (strcmp(s, map[i].opt) == 0) { *platform_out = map[i].platform; return 1; }
    }
    return 0;
}

static int is_reserved_windows_name(const char *s) {
    size_t len = strcspn(s, ".");
    while (len && s[len - 1] == ' ') --len;
    if (len < 3 || len > 7) return 0;
    unsigned char stem[8];
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = (unsigned char)s[i];
        stem[i] = c >= 'a' && c <= 'z' ? c - ('a' - 'A') : c;
    }
    stem[len] = 0;
    if (strcmp((const char *)stem, "CON") == 0 || strcmp((const char *)stem, "PRN") == 0 ||
        strcmp((const char *)stem, "AUX") == 0 || strcmp((const char *)stem, "NUL") == 0 ||
        strcmp((const char *)stem, "CONIN$") == 0 || strcmp((const char *)stem, "CONOUT$") == 0) return 1;
    if (memcmp(stem, "COM", 3) != 0 && memcmp(stem, "LPT", 3) != 0) return 0;
    if (len == 4) return (stem[3] >= '1' && stem[3] <= '9') ||
                         stem[3] == 0xb9 || stem[3] == 0xb2 || stem[3] == 0xb3;
    return len == 5 && stem[3] == 0xc2 &&
           (stem[4] == 0xb9 || stem[4] == 0xb2 || stem[4] == 0xb3);
}

static int is_safe_path_component(const char *s) {
    if (!s || !*s || strcmp(s, ".") == 0 || strcmp(s, "..") == 0) return 0;
    if (is_reserved_windows_name(s)) return 0;
    size_t len = strlen(s);
    if (s[len - 1] == '.' || s[len - 1] == ' ') return 0;
    for (; *s; ++s) {
        unsigned char c = (unsigned char)*s;
        if (c < 0x20 || c == 0x7f || strchr("/\\:*?\"<>|", c) != NULL) return 0;
    }
    return 1;
}

#include "launcher_template.h"

static int write_wrapped_b64(FILE *out, const char *b64, size_t len) {
    for (size_t i = 0; i < len; i += 76) {
        size_t chunk = len - i < 76 ? len - i : 76;
        if (fputc('#', out) == EOF) return -1;
        if (ab_write_all(out, b64 + i, chunk) != 0) return -1;
        if (fputc('\n', out) == EOF) return -1;
    }
    return 0;
}

static int write_bundle(FILE *out, const char *name, const char *version, const Payload *payloads, int count) {
    if (ab_write_all(out, launcher_template, sizeof(launcher_template)) != 0 || fputs("#__ANYBUNDLE_MANIFEST_BEGIN__\n", out) == EOF) return -1;
    if (fprintf(out, "#format=anybundle.bundle.v1\n#name=%s\n#version=%s\n#builder=anybundle-%s\n", name, version, AB_VERSION) < 0) return -1;
    for (int i = 0; i < count; ++i) {
        if (fprintf(out, "#platform=%s|%s|%s|%zu|0755\n", payloads[i].platform, payloads[i].entry, payloads[i].sha, payloads[i].size) < 0) return -1;
    }
    if (fputs("#__ANYBUNDLE_MANIFEST_END__\n", out) == EOF) return -1;
    for (int i = 0; i < count; ++i) {
        if (fprintf(out, "#__ANYBUNDLE_PAYLOAD_BEGIN__:%s\n", payloads[i].platform) < 0 ||
            write_wrapped_b64(out, payloads[i].b64, payloads[i].b64_len) != 0 ||
            fputs("#__ANYBUNDLE_PAYLOAD_END__\n", out) == EOF) return -1;
    }
    return 0;
}

static FILE *open_bundle_output(const char *path, char **temporary) {
    *temporary = NULL;
#ifdef _WIN32
    struct _stat64 info;
    wchar_t *wide_path = ab_utf8_to_wide(path);
    if (!wide_path) return NULL;
    int status = _wstat64(wide_path, &info);
    int stat_error = errno;
    free(wide_path);
    errno = stat_error;
    int regular = status == 0 && (info.st_mode & _S_IFMT) == _S_IFREG;
#else
    struct stat info;
    int status = stat(path, &info);
    int regular = status == 0 && S_ISREG(info.st_mode);
#endif
    if (status == 0) {
        if (!regular) return ab_fopen(path, "wb");
    } else if (errno != ENOENT) {
        return NULL;
    }

    size_t len = strlen(path);
    if (len > SIZE_MAX - 32) { errno = ENAMETOOLONG; return NULL; }
    char *tmp = (char *)malloc(len + 32);
    if (!tmp) { errno = ENOMEM; return NULL; }
    int fd = -1;
#ifdef _WIN32
    for (int attempt = 0; attempt < 128; ++attempt) {
        unsigned int first, second;
        if (rand_s(&first) != 0 || rand_s(&second) != 0) { errno = EIO; break; }
        snprintf(tmp, len + 32, "%s.tmp.%08x%08x", path, first, second);
        wchar_t *wide_tmp = ab_utf8_to_wide(tmp);
        if (!wide_tmp) break;
        fd = _wopen(wide_tmp, _O_WRONLY | _O_BINARY | _O_CREAT | _O_EXCL, _S_IREAD | _S_IWRITE);
        int open_error = errno;
        free(wide_tmp);
        errno = open_error;
        if (fd >= 0 || errno != EEXIST) break;
    }
#else
    memcpy(tmp, path, len);
    memcpy(tmp + len, ".tmp.XXXXXX", sizeof(".tmp.XXXXXX"));
    fd = mkstemp(tmp);
#endif
    if (fd < 0) { int error = errno; free(tmp); errno = error; return NULL; }
#ifdef _WIN32
    FILE *out = _fdopen(fd, "wb");
#else
    FILE *out = fdopen(fd, "wb");
#endif
    if (!out) {
        int error = errno;
#ifdef _WIN32
        _close(fd);
#else
        close(fd);
#endif
        ab_remove_file(tmp);
        free(tmp);
        errno = error;
        return NULL;
    }
    *temporary = tmp;
    return out;
}

int ab_build(int argc, char **argv) {
    const char *name = "app";
    const char *version = "0.0.0";
    const char *entry_override = NULL;
    const char *output = NULL;
    Payload payloads[8];
    int count = 0;
    int result = 1;
    char *temporary = NULL;
    memset(payloads, 0, sizeof(payloads));

    for (int i = 0; i < argc; ++i) {
        const char *p = NULL;
        if (strcmp(argv[i], "--name") == 0 && i + 1 < argc) name = argv[++i];
        else if (strcmp(argv[i], "--version") == 0 && i + 1 < argc) version = argv[++i];
        else if (strcmp(argv[i], "--entry") == 0 && i + 1 < argc) entry_override = argv[++i];
        else if ((strcmp(argv[i], "-o") == 0 || strcmp(argv[i], "--output") == 0) && i + 1 < argc) output = argv[++i];
        else if (valid_platform_opt(argv[i], &p) && i + 1 < argc) {
            if (count >= 8) { fprintf(stderr, "anybundle: too many payloads\n"); return 2; }
            for (int j = 0; j < count; ++j) {
                if (strcmp(payloads[j].platform, p) == 0) {
                    fprintf(stderr, "anybundle: duplicate platform: %s\n", p);
                    return 2;
                }
            }
            payloads[count].platform = p;
            payloads[count].path = argv[++i];
            count++;
        } else {
            fprintf(stderr, "anybundle: bad or incomplete option: %s\n", argv[i]);
            return 2;
        }
    }
    if (!output) { fprintf(stderr, "anybundle: missing -o OUTPUT\n"); return 2; }
    if (count == 0) { fprintf(stderr, "anybundle: provide at least one platform payload\n"); return 2; }
    if (!is_safe_path_component(name)) { fprintf(stderr, "anybundle: name must be a safe single path component\n"); return 2; }
    if (!is_safe_path_component(version)) { fprintf(stderr, "anybundle: version must be a safe single path component\n"); return 2; }

    for (int i = 0; i < count; ++i) {
        payloads[i].entry = entry_override ? entry_override : ab_basename(payloads[i].path);
        if (!is_safe_path_component(payloads[i].entry)) { fprintf(stderr, "anybundle: entry must be a safe single path component\n"); return 2; }
    }
    for (int i = 0; i < count; ++i) {
        payloads[i].data = ab_read_file(payloads[i].path, &payloads[i].size);
        if (!payloads[i].data) goto cleanup;
        ab_sha256_hex((const uint8_t *)payloads[i].data, payloads[i].size, payloads[i].sha);
        payloads[i].b64 = ab_base64_encode((const uint8_t *)payloads[i].data, payloads[i].size, &payloads[i].b64_len);
        if (!payloads[i].b64) { fprintf(stderr, "anybundle: out of memory\n"); goto cleanup; }
    }

    FILE *out = open_bundle_output(output, &temporary);
    if (!out) { fprintf(stderr, "anybundle: cannot write %s: %s\n", output, strerror(errno)); goto cleanup; }
    int error = write_bundle(out, name, version, payloads, count) == 0 ? 0 : (errno ? errno : EIO);
    if (fflush(out) != 0 && !error) error = errno ? errno : EIO;
    if (ferror(out) && !error) error = EIO;
#ifndef _WIN32
    if (!error && temporary && fchmod(fileno(out), 0755) != 0) error = errno ? errno : EIO;
#endif
    if (fclose(out) != 0 && !error) error = errno ? errno : EIO;
    if (error) {
        fprintf(stderr, "anybundle: cannot write %s: %s\n", output, strerror(error));
        goto cleanup;
    }
    if (temporary) {
#ifndef _WIN32
        if (rename(temporary, output) != 0) {
            fprintf(stderr, "anybundle: cannot replace %s: %s\n", output, strerror(errno));
            goto cleanup;
        }
#else
        wchar_t *wide_tmp = ab_utf8_to_wide(temporary);
        if (!wide_tmp) { fprintf(stderr, "anybundle: cannot replace %s: %s\n", output, strerror(errno)); goto cleanup; }
        wchar_t *wide_output = ab_utf8_to_wide(output);
        if (!wide_output) { free(wide_tmp); fprintf(stderr, "anybundle: cannot replace %s: %s\n", output, strerror(errno)); goto cleanup; }
        int moved = MoveFileExW(wide_tmp, wide_output, MOVEFILE_REPLACE_EXISTING);
        DWORD move_error = GetLastError();
        free(wide_output); free(wide_tmp);
        if (!moved) {
            fprintf(stderr, "anybundle: cannot replace %s: Windows error %lu\n", output, (unsigned long)move_error);
            goto cleanup;
        }
#endif
    }
    fprintf(stderr, "anybundle: wrote %s with %d payload(s)\n", output, count);
    result = 0;
cleanup:
    if (temporary) {
        if (result != 0 && ab_remove_file(temporary) != 0) fprintf(stderr, "anybundle: cannot remove temporary output %s: %s\n", temporary, strerror(errno));
        free(temporary);
    }
    for (int i = 0; i < count; ++i) { free(payloads[i].data); free(payloads[i].b64); }
    return result;
}
