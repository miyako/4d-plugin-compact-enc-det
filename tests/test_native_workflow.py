"""Execute real workflow Bash only behind closed-PATH native/credential doubles."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

import yaml

from helper_support import Fixture, ROOT, original, source
import native


WORKFLOW = ROOT / ".github/workflows/release.yml"
PRODUCT = "Compact Encoding Detection"
CONTENTS = native.BUNDLE / "Contents"
STUB = r'''#!PYTHON
import base64, json, os, pathlib, plistlib, shutil, sys
tool, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["NATIVE_LOG"], "a") as out:
    out.write(json.dumps([tool, *args]) + "\n")
if os.environ.get("FAIL_TOOL") == tool:
    sys.exit(23)
product = "Compact Encoding Detection"
contents = pathlib.Path("test/Plugins/Compact Encoding Detection.bundle/Contents")
if tool in ("python", "python3"):
    if args and args[0].endswith("release.py"):
        assert os.environ["GH_TOKEN"] == "offline-only"
        assert os.environ["GITHUB_REPOSITORY"] == "miyako/4d-plugin-compact-enc-det"
        assert args[2:4] == ["--sha", os.environ["GITHUB_SHA"]]
        if args[1] == "publish":
            assert args[4:] == [f"{product}-{os.environ['VERSION']}.zip",
                                f"{product}-{os.environ['VERSION']}.dmg"]
        if os.environ.get("FAIL_PUBLICATION") or (
                args[1] == "preflight" and os.environ.get("FAIL_PREFLIGHT")):
            sys.exit(9)
    else:
        os.execv(sys.executable, [sys.executable, *args])
elif tool == "xcodebuild":
    assert args == ["-project", product + ".xcodeproj", "-target", product,
        "-configuration", "Default", "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO",
        "MACOSX_DEPLOYMENT_TARGET=11.0", "CODE_SIGNING_ALLOWED=NO",
        "CONFIGURATION_BUILD_DIR=" + str(pathlib.Path.cwd() / "test/Plugins"), "build"]
    for relative in ("MacOS/" + product, "Info.plist", "Resources/manifest.json",
                     "Resources/constants.xlf", "Resources/English.lproj/InfoPlist.strings",
                     "_CodeSignature/CodeResources"):
        assert not (contents / relative).exists(), relative
    if not os.environ.get("STALE_BUILD"):
        (contents / "MacOS").mkdir(parents=True, exist_ok=True)
        (contents / "MacOS" / product).write_bytes(b"fresh-macos")
        value = plistlib.loads(pathlib.Path("Info.plist").read_bytes())
        (contents / "Info.plist").write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
        (contents / "Resources/English.lproj").mkdir(parents=True, exist_ok=True)
        target = contents / "Resources/English.lproj/InfoPlist.strings"
        if os.environ.get("COMPILED_STRINGS"):
            sys.path.insert(0, ".github/scripts")
            import source_version
            value = source_version.built_dictionary("English.lproj/InfoPlist.strings")
            target.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
        else:
            target.write_bytes(pathlib.Path("English.lproj/InfoPlist.strings").read_text().encode("utf-16"))
        for resource in ("manifest.json", "constants.xlf"):
            shutil.copyfile(resource, contents / "Resources" / resource)
        db = pathlib.Path("build/XCBuildData")
        db.mkdir(parents=True, exist_ok=True)
        for name in ("build.db", "build.db-wal", "build.db-shm"):
            (db / name).write_bytes(b"fresh-database")
elif tool == "lipo":
    assert args == ["-archs", str(contents / "MacOS" / product)]
    print(os.environ.get("ARCHES", "arm64 x86_64"))
elif tool == "base64":
    pathlib.Path(args[args.index("-o") + 1]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "security":
    if args[0] == "find-identity":
        print("" if os.environ.get("MISSING_IDENTITY") else
              '  1) OFFLINE "Developer ID Application: Fixture"')
elif tool == "codesign":
    if "--verify" in args and os.environ.get("FAIL_VERIFY"):
        sys.exit(7)
    if "--verify" not in args:
        (contents / "_CodeSignature").mkdir(exist_ok=True)
        (contents / "_CodeSignature/CodeResources").write_bytes(b"fresh-signature")
elif tool in ("ditto", "hdiutil"):
    suffix = "zip" if tool == "ditto" else "dmg"
    assert args[-1] == f"{product}-{os.environ['VERSION']}.{suffix}"
    pathlib.Path(args[-1]).write_bytes(b"offline-package")
elif tool == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        print(os.environ.get("NOTARY_JSON", json.dumps({
            "id": "offline-id", "status": os.environ.get("NOTARY_STATUS", "Accepted")})))
        sys.exit(int(os.environ.get("NOTARY_EXIT", "0")))
    elif args[:2] == ["stapler", "staple"]:
        sys.exit(int(os.environ.get("STAPLE_EXIT", "0")))
    else:
        assert args[:2] == ["notarytool", "store-credentials"], args
else:
    sys.exit("Unexpected native tool: " + tool)
'''


class NativeWorkflowTests(Fixture):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.log = self.root / "native.jsonl"
        for tool in ("python", "python3", "xcodebuild", "lipo", "base64",
                     "security", "codesign", "ditto", "hdiutil", "xcrun"):
            path = self.tools / tool
            path.write_text(STUB.replace("PYTHON", sys.executable))
            path.chmod(0o755)
        for tool in ("bash", "grep", "head", "sed"):
            (self.tools / tool).symlink_to(shutil.which(tool))
        version = source.read(ROOT)
        self.env = {
            "PATH": str(self.tools), "HOME": str(self.checkout), "LC_ALL": "C",
            "RUNNER_TEMP": str(self.checkout), "NATIVE_LOG": str(self.log),
            "PRODUCT_NAME": PRODUCT, "BASE_DIR": "test", "VERSION": version,
            "MACOS_DEPLOYMENT_TARGET": "11.0",
            "KEYCHAIN_PATH": str(self.checkout / "offline.keychain"),
            "BUNDLE_PATH": str(native.BUNDLE), "GITHUB_ENV": str(self.checkout / "github-env"),
            "GITHUB_SHA": "a" * 40, "GH_TOKEN": "offline-only",
            "GITHUB_REPOSITORY": "miyako/4d-plugin-compact-enc-det",
            "PYTHONDONTWRITEBYTECODE": "1",
            "CERT_BASE64": "b2ZmbGluZQ==", "CERT_PASSWORD": "offline-only",
            "KEYCHAIN_PASSWORD": "offline-only", "APPLE_ID": "offline@example.invalid",
            "TEAM_ID": "OFFLINEONLY", "APP_PASSWORD": "offline-only",
        }
        shutil.copytree(ROOT / ".github/scripts", self.checkout / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.sources(self.checkout)
        for name in ("manifest.json", "constants.xlf"):
            (self.checkout / name).write_bytes(original(name))
        self.jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
        self.contents = self.checkout / CONTENTS
        self.protected = {}
        for relative in (
            CONTENTS / "QuickLook/Thumbnail.png", CONTENTS / "Resources/custom.txt",
            CONTENTS / "MacOS/runtime.dylib", "test/Plugins/Default/keep",
            "build/unrelated/keep", "a/libced.a", "a/libjsoncpp.a",
            "lib/windows64/ced.lib",
        ):
            target = self.checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"preserved")
            self.protected[target] = b"preserved"
        for relative in native.FILES:
            target = self.checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"stale")
        target = self.checkout / native.DOWNLOADS[0]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"fresh-windows")

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_step(self, job, name, success=True):
        step = next(step for step in self.jobs[job]["steps"] if step.get("name") == name)
        script = step["run"]
        self.assertNotIn("${{", script)
        self.assertEqual(step.get("shell", "bash"), "bash")
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
            cwd=self.checkout, env=self.env, capture_output=True, text=True, timeout=30)
        if success is not None:
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def mac_step(self, name, success=True):
        return self.run_step("build-macos", name, success)

    def build(self):
        self.mac_step("build macOS plugin (universal)")

    def pipeline(self):
        for job in ("version", "build-macos"):
            for step in self.jobs[job]["steps"]:
                if "run" in step:
                    result = self.run_step(job, step["name"], None)
                    if result.returncode:
                        return result
        return result

    def test_complete_real_shell_pipeline_is_fresh_and_publishes_only_after_staple(self):
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path, data in self.protected.items():
            self.assertEqual(path.read_bytes(), data)
        for relative, data in (("MacOS/" + PRODUCT, b"fresh-macos"),
                               ("Windows64/" + PRODUCT + ".4DX", b"fresh-windows"),
                               ("_CodeSignature/CodeResources", b"fresh-signature")):
            self.assertEqual((self.contents / relative).read_bytes(), data)
        calls = self.calls()
        index = lambda test: next(i for i, call in enumerate(calls) if test(call))
        xcode = index(lambda call: call[0] == "xcodebuild")
        sign = index(lambda call: call[0] == "codesign")
        package = index(lambda call: call[0] == "ditto")
        staple = index(lambda call: call[:3] == ["xcrun", "stapler", "staple"])
        publish = index(lambda call: call[0] == "python3" and "publish" in call)
        self.assertLess(xcode, sign)
        self.assertLess(sign, package)
        self.assertLess(package, staple)
        self.assertLess(staple, publish)
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"] for call in calls), 2)
        self.assertTrue(all("--strict" in call and "--deep" in call for call in calls
                            if call[0] == "codesign" and "--verify" in call))

    def test_dynamic_source_version_and_compiled_localization(self):
        before, version = self.env["VERSION"], "3.2.1"
        for path in source.SOURCE_PATHS:
            target = self.checkout / path
            target.write_bytes(target.read_bytes().replace(before.encode(), version.encode()))
        self.env.update(VERSION=version, COMPILED_STRINGS="1")
        self.assertEqual(source.read(self.checkout), version)
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for suffix in ("zip", "dmg"):
            self.assertTrue((self.checkout / f"{PRODUCT}-{version}.{suffix}").is_file())

    def test_cleanup_error_never_reaches_xcode(self):
        path = self.contents / "Info.plist"
        path.unlink()
        path.mkdir()
        self.mac_step("build macOS plugin (universal)", False)
        self.assertFalse(any(call[0] == "xcodebuild" for call in self.calls()))

    def test_missing_empty_stale_binary_and_exact_architecture_tokens(self):
        self.env["STALE_BUILD"] = "1"
        self.build()
        self.mac_step("verify universal binary", False)
        self.env.pop("STALE_BUILD")
        self.build()
        binary = self.contents / "MacOS" / PRODUCT
        binary.write_bytes(b"")
        self.mac_step("verify universal binary", False)
        binary.write_bytes(b"fresh")
        for arches in ("arm64e x86_64", "arm64 x86_64h", ""):
            self.env["ARCHES"] = arches
            self.mac_step("verify universal binary", False)
        self.env["ARCHES"] = "arm64 x86_64 arm64e i386"
        self.mac_step("verify universal binary")

    def test_missing_and_drifted_metadata_localization_and_resources_rejected(self):
        self.build()
        for relative in ("Info.plist", "Resources/English.lproj/InfoPlist.strings",
                         "Resources/constants.xlf", "Resources/manifest.json"):
            path = self.contents / relative
            saved = path.read_bytes()
            for raw in (None, b"", b"drift"):
                with self.subTest(relative=relative, raw=raw):
                    if raw is None:
                        path.unlink()
                    else:
                        path.write_bytes(raw)
                    self.mac_step("verify universal binary", False)
                    path.write_bytes(saved)

    def test_all_credential_native_notary_and_staple_failures_never_publish(self):
        cases = [{"FAIL_TOOL": tool} for tool in (
            "python3", "base64", "security", "xcrun", "xcodebuild", "lipo",
            "codesign", "ditto", "hdiutil",
        )] + [
            {"FAIL_PREFLIGHT": "1"}, {"MISSING_IDENTITY": "1"}, {"FAIL_VERIFY": "1"},
            {"STALE_BUILD": "1"}, {"ARCHES": "arm64e x86_64"},
            {"NOTARY_EXIT": "5", "NOTARY_STATUS": "Accepted"},
            {"NOTARY_STATUS": "Invalid"}, {"NOTARY_STATUS": ""},
            {"NOTARY_JSON": "not json"}, {"NOTARY_JSON": "[]"},
            {"NOTARY_JSON": "{}"}, {"STAPLE_EXIT": "8"},
            {"NOTARY_JSON": '{"status":"Invalid","status":"Accepted"}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":{"id":1,"id":2}}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":NaN}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":-Infinity}'},
            {"NOTARY_JSON": '{"status":"Accepted","extra":1e999}'},
        ]
        env = dict(self.env)
        for case in cases:
            with self.subTest(case=case):
                self.env = {**env, **case}
                self.log.unlink(missing_ok=True)
                for suffix in ("zip", "dmg"):
                    (self.checkout / f"{PRODUCT}-{self.env['VERSION']}.{suffix}").unlink(missing_ok=True)
                result = self.pipeline()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(call[0] == "python3" and "publish" in call
                                     for call in self.calls()))


class NativeWorkflowContractTests(unittest.TestCase):
    def test_exact_dispatch_checkout_environment_concurrency_and_original_topology(self):
        workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        intake = yaml.load(original(".github/workflows/release.yml"), Loader=yaml.BaseLoader)
        self.assertEqual(workflow["name"], "Build")
        self.assertEqual(workflow["on"], {"workflow_dispatch": ""})
        self.assertEqual(workflow["concurrency"],
                         {"group": "source-publication", "cancel-in-progress": "false"})
        for key, value in (("PRODUCT_NAME", PRODUCT), ("BASE_DIR", "test"),
                           ("MACOS_DEPLOYMENT_TARGET", "11.0"), ("GIT_CONFIG_COUNT", "1"),
                           ("GIT_CONFIG_KEY_0", "core.autocrlf"), ("GIT_CONFIG_VALUE_0", "false")):
            self.assertEqual(workflow["env"][key], value)
        self.assertEqual(list(workflow["jobs"]), list(intake["jobs"]))
        for name, job in workflow["jobs"].items():
            self.assertEqual(job["runs-on"], intake["jobs"][name]["runs-on"])
            self.assertEqual(job.get("needs"), intake["jobs"][name].get("needs"))
            self.assertNotIn("if", job)
            checkout = [step for step in job["steps"]
                        if step.get("uses", "").startswith("actions/checkout@")]
            self.assertEqual(len(checkout), 1)
            self.assertEqual(checkout[0]["with"], {"ref": "${{ github.sha }}"})
            for step in job["steps"]:
                self.assertNotIn("if", step)
                self.assertNotIn("${{", step.get("run", ""))
        mac = workflow["jobs"]["build-macos"]["steps"]
        self.assertIn("release.py preflight", mac[1]["run"])
        self.assertIn("release.py publish", mac[-1]["run"])
        for forbidden in ("inputs.", "github.ref", "softprops", "dispatches",
                          "bump.py", "submodules:", "git clone", "brew ", "cmake "):
            self.assertNotIn(forbidden, WORKFLOW.read_text())

    def test_native_projects_archives_and_packaged_resources_are_unchanged(self):
        project = PRODUCT + ".xcodeproj/project.pbxproj"
        normalize = lambda data: re.sub(
            rb"((?:MARKETING_VERSION|CURRENT_PROJECT_VERSION)\s*=\s*)[0-9.]+;",
            rb"\g<1>VERSION;", data)
        self.assertEqual(normalize((ROOT / project).read_bytes()), normalize(original(project)))
        for path in ("a/libced.a", "a/libjsoncpp.a", "lib/windows64/ced.lib",
                     "lib/windows64/jsoncpp.lib", "constants.xlf", "manifest.json",
                     *(str(path) for path in native.FILES),
                     str(native.WINDOWS_BINARY), str(CONTENTS / "QuickLook/Thumbnail.png")):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), original(path))
