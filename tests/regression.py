"""Exercise built bundles through a real Shell or PowerShell process."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--builder", required=True, type=Path)
parser.add_argument("--payload", required=True, type=Path)
parser.add_argument("--shell", choices=("sh", "bash", "powershell"), required=True)
parser.add_argument("--runtime", help="Interpreter executable; defaults to --shell")
parser.add_argument("--io-fault-library", type=Path, default=os.environ.get("ANYBUNDLE_TEST_IO_FAULT_LIBRARY"),
                    help="Optional Linux shared library for delayed output error tests")
OPTIONS, remaining = parser.parse_known_args()
OPTIONS.builder = OPTIONS.builder.resolve()
OPTIONS.payload = OPTIONS.payload.resolve()
if OPTIONS.io_fault_library:
    OPTIONS.io_fault_library = OPTIONS.io_fault_library.resolve()


class BundleRegression(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="anybundle-test-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name).resolve()
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.temp = self.root / "temp"
        self.temp.mkdir()
        self.cache = self.root / "cache"
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.cache),
                        LOCALAPPDATA=str(self.cache), TMPDIR=str(self.temp),
                        TEMP=str(self.temp), TMP=str(self.temp), NO_COLOR="1")
        # Let each PowerShell edition discover its own standard modules.
        for key in list(self.env):
            if key.lower() == "psmodulepath":
                del self.env[key]
        arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64",
                "arm64": "arm64", "i386": "x86", "i686": "x86",
                "x86": "x86"}[platform.machine().lower()]
        system = {"Windows": "win", "Linux": "linux", "Darwin": "macos"}
        self.native = system[platform.system()] + "-" + arch
        self.other = "linux-arm64" if self.native != "linux-arm64" else "win-x64"

    def command(self, argv, success=True, env=None):
        result = subprocess.run([str(a) for a in argv], cwd=self.root,
                                env=env or self.env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=90)
        output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return result

    def build(self, *options, payloads=None, filename="bundle.sh.ps1", success=True):
        bundle = self.root / filename
        payloads = payloads or [(self.native, OPTIONS.payload)]
        argv = [OPTIONS.builder, "build", "--name", "regression", "--version", "1.2.3"]
        for key, path in payloads:
            argv.extend(["--" + key, path])
        result = self.command([*argv, *options, "-o", bundle], success=success)
        if not success:
            self.assertFalse(bundle.exists())
            return result
        return bundle

    def launch(self, bundle, *args, success=True, env=None):
        runtime = OPTIONS.runtime or OPTIONS.shell
        prefix = [runtime]
        if OPTIONS.shell == "powershell":
            prefix += ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
        return self.command([*prefix, bundle, *args], success=success, env=env)

    def rewrite(self, bundle, transform):
        original = bundle.read_text(encoding="utf-8")
        changed = transform(original)
        self.assertNotEqual(original, changed)
        with bundle.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(changed)

    def assert_temp_clean(self):
        self.assertEqual(list(self.temp.iterdir()), [])

    def cache_root(self, base=None):
        base = base or self.cache
        return base / "AnyBundle" / "cache" if OPTIONS.shell == "powershell" else base / "anybundle"

    def directory_link(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            env = dict(self.env, AB_TEST_LINK=str(link), AB_TEST_TARGET=str(target))
            self.command([OPTIONS.runtime or "powershell", "-NoProfile", "-NonInteractive", "-Command",
                          "$ErrorActionPreference='Stop'; New-Item -ItemType Junction "
                          "-Path $env:AB_TEST_LINK -Target $env:AB_TEST_TARGET | Out-Null"], env=env)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_reject_unsafe_build_components(self):
        for option in ("--name", "--version", "--entry"):
            for value in ("", ".", "..", "../../../side-cache", "..\\side-cache",
                          "bad|field", "bad\nline", "bad\rline", "bad\tfield",
                          "C:drive", "bad?name", "bad*name", 'bad"name',
                          "bad<name", "bad>name", ".. ", "trailing.", "bad\x7f"):
                with self.subTest(option=option, value=value):
                    result = self.build(option, value, success=False)
                    self.assertIn("safe single path component", result.stderr)

    def test_reject_duplicate_platform(self):
        self.build(payloads=[(self.native, OPTIONS.payload),
                             (self.native, OPTIONS.payload)], success=False)

    def test_reject_windows_reserved_components(self):
        names = ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
        names += [prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)]
        names += [prefix + digit for prefix in ("COM", "LPT") for digit in ("\u00b9", "\u00b2", "\u00b3")]
        for option in ("--name", "--version", "--entry"):
            for name in names:
                for value in (name, name.lower() + ".txt", name + " .tar.gz"):
                    with self.subTest(option=option, value=value):
                        result = self.build(option, value, success=False)
                        self.assertIn("safe single path component", result.stderr)

    def test_allow_names_containing_reserved_words(self):
        for value in ("console", "NULL", "COM10", "LPT10", "my.CON", "COM1-helper", "NULdata"):
            with self.subTest(value=value):
                self.build("--name", value, "--version", value, "--entry", value)

    def test_runtime_rejects_reserved_components(self):
        for key, old in (("name", "#name=regression"), ("version", "#version=1.2.3"),
                         ("entry", "|" + OPTIONS.payload.name + "|")):
            for value in ("nUl.txt", "CoM\u00b9.dat"):
                with self.subTest(key=key, value=value):
                    bundle = self.build()
                    replacement = "|" + value + "|" if key == "entry" else "#" + key + "=" + value
                    self.rewrite(bundle, lambda text: text.replace(old, replacement, 1))
                    result = self.launch(bundle, "run", success=False)
                    self.assertIn("unsafe", result.stdout + result.stderr)
                    self.assertFalse(self.cache.exists())
                    result = self.launch(bundle, "verify", success=False)
                    self.assertIn("invalid manifest", result.stdout + result.stderr)

    @unittest.skipUnless(Path("/dev/full").exists() and os.name == "posix", "requires /dev/full")
    def test_build_reports_device_write_failure(self):
        for data in (b"", bytes(range(256)) * 100):
            with self.subTest(size=len(data)):
                payload = self.root / "payload.bin"
                payload.write_bytes(data)
                result = self.command([OPTIONS.builder, "build", "--linux-x64", payload,
                                       "-o", "/dev/full"], success=False)
                self.assertNotIn("anybundle: wrote", result.stderr)
                self.assertIn("/dev/full", result.stderr)
                self.assertIn("write", result.stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX file size limits")
    def test_build_write_failure_preserves_output(self):
        import resource
        def limit_file_size():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))
        output = self.root / "keep.sh.ps1"
        for existing in (True, False):
            with self.subTest(existing=existing):
                if existing:
                    output.write_bytes(b"keep existing bundle")
                result = subprocess.run([str(OPTIONS.builder), "build", "--" + self.native,
                                         str(OPTIONS.payload), "-o", str(output)],
                                        cwd=self.root, env=self.env, capture_output=True,
                                        text=True, timeout=30, preexec_fn=limit_file_size)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("write", result.stderr)
                self.assertNotIn("anybundle: wrote", result.stderr)
                if existing:
                    self.assertEqual(output.read_bytes(), b"keep existing bundle")
                    output.unlink()
                else:
                    self.assertFalse(output.exists())
                self.assertEqual(list(self.root.glob("*.tmp.*")), [])

    @unittest.skipUnless(os.name == "nt", "Windows file sharing semantics")
    def test_build_replacement_failure_preserves_output(self):
        unicode_dir = self.root / "\u4e2d\u6587-\U0001f600"
        unicode_dir.mkdir()
        for output in (self.root / "locked.sh.ps1", unicode_dir / "\u51fa\u529b.sh.ps1"):
            with self.subTest(output=output):
                output.write_bytes(b"keep existing bundle")
                with output.open("rb"):
                    result = self.command([OPTIONS.builder, "build", "--" + self.native,
                                           OPTIONS.payload, "-o", output], success=False)
                self.assertIn("cannot replace", result.stderr)
                self.assertNotIn("anybundle: wrote", result.stderr)
                self.assertEqual(output.read_bytes(), b"keep existing bundle")
                self.assertEqual(list(self.root.rglob("*.tmp.*")), [])

    @unittest.skipUnless(platform.system() == "Linux" and OPTIONS.io_fault_library,
                         "requires Linux I/O fault injection library")
    def test_build_reports_flush_and_close_failures(self):
        self.assertTrue(OPTIONS.io_fault_library.is_file())
        output = self.root / "keep.sh.ps1"
        for stage in ("flush", "close"):
            for existing in (True, False):
                with self.subTest(stage=stage, existing=existing):
                    if existing:
                        output.write_bytes(b"keep existing bundle")
                    env = dict(self.env, LD_PRELOAD=str(OPTIONS.io_fault_library),
                               ANYBUNDLE_TEST_IO_FAILURE=stage)
                    result = self.command([OPTIONS.builder, "build", "--" + self.native,
                                           OPTIONS.payload, "-o", output], success=False, env=env)
                    self.assertIn("cannot write", result.stderr)
                    self.assertNotIn("anybundle: wrote", result.stderr)
                    if existing:
                        self.assertEqual(output.read_bytes(), b"keep existing bundle")
                        output.unlink()
                    else:
                        self.assertFalse(output.exists())
                    self.assertEqual(list(self.root.glob("*.tmp.*")), [])

    def test_build_replaces_existing_output(self):
        output = self.root / "bundle.sh.ps1"
        output.write_bytes(b"previous bundle")
        bundle = self.build()
        self.assertTrue(bundle.read_bytes().startswith(b"#!/usr/bin/env sh\n"))
        self.assertEqual(list(self.root.glob("*.tmp.*")), [])
        self.assertIn("OK " + self.native, self.launch(bundle, "verify").stdout)

    def test_unicode_input_output_and_manifest(self):
        for directory, entry in (("\u4e2d\u6587 \u76ee\u5f55", "\u7a0b\u5e8f.exe"),
                                 ("\u65e5\u672c\u8a9e\u306e\u30d1\u30b9", "\u5b9f\u884c.exe"),
                                 ("unicode-\U0001f600-\U00020bb7", "app-\U0001f600.exe")):
            with self.subTest(directory=directory):
                folder = self.root / directory
                folder.mkdir()
                source = folder / entry
                source.write_bytes(OPTIONS.payload.read_bytes())
                output = folder / "\u5e94\u7528 [literal].sh.ps1"
                output.write_bytes(b"previous bundle")
                bundle = self.build("--name", "\u5e94\u7528-\U0001f600", "--version", "\u7248\u672c1",
                                    payloads=[(self.native, source)], filename=str(output))
                manifest = bundle.read_text(encoding="utf-8")
                self.assertIn("#name=\u5e94\u7528-\U0001f600\n", manifest)
                self.assertIn("#version=\u7248\u672c1\n", manifest)
                self.assertIn("|" + entry + "|", manifest)
                self.assertIn("OK " + self.native, self.launch(bundle, "verify").stdout)
                unpacked = folder / "\u89e3\u5305-\U0001f600.exe"
                self.launch(bundle, "unpack", "-o", unpacked)
                self.assertEqual(unpacked.read_bytes(), source.read_bytes())
                self.assertIn("argc=1", self.launch(bundle, "run").stdout)
                self.launch(bundle, "clean-cache")
                self.assertEqual(list(self.root.rglob("*.tmp.*")), [])

    def test_embedded_launcher_matches_template(self):
        template = Path(__file__).resolve().parents[1] / "templates" / "launcher.sh.ps1"
        expected = template.read_text(encoding="utf-8").encode("utf-8")
        bundle = self.build()
        self.assertTrue(bundle.read_bytes().startswith(expected + b"#__ANYBUNDLE_MANIFEST_BEGIN__\n"))

    def test_entry_order_is_independent(self):
        early = self.root / "early.sh.ps1"
        self.command([OPTIONS.builder, "build", "--name", "regression", "--version", "1.2.3",
                      "--entry", "custom-name", "--" + self.native, OPTIONS.payload,
                      "--" + self.other, OPTIONS.payload, "-o", early])
        late = self.build("--entry", "custom-name", payloads=[
            (self.native, OPTIONS.payload), (self.other, OPTIONS.payload)])
        self.assertEqual(early.read_bytes(), late.read_bytes())
        self.assertIn("|custom-name|", late.read_text(encoding="utf-8"))

    def test_info_list_verify_and_unpack(self):
        bundle = self.build(payloads=[(self.native, OPTIONS.payload),
                                      (self.other, OPTIONS.payload)])
        self.assertIn("name=regression", self.launch(bundle, "info").stdout)
        self.assertIn(self.other, self.launch(bundle, "list").stdout)
        verified = self.launch(bundle, "verify").stdout
        self.assertIn("OK " + self.native, verified)
        self.assertIn("OK " + self.other, verified)
        output = "unpacked [literal] payload.bin"
        self.launch(bundle, "unpack", "--platform", self.other, "-o", output)
        self.assertEqual((self.root / output).read_bytes(), OPTIONS.payload.read_bytes())
        self.assert_temp_clean()

    def test_corrupt_first_payload_reports_all_platforms(self):
        bundle = self.build(payloads=[(self.native, OPTIONS.payload),
                                      (self.other, OPTIONS.payload)])
        marker = "#__ANYBUNDLE_PAYLOAD_BEGIN__:" + self.native + "\n#"
        self.rewrite(bundle, lambda s: s.replace(marker, marker + "AAAA", 1))
        result = self.launch(bundle, "verify", success=False)
        self.assertIn("FAIL " + self.native, result.stdout)
        self.assertIn("OK " + self.other, result.stdout)
        self.assert_temp_clean()

    def test_invalid_base64_reports_all_platforms(self):
        bundle = self.build(payloads=[(self.native, OPTIONS.payload),
                                      (self.other, OPTIONS.payload)])
        marker = "#__ANYBUNDLE_PAYLOAD_BEGIN__:" + self.native + "\n#"
        self.rewrite(bundle, lambda s: s.replace(marker, marker + "!", 1))
        result = self.launch(bundle, "verify", success=False)
        self.assertIn("FAIL " + self.native, result.stdout)
        self.assertIn("OK " + self.other, result.stdout)
        self.assert_temp_clean()

    def test_corrupt_unpack_preserves_existing_output(self):
        bundle = self.build()
        marker = "#__ANYBUNDLE_PAYLOAD_BEGIN__:" + self.native + "\n#"
        self.rewrite(bundle, lambda s: s.replace(marker, marker + "AAAA", 1))
        output = self.root / "keep [literal].bin"
        output.write_bytes(b"keep existing data")
        self.launch(bundle, "unpack", "-o", output, success=False)
        self.assertEqual(output.read_bytes(), b"keep existing data")
        self.assertEqual(list(self.root.glob("*.tmp.*")), [])

    def test_empty_payload(self):
        empty = self.root / "empty.bin"
        empty.touch()
        bundle = self.build(payloads=[(self.native, empty)])
        self.assertIn("OK " + self.native, self.launch(bundle, "verify").stdout)
        empty.unlink()
        self.launch(bundle, "unpack")
        self.assertEqual(empty.read_bytes(), b"")
        self.assert_temp_clean()

    def test_missing_or_incomplete_empty_block_fails(self):
        empty = self.root / "empty.bin"
        empty.touch()
        for marker in ("#__ANYBUNDLE_PAYLOAD_BEGIN__:" + self.native,
                       "#__ANYBUNDLE_PAYLOAD_END__"):
            with self.subTest(marker=marker):
                bundle = self.build(payloads=[(self.native, empty)])
                self.rewrite(bundle, lambda s: s.replace(marker + "\n", "", 1))
                result = self.launch(bundle, "verify", success=False)
                self.assertIn("invalid manifest", result.stdout + result.stderr)
                self.assert_temp_clean()

    def test_verify_rejects_empty_manifest(self):
        for keep_payload in (True, False):
            with self.subTest(keep_payload=keep_payload):
                bundle = self.build()
                def remove_platforms(text):
                    text = re.sub(r"^#platform=.*\n", "", text, flags=re.M)
                    if not keep_payload:
                        text = re.sub(r"^#__ANYBUNDLE_PAYLOAD_BEGIN__:.*?^#__ANYBUNDLE_PAYLOAD_END__\n",
                                      "", text, flags=re.M | re.S)
                    return text
                self.rewrite(bundle, remove_platforms)
                result = self.launch(bundle, "verify", success=False)
                self.assertIn("invalid manifest", result.stdout + result.stderr)
                self.assert_temp_clean()

    def test_verify_rejects_malformed_structure(self):
        bundle = self.build()
        original = bundle.read_text(encoding="utf-8")
        declaration = next(line for line in original.splitlines(True) if line.startswith("#platform="))
        block = re.search(r"^#__ANYBUNDLE_PAYLOAD_BEGIN__:.*?^#__ANYBUNDLE_PAYLOAD_END__\n",
                          original, re.M | re.S).group()
        variants = {
            "missing begin": original.replace("#__ANYBUNDLE_MANIFEST_BEGIN__\n", "", 1),
            "missing end": original.replace("#__ANYBUNDLE_MANIFEST_END__\n", "", 1),
            "duplicate manifest": original + "#__ANYBUNDLE_MANIFEST_BEGIN__\n",
            "duplicate platform": original.replace(declaration, declaration * 2, 1),
            "duplicate payload": original + block,
            "missing payload": original.replace(block, "", 1),
            "orphan payload": original + block.replace(":" + self.native, ":" + self.other, 1),
            "unexpected end": original + "#__ANYBUNDLE_PAYLOAD_END__\n",
            "nested payload": original.replace(block, block.splitlines()[0] + "\n" + block, 1),
            "payload before manifest": block + original.replace(block, "", 1),
            "duplicate metadata": original.replace("#name=regression\n", "#name=regression\n" * 2, 1),
            "missing metadata": original.replace("#version=1.2.3\n", "", 1),
            "wrong format": original.replace("#format=anybundle.bundle.v1", "#format=unknown", 1),
        }
        for case, text in variants.items():
            with self.subTest(case=case):
                with bundle.open("w", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
                result = self.launch(bundle, "verify", success=False)
                self.assertIn("invalid manifest", result.stdout + result.stderr)
                self.assert_temp_clean()

    def test_verify_rejects_invalid_platform_metadata(self):
        bundle = self.build()
        original = bundle.read_text(encoding="utf-8")
        declaration = next(line for line in original.splitlines() if line.startswith("#platform="))
        for field, value in ((0, "#platform=unknown"), (1, "../outside"), (2, "bad-hash"),
                             (3, "not-a-size"), (4, "0777")):
            with self.subTest(field=field, value=value):
                fields = declaration.split("|")
                fields[field] = value
                self.rewrite(bundle, lambda _: original.replace(declaration, "|".join(fields), 1))
                result = self.launch(bundle, "verify", success=False)
                self.assertIn("invalid manifest", result.stdout + result.stderr)
                self.assert_temp_clean()

    def test_verify_rejects_wrong_payload_size(self):
        bundle = self.build(payloads=[(self.native, OPTIONS.payload), (self.other, OPTIONS.payload)])
        declaration = next(line for line in bundle.read_text().splitlines() if line.startswith("#platform="))
        fields = declaration.split("|")
        fields[3] = str(int(fields[3]) + 1)
        self.rewrite(bundle, lambda text: text.replace(declaration, "|".join(fields), 1))
        result = self.launch(bundle, "verify", success=False)
        self.assertIn("FAIL " + self.native, result.stdout)
        self.assertIn("OK " + self.other, result.stdout)
        self.assert_temp_clean()

    def test_unpack_creates_output_parent_directories(self):
        bundle = self.build()
        output = Path("nested [literal]") / "new parent" / "payload.bin"
        self.launch(bundle, "unpack", "-o", output)
        self.assertEqual((self.root / output).read_bytes(), OPTIONS.payload.read_bytes())
        self.assertEqual(list(self.root.rglob("*.tmp.*")), [])

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX symlink attack")
    def test_unpack_ignores_predictable_temp_symlink(self):
        bundle = self.build()
        output = self.root / "out"
        victim = self.root / "victim.txt"
        victim.write_bytes(b"do not change")
        runtime = str(Path(shutil.which(OPTIONS.runtime or OPTIONS.shell)).resolve())
        self.command([runtime, "-c", 'ln -s "$2" "$1.tmp.$$"; exec "$3" "$4" unpack -o "$1"',
                      "symlink-test", output, victim, runtime, bundle])
        self.assertEqual(victim.read_bytes(), b"do not change")
        self.assertFalse(output.is_symlink())
        self.assertEqual(output.read_bytes(), OPTIONS.payload.read_bytes())
        links = list(self.root.glob("out.tmp.*"))
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].is_symlink())

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX permission bits")
    def test_new_cache_permissions_follow_umask(self):
        bundle = self.build()
        runtime = str(Path(shutil.which(OPTIONS.runtime or OPTIONS.shell)).resolve())
        for mask in (0o000, 0o002, 0o022, 0o027, 0o077):
            with self.subTest(umask=oct(mask)):
                case_root = self.cache / str(mask)
                base = case_root / "nested"
                env = dict(self.env, XDG_CACHE_HOME=str(base))
                self.command([runtime, "-c", 'umask "$1"; exec "$2" "$3" run',
                              "permissions-test", format(mask, "03o"), runtime, bundle], env=env)
                cached, = base.rglob(OPTIONS.payload.name)
                self.assertEqual(cached.read_bytes(), OPTIONS.payload.read_bytes())
                for path in (case_root, *case_root.rglob("*")):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o777 & ~mask, str(path))

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX permission bits")
    def test_unpack_permissions_follow_umask(self):
        bundle = self.build()
        runtime = str(Path(shutil.which(OPTIONS.runtime or OPTIONS.shell)).resolve())
        for mask in (0o000, 0o002, 0o022, 0o027, 0o077):
            with self.subTest(umask=oct(mask)):
                case_root = self.root / ("unpack-" + str(mask))
                output = case_root / "nested" / "payload.bin"
                self.command([runtime, "-c", 'umask "$1"; exec "$2" "$3" unpack -o "$4"',
                              "permissions-test", format(mask, "03o"), runtime, bundle, output])
                self.assertEqual(output.read_bytes(), OPTIONS.payload.read_bytes())
                for path in (case_root, output.parent, output):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o777 & ~mask, str(path))

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX permission bits")
    def test_existing_cache_directories_keep_permissions(self):
        bundle = self.build()
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()[:16]
        cache_root = self.cache_root()
        leaf = cache_root / "regression" / "1.2.3" / digest / self.native
        leaf.mkdir(parents=True)
        directories = [cache_root, *sorted(cache_root.rglob("*"))]
        modes = (0o775, 0o750, 0o777)
        expected = {}
        for index, directory in enumerate(directories):
            directory.chmod(modes[index % len(modes)])
            expected[directory] = directory.stat().st_mode & 0o777
        self.assertIn("argc=1", self.launch(bundle, "run").stdout)
        for directory, mode in expected.items():
            self.assertEqual(directory.stat().st_mode & 0o777, mode, str(directory))
        self.launch(bundle, "clean-cache")
        self.assertEqual(cache_root.stat().st_mode & 0o777, expected[cache_root])

    def test_cache_accepts_linked_directories(self):
        bundle = self.build()
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()[:16]
        parts = list(self.cache_root().relative_to(self.cache).parts)
        parts += ["regression", "1.2.3", digest, self.native]
        for index in range(len(parts)):
            with self.subTest(component=parts[index]):
                base = self.cache / str(index)
                outside = self.root / ("linked-storage-" + str(index))
                outside.mkdir()
                mode = outside.stat().st_mode & 0o777
                link = base.joinpath(*parts[:index + 1])
                self.directory_link(link, outside)
                env = dict(self.env, XDG_CACHE_HOME=str(base), LOCALAPPDATA=str(base))
                for _ in range(2):
                    self.assertIn("argc=1", self.launch(bundle, "run", env=env).stdout)
                payloads = list(outside.rglob(OPTIONS.payload.name))
                self.assertEqual(len(payloads), 1)
                self.assertEqual(payloads[0].read_bytes(), OPTIONS.payload.read_bytes())
                self.assertTrue(link.is_dir())
                if os.name == "posix":
                    self.assertEqual(outside.stat().st_mode & 0o777, mode)

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX cache symlinks")
    def test_cache_accepts_symlinked_payload_and_repairs_bad_link(self):
        bundle = self.build()
        self.launch(bundle, "run")
        cached, = self.cache.rglob(OPTIONS.payload.name)
        cached.unlink()
        external = self.root / "external-payload"
        shutil.copyfile(OPTIONS.payload, external)
        external.chmod(0o755)
        cached.symlink_to(external)
        self.assertIn("argc=1", self.launch(bundle, "run").stdout)
        self.assertTrue(cached.is_symlink())
        external.write_bytes(b"damaged external payload")
        self.assertIn("argc=1", self.launch(bundle, "run").stdout)
        self.assertFalse(cached.is_symlink())
        self.assertEqual(cached.read_bytes(), OPTIONS.payload.read_bytes())
        self.assertEqual(external.read_bytes(), b"damaged external payload")

    def test_clean_cache_respects_directory_links(self):
        bundle = self.build()
        for position in ("root", "application", "nested"):
            with self.subTest(position=position):
                base = self.cache / position
                env = dict(self.env, XDG_CACHE_HOME=str(base), LOCALAPPDATA=str(base))
                cache_root = self.cache_root(base)
                application = cache_root / "regression"
                outside = self.root / ("storage-" + position)
                outside.mkdir()
                victim = outside / "unrelated.txt"
                victim.write_bytes(b"do not delete")
                if position == "root":
                    self.directory_link(cache_root, outside)
                    self.assertIn("argc=1", self.launch(bundle, "run", env=env).stdout)
                elif position == "application":
                    self.directory_link(application, outside)
                else:
                    self.assertIn("argc=1", self.launch(bundle, "run", env=env).stdout)
                    self.directory_link(application / "linked [literal]", outside)
                sibling = cache_root / "another-app" / "keep.txt"
                sibling.parent.mkdir(parents=True)
                sibling.write_bytes(b"keep sibling")
                self.launch(bundle, "clean-cache", env=env)
                self.assertFalse(os.path.lexists(application))
                self.assertEqual(victim.read_bytes(), b"do not delete")
                self.assertEqual(sibling.read_bytes(), b"keep sibling")
                self.assertTrue(outside.is_dir())
                self.assertTrue(cache_root.is_dir())
                self.launch(bundle, "clean-cache", env=env)

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX signals")
    def test_unpack_cleans_temp_file_after_termination(self):
        bundle = self.build()
        tools = self.root / "tools"
        tools.mkdir()
        decoder = tools / "base64"
        decoder.write_text('#!/bin/sh\nif [ "$1" = --help ]; then echo "-d"; exit; fi\n'
                           ': > "$AB_TEST_READY"\nwhile :; do sleep 1; done\n')
        decoder.chmod(0o700)
        ready = self.root / "ready"
        env = dict(self.env, PATH=str(tools) + os.pathsep + self.env["PATH"], AB_TEST_READY=str(ready))
        runtime = str(Path(shutil.which(OPTIONS.runtime or OPTIONS.shell)).resolve())
        process = subprocess.Popen([runtime, str(bundle), "unpack", "-o", "out"],
                                   cwd=self.root, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "decoder was not reached")
            self.assertEqual(len(list(self.root.glob("out.tmp.*"))), 1)
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(list(self.root.glob("out.tmp.*")), [])
            self.assertFalse((self.root / "out").exists())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)

    def test_runtime_rejects_manifest_traversal(self):
        for key, old in (("name", "#name=regression"),
                         ("version", "#version=1.2.3"),
                         ("entry", "|" + OPTIONS.payload.name + "|")):
            for value in ("../../outside", "..\\outside", ".. "):
                with self.subTest(key=key, value=value):
                    bundle = self.build()
                    replacement = "|" + value + "|" if key == "entry" else "#" + key + "=" + value
                    self.rewrite(bundle, lambda s: s.replace(old, replacement, 1))
                    result = self.launch(bundle, "run", success=False)
                    self.assertIn("unsafe", result.stdout + result.stderr)
                    self.assertFalse(self.cache.exists())
                    if key == "entry":
                        self.launch(bundle, "unpack", success=False)
                    if key == "name":
                        self.launch(bundle, "clean-cache", success=False)

    def test_run_argument_forwarding_cache_and_cleanup(self):
        bundle = self.build()
        args = ["with spaces", "--flag", "*", "semi;colon"]
        for prefix in (("--",), ("run", "--"), ("run",)):
            with self.subTest(prefix=prefix):
                result = self.launch(bundle, *prefix, *args)
                self.assertIn("argc=5", result.stdout)
                for index, value in enumerate(args, 1):
                    self.assertIn("argv[{}]={}".format(index, value), result.stdout)
        for prefix in ((), ("run",), ("run", "--")):
            with self.subTest(prefix=prefix):
                self.assertIn("argc=1", self.launch(bundle, *prefix).stdout)
        cached = list(self.cache.rglob(OPTIONS.payload.name))
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].read_bytes(), OPTIONS.payload.read_bytes())
        cached[0].write_bytes(b"damaged cache")
        self.assertIn("argc=1", self.launch(bundle, "run").stdout)
        self.assertEqual(cached[0].read_bytes(), OPTIONS.payload.read_bytes())
        self.launch(bundle, "clean-cache")
        self.assertFalse(cached[0].exists())

    def test_run_preserves_special_arguments(self):
        bundle = self.build()
        args = ["", 'embedded"quote', "trailing\\", 'slash\\"quote', "two words\\"]
        result = self.launch(bundle, "run", "--", *args)
        self.assertIn("argc=6", result.stdout)
        for index, value in enumerate(args, 1):
            self.assertIn("argv[{}]={}\n".format(index, value), result.stdout)

    def test_payload_exit_status(self):
        bundle = self.build(payloads=[(self.native, OPTIONS.builder)])
        result = self.launch(bundle, "--", "unknown-command", success=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    @unittest.skipIf(OPTIONS.shell == "powershell", "POSIX hash command lookup")
    def test_missing_sha256_tools_fails(self):
        bundle = self.build()
        tools = self.root / "tools"
        tools.mkdir()
        # Keep extraction tools available, while intentionally hiding both hash tools.
        runtime = str(Path(shutil.which(OPTIONS.runtime or OPTIONS.shell)).resolve())
        for name in ("awk", "base64", "grep", "mktemp", "rm", "mv", "chmod", "cut", "uname", "mkdir", "wc"):
            target = shutil.which(name)
            self.assertIsNotNone(target, name)
            (tools / name).symlink_to(target)
        env = dict(self.env, PATH=str(tools))
        result = self.command([runtime, bundle, "verify"], success=False, env=env)
        self.assertIn("FAIL " + self.native, result.stdout)
        self.assert_temp_clean()


if __name__ == "__main__":
    unittest.main(argv=[__file__, *remaining])
