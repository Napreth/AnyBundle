CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra
PYTHON ?= python3
SRC := $(wildcard src/*.c)
HEADERS := $(wildcard src/*.h)

anybundle: $(SRC) $(HEADERS)
	$(CC) $(CFLAGS) -o $@ $(SRC)

.PHONY: generate-template check-template example clean

generate-template:
	$(PYTHON) tools/embed_launcher.py

check-template:
	$(PYTHON) tools/embed_launcher.py --check

example: anybundle
	$(CC) $(CFLAGS) -o examples/hello examples/hello.c
	./anybundle build --name hello --version 0.1.0 --linux-x64 examples/hello -o examples/hello-any-platform.sh.ps1
	sh examples/hello-any-platform.sh.ps1 list
	sh examples/hello-any-platform.sh.ps1 -- one two

clean:
	rm -f anybundle examples/hello examples/hello-any-platform.sh.ps1 examples/hello-unpacked
