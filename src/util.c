#include "anybundle.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <wchar.h>
#include <windows.h>

wchar_t *ab_utf8_to_wide(const char *text) {
    int length = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
    if (!length) { errno = EINVAL; return NULL; }
    wchar_t *wide = (wchar_t *)malloc((size_t)length * sizeof(*wide));
    if (!wide) { errno = ENOMEM; return NULL; }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, wide, length)) {
        free(wide); errno = EINVAL; return NULL;
    }
    return wide;
}

char *ab_wide_to_utf8(const wchar_t *text) {
    int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, -1, NULL, 0, NULL, NULL);
    if (!length) { errno = EINVAL; return NULL; }
    char *utf8 = (char *)malloc((size_t)length);
    if (!utf8) { errno = ENOMEM; return NULL; }
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, -1, utf8, length, NULL, NULL)) {
        free(utf8); errno = EINVAL; return NULL;
    }
    return utf8;
}
#endif

FILE *ab_fopen(const char *path, const char *mode) {
#ifdef _WIN32
    wchar_t *wide_path = ab_utf8_to_wide(path);
    if (!wide_path) return NULL;
    wchar_t *wide_mode = ab_utf8_to_wide(mode);
    if (!wide_mode) { free(wide_path); return NULL; }
    FILE *file = _wfopen(wide_path, wide_mode);
    int error = errno;
    free(wide_mode); free(wide_path);
    errno = error;
    return file;
#else
    return fopen(path, mode);
#endif
}

int ab_remove_file(const char *path) {
#ifdef _WIN32
    wchar_t *wide = ab_utf8_to_wide(path);
    if (!wide) return -1;
    int result = _wremove(wide);
    int error = errno;
    free(wide);
    errno = error;
    return result;
#else
    return remove(path);
#endif
}

char *ab_strdup(const char *s) {
    size_t n = strlen(s) + 1;
    char *p = (char *)malloc(n);
    if (p) memcpy(p, s, n);
    return p;
}

const char *ab_basename(const char *path) {
    const char *a = strrchr(path, '/');
    const char *b = strrchr(path, '\\');
    const char *p = a;
    if (b && (!p || b > p)) p = b;
    return p ? p + 1 : path;
}

char *ab_read_file(const char *path, size_t *size_out) {
    FILE *f = ab_fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "anybundle: cannot open %s: %s\n", path, strerror(errno));
        return NULL;
    }
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long n = ftell(f);
    if (n < 0) { fclose(f); return NULL; }
    rewind(f);
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t got = fread(buf, 1, (size_t)n, f);
    fclose(f);
    if (got != (size_t)n) {
        free(buf);
        fprintf(stderr, "anybundle: short read: %s\n", path);
        return NULL;
    }
    buf[got] = 0;
    if (size_out) *size_out = got;
    return buf;
}

int ab_write_all(FILE *f, const void *buf, size_t n) {
    return fwrite(buf, 1, n, f) == n ? 0 : -1;
}

char *ab_shell_single_quote(const char *s) {
    size_t len = 2;
    for (const char *p = s; *p; ++p) len += (*p == '\'') ? 4 : 1;
    char *out = (char *)malloc(len + 1);
    if (!out) return NULL;
    char *q = out;
    *q++ = '\'';
    for (const char *p = s; *p; ++p) {
        if (*p == '\'') { memcpy(q, "'\\''", 4); q += 4; }
        else *q++ = *p;
    }
    *q++ = '\'';
    *q = 0;
    return out;
}
