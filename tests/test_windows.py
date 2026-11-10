"""Execute actual workflow PowerShell with a closed PATH; pin original CMD."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml

from helper_support import Fixture, ROOT, original
import native


PWSH = "/usr/local/bin/pwsh"
OUTPUT = native.WINDOWS_BINARY
WORKFLOW = ROOT / ".github/workflows/release.yml"
MSBUILD = (
    'msbuild "%PRODUCT_NAME%.sln" /p:Configuration=Release /p:Platform=x64 '
    '/p:PlatformToolset=v143 /p:WindowsTargetPlatformVersion=10.0 /m'
)


class WindowsTests(Fixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(Path(PWSH).is_file(), "PowerShell is mandatory, not a skipped test")
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.log = self.root / "windows.jsonl"
        python = self.tools / "python"
        python.write_text(f"""#!{sys.executable}
import json, os, sys
assert sys.argv[1:] == [".github/scripts/release.py", "preflight", "--sha", os.environ["GITHUB_SHA"]]
assert os.environ["GH_TOKEN"] == "offline-only"
with open(os.environ["WINDOWS_LOG"], "a") as out:
    out.write(json.dumps(sys.argv[1:]) + "\\n")
sys.exit(9 if os.environ.get("FAIL_PREFLIGHT") else 0)
""")
        python.chmod(0o755)
        (self.tools / "python3").symlink_to(python.name)
        self.env = {
            "PATH": str(self.tools), "HOME": str(self.root),
            "WINDOWS_LOG": str(self.log), "PRODUCT_NAME": native.PRODUCT,
            "BASE_DIR": "test", "GITHUB_SHA": "a" * 40, "GH_TOKEN": "offline-only",
            "POWERSHELL_TELEMETRY_OPTOUT": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        }
        self.file(".github/scripts/windows.ps1",
                  (ROOT / ".github/scripts/windows.ps1").read_bytes())
        self.file(OUTPUT, b"stale committed plugin")
        self.file("Objs/Release/nested/old.obj", b"stale intermediate")
        self.protected = {}
        for path in (
            native.BUNDLE / "Contents/QuickLook/Thumbnail.png",
            native.BUNDLE / "Contents/Resources/custom.txt",
            native.BUNDLE / "Contents/MacOS" / native.PRODUCT,
            native.BUNDLE / "Contents/Windows/other.4DX",
            native.BUNDLE / "Contents/Windows64/other.lib",
            "test/Plugins/Default/keep", "test/Plugins/Other.bundle/keep",
            "Objs/Debug/keep", "lib/windows64/ced.lib",
        ):
            target = self.file(path, b"preserved")
            self.protected[target] = b"preserved"

    def file(self, relative, data):
        target = self.checkout / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    def powershell(self, script, success=True):
        script = ("$ErrorActionPreference = 'Stop'\n" + script +
                  "\nif (Test-Path variable:LASTEXITCODE) { exit $LASTEXITCODE }")
        result = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=self.checkout, env=self.env, text=True, capture_output=True, timeout=30)
        if success is not None:
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def phase(self, phase, success=True, prefix=""):
        return self.powershell(prefix + f"\n& ./.github/scripts/windows.ps1 -Phase {phase}",
                               success)

    def assert_preserved(self):
        for path, data in self.protected.items():
            self.assertEqual(path.read_bytes(), data)

    def test_selective_cleanup_and_exact_committed_casing(self):
        self.phase("prepare")
        self.phase("prepare")
        self.assertFalse((self.checkout / OUTPUT).exists())
        self.assertFalse((self.checkout / "Objs/Release").exists())
        self.assert_preserved()
        self.file(OUTPUT, b"fresh")
        self.phase("collect")
        self.assertEqual((self.checkout / "winbin" / OUTPUT.name).read_bytes(), b"fresh")
        self.assert_preserved()

    def test_missing_empty_or_wrong_location_never_falls_back_to_first_match(self):
        self.phase("prepare")
        self.file("unrelated/Windows64/" + OUTPUT.name, b"misleading candidate")
        self.phase("collect", False)
        self.file(OUTPUT, b"")
        self.phase("collect", False)
        self.assertFalse((self.checkout / "winbin").exists())

    def test_symlink_ancestors_nested_dangling_and_samebyte_output_are_rejected(self):
        outside = self.file("outside/keep", b"stale committed plugin")
        for relative in (OUTPUT, Path("Objs/Release/nested/link"),
                         Path("Objs/Release/nested/dangling")):
            with self.subTest(relative=relative):
                path = self.checkout / relative
                old = path.read_bytes() if path.exists() else None
                path.unlink(missing_ok=True)
                path.symlink_to(self.checkout / "absent" if path.name == "dangling" else outside)
                self.phase("prepare", False)
                self.assertTrue((self.checkout / "Objs/Release/nested/old.obj").is_file())
                path.unlink()
                if old is not None:
                    path.write_bytes(old)
        plugins = self.checkout / "test/Plugins"
        moved = self.checkout / "outside-plugins"
        plugins.rename(moved)
        plugins.symlink_to(moved, target_is_directory=True)
        self.phase("prepare", False)
        self.assertEqual((self.checkout / OUTPUT).read_bytes(), b"stale committed plugin")
        self.assertEqual(outside.read_bytes(), b"stale committed plugin")

    def test_reparse_attribute_and_cleanup_io_failure_are_fatal_before_deletion(self):
        self.phase("prepare", False, prefix=(
            "function Get-Item { param($LiteralPath, [switch]$Force)\n"
            " $item = Microsoft.PowerShell.Management\\Get-Item -LiteralPath $LiteralPath -Force\n"
            " if ($item.FullName.EndsWith('Objs/Release')) { "
            "return [pscustomobject]@{ FullName=$item.FullName; "
            "Attributes=[IO.FileAttributes]::ReparsePoint; PSIsContainer=$true } }; $item\n}"
        ))
        self.assertEqual((self.checkout / OUTPUT).read_bytes(), b"stale committed plugin")
        self.phase("prepare", False, prefix="function Remove-Item { throw 'offline denied' }")
        self.assertTrue((self.checkout / "Objs/Release/nested/old.obj").exists())

    def test_staging_reparse_or_unexpected_leaf_is_not_overwritten(self):
        outside = self.file("outside/keep", b"untouched")
        link = self.file("winbin/" + OUTPUT.name, b"old")
        link.unlink()
        link.symlink_to(outside)
        self.phase("collect", False)
        self.assertEqual(outside.read_bytes(), b"untouched")
        link.unlink()
        self.file("winbin/evil.dll", b"unknown")
        self.phase("collect", False)
        self.assertFalse(link.exists())

    def workflow(self, fresh=True, empty=False, cleanup_failure=False):
        steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build-windows"]["steps"]
        build = upload = False
        for step in steps:
            if "run" in step:
                script = step["run"]
                if step.get("shell") == "cmd":
                    self.assertEqual(script.strip(), MSBUILD)
                    self.assertFalse((self.checkout / OUTPUT).exists())
                    self.assertFalse((self.checkout / "Objs/Release").exists())
                    build = True
                    if fresh:
                        self.file(OUTPUT, b"" if empty else b"fresh workflow plugin")
                    continue
                self.assertNotIn("${{", script)
                if cleanup_failure and "-Phase prepare" in script:
                    script = "function Remove-Item { throw 'offline denied' }\n" + script
                if step.get("shell") == "bash":
                    result = subprocess.run(
                        ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                        cwd=self.checkout, env=self.env, text=True, capture_output=True, timeout=30)
                else:
                    result = self.powershell(script, None)
                if result.returncode:
                    return False, build, upload
            elif step.get("uses", "").startswith("actions/upload-artifact@"):
                upload = True
                self.assertEqual(step["with"]["path"].rstrip("/"), "winbin")
                self.assertEqual(step["with"]["if-no-files-found"], "error")
        return True, build, upload

    def test_actual_workflow_powershell_collects_fresh_artifact(self):
        self.assertEqual(self.workflow(), (True, True, True))
        self.assertEqual((self.checkout / "winbin" / OUTPUT.name).read_bytes(),
                         b"fresh workflow plugin")
        self.assert_preserved()

    def test_workflow_preflight_cleanup_missing_and_empty_fail_without_upload(self):
        self.env["FAIL_PREFLIGHT"] = "1"
        self.assertEqual(self.workflow(), (False, False, False))
        del self.env["FAIL_PREFLIGHT"]
        self.assertEqual(self.workflow(cleanup_failure=True), (False, False, False))
        self.assertEqual(self.workflow(fresh=False), (False, True, False))
        self.assertEqual(self.workflow(empty=True), (False, True, False))

    def test_original_cmd_and_vcxproj_output_topology_preserved(self):
        current = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build-windows"]
        intake = yaml.safe_load(original(".github/workflows/release.yml"))["jobs"]["build-windows"]
        cmd = lambda job: next(step for step in job["steps"] if step.get("shell") == "cmd")
        self.assertEqual(cmd(current), cmd(intake))
        self.assertEqual(current["runs-on"], "windows-latest")
        project = ET.fromstring(original(native.PRODUCT + ".vcxproj"))
        ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
        outdir = [node.text for node in project.findall(".//m:OutDir", ns)
                  if node.get("Condition") == "'$(Configuration)|$(Platform)'=='Release|x64'"]
        self.assertEqual(outdir, [
            "$(ProjectDir)test\\plugins\\$(ProjectName).bundle\\contents\\windows64\\"])
        self.assertEqual((ROOT / (native.PRODUCT + ".vcxproj")).read_bytes(),
                         original(native.PRODUCT + ".vcxproj"))
        self.assertEqual((ROOT / (native.PRODUCT + ".sln")).read_bytes(),
                         original(native.PRODUCT + ".sln"))
