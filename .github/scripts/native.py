"""Rebuild only proven native outputs; retain every packaged sibling."""

import argparse
from pathlib import Path, PurePosixPath
import re
import shutil
import stat


PRODUCT = "Compact Encoding Detection"
PRODUCT_NAME = PRODUCT
BASE_DIR = "test"
BASE = Path(BASE_DIR) / "Plugins"
BUNDLE = BASE / (PRODUCT + ".bundle")
FILES = tuple(BUNDLE / relative for relative in (
    f"Contents/MacOS/{PRODUCT}", "Contents/Info.plist",
    "Contents/Resources/English.lproj/InfoPlist.strings",
    "Contents/Resources/constants.xlf", "Contents/Resources/manifest.json",
    "Contents/_CodeSignature/CodeResources",
))
WINDOWS_NAMES = (PRODUCT + ".4DX",)
WINDOWS_BINARY = BUNDLE / "Contents/Windows64" / WINDOWS_NAMES[0]
WINDOWS = WINDOWS_BINARY
DOWNLOADS = tuple(Path("winbuild") / name for name in WINDOWS_NAMES)
GENERATED_FILES = (*FILES, WINDOWS_BINARY, *DOWNLOADS)
XCODE_DATA = Path("build/XCBuildData")
DIRECTORIES = (
    Path("build") / (PRODUCT + ".build"),
    Path("build/Default") / (PRODUCT + ".build"),
    BASE / (PRODUCT + ".build"),
    BASE / "Default" / (PRODUCT + ".build"),
)


def generated(path):
    path = str(path)
    if "\\" in path or PurePosixPath(path).as_posix() != path \
            or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        return False
    return (path in set(map(str, GENERATED_FILES))
            or bool(re.fullmatch(
                r"build/XCBuildData/(?:build\.db(?:-wal|-shm)?|"
                r"[0-9a-f]{32}\.xcbuilddata/.+)", path))
            or any(path.startswith(str(directory) + "/") for directory in DIRECTORIES))


is_generated = generated


def is_link(path):
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400)


def validate_paths(paths):
    root = Path.cwd().resolve()
    for path in map(Path, paths):
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Output escapes checkout: {path}")
        for parent in reversed((path, *path.parents)):
            if parent == Path("."):
                continue
            try:
                metadata = parent.lstat()
            except FileNotFoundError:
                continue
            if is_link(parent):
                raise ValueError(f"Refusing symlink/reparse output: {parent}")
            if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ValueError(f"Refusing nonregular output: {parent}")
            if parent != path and not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"Expected output ancestor directory: {parent}")
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Output escapes checkout: {path}")
        if path.is_dir():
            for descendant in path.rglob("*"):
                metadata = descendant.lstat()
                if is_link(descendant) or not (
                    stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
                ):
                    raise ValueError(f"Refusing symlink/nonregular output: {descendant}")


def prepare():
    validate_paths((*FILES, *DIRECTORIES, XCODE_DATA))
    for path in FILES:
        if path.is_dir():
            raise ValueError(f"Expected generated file: {path}")
    for path in DIRECTORIES:
        if path.exists() and not path.is_dir():
            raise ValueError(f"Expected intermediate directory: {path}")
    for path in FILES:
        path.unlink(missing_ok=True)
    for path in DIRECTORIES:
        if path.exists():
            shutil.rmtree(path)


def require_file(path):
    path = Path(path)
    validate_paths((path,))
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty native output: {path}")


def validate_outputs():
    validate_paths((*GENERATED_FILES, *DIRECTORIES, XCODE_DATA))
    for path in GENERATED_FILES:
        require_file(path)


def verify_resources():
    for name in ("manifest.json", "constants.xlf"):
        copied = BUNDLE / "Contents/Resources" / name
        require_file(copied)
        require_file(Path(name))
        if copied.read_bytes() != Path(name).read_bytes():
            raise ValueError(f"Copied resource differs from source: {copied}")


def merge_windows():
    validate_paths((*DOWNLOADS, WINDOWS_BINARY))
    for path in DOWNLOADS:
        require_file(path)
    if WINDOWS_BINARY.exists() and not WINDOWS_BINARY.is_file():
        raise ValueError(f"Expected Windows binary file: {WINDOWS_BINARY}")
    WINDOWS_BINARY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DOWNLOADS[0], WINDOWS_BINARY)


def verify_windows():
    require_file(WINDOWS_BINARY)
    require_file(DOWNLOADS[0])
    if WINDOWS_BINARY.read_bytes() != DOWNLOADS[0].read_bytes():
        raise ValueError("Merged Windows payload differs from downloaded artifact")


def validate_built(version):
    import source_version

    for path in FILES[:-1]:
        require_file(path)
    verify_resources()
    if source_version.read() != version:
        raise ValueError("Built version differs from selected immutable source")
    source_version.verify_bundle(BUNDLE)


def validate_assets(version):
    validate_outputs()
    validate_built(version)
    verify_windows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=(
        "clean-macos", "verify-resources", "merge-windows", "built", "assets",
    ))
    phase = parser.parse_args().phase
    if phase == "clean-macos":
        prepare()
    elif phase == "merge-windows":
        merge_windows()
    elif phase == "verify-resources":
        verify_resources()
    else:
        import source_version
        (validate_built if phase == "built" else validate_assets)(source_version.read())
