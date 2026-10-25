/* Linux-only fault injection for output errors delayed until flush or close. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int fail_output(FILE *stream, const char *stage) {
    const char *failure = getenv("ANYBUNDLE_TEST_IO_FAILURE");
    if (!stream || !failure || strcmp(failure, stage) != 0) return 0;
    int fd = fileno(stream);
    int flags = fd > STDERR_FILENO ? fcntl(fd, F_GETFL) : -1;
    return flags >= 0 && (flags & O_ACCMODE) != O_RDONLY;
}

int fflush(FILE *stream) {
    int (*original)(FILE *) = (int (*)(FILE *))dlsym(RTLD_NEXT, "fflush");
    if (!original) { errno = EIO; return EOF; }
    int fail = fail_output(stream, "flush");
    int result = original(stream);
    if (fail && result == 0) { errno = EIO; return EOF; }
    return result;
}

int fclose(FILE *stream) {
    int (*original)(FILE *) = (int (*)(FILE *))dlsym(RTLD_NEXT, "fclose");
    if (!original) { errno = EIO; return EOF; }
    int fail = fail_output(stream, "close");
    int result = original(stream);
    if (fail && result == 0) { errno = EIO; return EOF; }
    return result;
}
