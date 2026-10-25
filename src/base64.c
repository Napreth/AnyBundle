#include "anybundle.h"
#include <stdlib.h>

static const char table[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

char *ab_base64_encode(const uint8_t *data, size_t len, size_t *out_len) {
    size_t olen = 4 * ((len + 2) / 3);
    char *out = (char *)malloc(olen + 1);
    if (!out) return NULL;
    size_t i = 0, j = 0;
    while (i < len) {
        uint32_t a = i < len ? data[i++] : 0;
        uint32_t b = i < len ? data[i++] : 0;
        uint32_t c = i < len ? data[i++] : 0;
        uint32_t triple = (a << 16) | (b << 8) | c;
        out[j++] = table[(triple >> 18) & 63];
        out[j++] = table[(triple >> 12) & 63];
        out[j++] = table[(triple >> 6) & 63];
        out[j++] = table[triple & 63];
    }
    size_t mod = len % 3;
    if (mod) {
        out[olen - 1] = '=';
        if (mod == 1) out[olen - 2] = '=';
    }
    out[olen] = 0;
    if (out_len) *out_len = olen;
    return out;
}
