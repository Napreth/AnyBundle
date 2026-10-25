#ifndef ANYBUNDLE_H
#define ANYBUNDLE_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define AB_VERSION "1.0.0"

char *ab_read_file(const char *path, size_t *size_out);
FILE *ab_fopen(const char *path, const char *mode);
int ab_remove_file(const char *path);
#ifdef _WIN32
wchar_t *ab_utf8_to_wide(const char *text);
char *ab_wide_to_utf8(const wchar_t *text);
#endif
int ab_write_all(FILE *f, const void *buf, size_t n);
const char *ab_basename(const char *path);
char *ab_strdup(const char *s);
void ab_sha256_hex(const uint8_t *data, size_t len, char out_hex[65]);
char *ab_base64_encode(const uint8_t *data, size_t len, size_t *out_len);
char *ab_shell_single_quote(const char *s);
int ab_build(int argc, char **argv);
void ab_print_help(FILE *out);

#endif
