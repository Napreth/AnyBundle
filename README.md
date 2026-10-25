# AnyBundle

AnyBundle builds a single **sh / PowerShell polyglot self-extracting launcher** that can carry native payloads for Windows, Linux, and macOS.

Run the generated `.sh.ps1` file with POSIX sh or PowerShell:

```sh
sh ./myapp-any-platform.sh.ps1 -- --version
./myapp-any-platform.sh.ps1 list
```

```powershell
powershell ./myapp-any-platform.sh.ps1 -- --version
powershell ./myapp-any-platform.sh.ps1 unpack -o myapp.exe --platform win-x64
```

## What it is

A generated bundle contains:

- a small polyglot launcher;
- a text manifest;
- base64 payload blocks, one per platform.

At runtime it detects the current platform, extracts the matching payload to a cache, verifies SHA-256, and executes it.

Supported platform keys:

- `win-x64`
- `win-x86`
- `win-arm64`
- `linux-x64`
- `linux-x86`
- `linux-arm64`
- `macos-x64`
- `macos-arm64`

## Build AnyBundle

```sh
cc -std=c11 -O2 -Wall -Wextra -o anybundle src/*.c
```

On Windows with MSVC Developer Prompt:

```bat
cl /O2 /Fe:anybundle.exe src\*.c
```

## Build a universal bundle

```sh
./anybundle build \
  --name myapp \
  --version 1.0.0 \
  --win-x64 ./dist/myapp-win-x64.exe \
  --win-x86 ./dist/myapp-win-x86.exe \
  --win-arm64 ./dist/myapp-win-arm64.exe \
  --linux-x64 ./dist/myapp-linux-x64 \
  --linux-x86 ./dist/myapp-linux-x86 \
  --linux-arm64 ./dist/myapp-linux-arm64 \
  --macos-x64 ./dist/myapp-macos-x64 \
  --macos-arm64 ./dist/myapp-macos-arm64 \
  -o myapp-v1.0.0-any-platform.sh.ps1
```

Include the platforms you want to distribute. `--name` and `--version` identify the application. Each extracted file uses its input basename; use `--entry NAME` to choose a common filename for all payloads. Run `anybundle --help` for the full option list.

## Generated bundle commands

```text
bundle.sh.ps1 [command] [options] [-- payload-args]
```

Commands:

- `run` — extract current platform payload and execute it. This is the default.
- `--` — shorthand for default run; everything after it goes to the inner program.
- `unpack` — extract a payload and do not run it.
- `list` — list embedded platforms.
- `info` — print the embedded manifest.
- `verify` — extract and hash-check all embedded payloads.
- `clean-cache` — remove this application's cached files.

On POSIX systems, the cache is stored under `$XDG_CACHE_HOME/anybundle` or `$HOME/.cache/anybundle`. On Windows, it is stored under `%LOCALAPPDATA%\AnyBundle\cache`, with `%TEMP%\AnyBundle\cache` as the fallback.

Examples:

```sh
sh ./myapp-any-platform.sh.ps1 run -- --help
sh ./myapp-any-platform.sh.ps1 unpack -o ./myapp --platform linux-x64
sh ./myapp-any-platform.sh.ps1 verify
sh ./myapp-any-platform.sh.ps1 clean-cache
```

```powershell
powershell ./myapp-any-platform.sh.ps1 run -- --help
powershell ./myapp-any-platform.sh.ps1 unpack -o .\myapp.exe --win-x64
```

## Bundle AnyBundle itself

AnyBundle can package its own native binaries using the same build command:

```sh
cd build/dist
./anybundle-v1.0.0-linux-x64 build \
  --name anybundle \
  --version 1.0.0 \
  --win-x64 ./anybundle-v1.0.0-win-x64.exe \
  --linux-x64 ./anybundle-v1.0.0-linux-x64 \
  --macos-arm64 ./anybundle-v1.0.0-macos-arm64 \
  -o anybundle-v1.0.0-any-platform.sh.ps1
```

Then use the bundle directly:

```powershell
powershell ./anybundle-v1.0.0-any-platform.sh.ps1 -- build --win-x64 xxx.exe -o xxx-any-platform.sh.ps1
```

Or unpack a native binary:

```powershell
powershell ./anybundle-v1.0.0-any-platform.sh.ps1 unpack -o anybundle.exe --win-x64
powershell ./anybundle-v1.0.0-any-platform.sh.ps1 unpack -o anybundle --linux-x64
```

## Runtime requirements

- Linux and macOS: POSIX sh, standard command-line utilities, `base64` or `openssl`, and `sha256sum` or `shasum`.
- Windows: Windows PowerShell 5.1 or PowerShell 7. Use `powershell` or `pwsh` to run the bundle.

Payloads are stored as Base64, which adds about 33% to their size before compression. Each payload must be built for its target platform and include or otherwise provide its runtime dependencies.

## Development

The launcher template is `templates/launcher.sh.ps1`. After editing it, regenerate the C resource:

```sh
python3 tools/embed_launcher.py
python3 tools/embed_launcher.py --check
```

### Tests

Build the example payload, then run the suite with Python 3:

```sh
make anybundle
cc -std=c11 -O2 -Wall -Wextra -o examples/hello examples/hello.c
python3 tests/regression.py --builder ./anybundle --payload examples/hello --shell sh -v
python3 tests/regression.py --builder ./anybundle --payload examples/hello --shell bash -v
```

On Windows, after building `anybundle.exe`:

```powershell
cl /O2 /Fe:hello.exe examples\hello.c
python tests/regression.py --builder .\anybundle.exe --payload .\hello.exe --shell powershell --runtime powershell -v
python tests/regression.py --builder .\anybundle.exe --payload .\hello.exe --shell powershell --runtime pwsh -v
```

GitHub Actions runs the test suite on Linux, macOS, and Windows.
