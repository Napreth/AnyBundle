#!/usr/bin/env sh
set -eu
cc -std=c11 -O2 -Wall -Wextra -o anybundle ../src/*.c
cc -std=c11 -O2 -Wall -Wextra -o hello hello.c
./anybundle build --name hello --version 0.1.0 --linux-x64 ./hello -o hello-any-platform.sh.ps1
sh ./hello-any-platform.sh.ps1 list
sh ./hello-any-platform.sh.ps1 -- one two
sh ./hello-any-platform.sh.ps1 unpack -o ./hello-unpacked
./hello-unpacked unpacked
