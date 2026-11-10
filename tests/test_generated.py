"""Only exact native leaves and proven Xcode intermediates gain exemptions."""

import unittest

from helper_support import source
import native


class GeneratedOutputTests(unittest.TestCase):
    def test_exact_native_files_and_controlled_directory_descendants(self):
        for path in (
            *map(str, native.GENERATED_FILES),
            "build/XCBuildData/build.db", "build/XCBuildData/build.db-wal",
            "build/XCBuildData/build.db-shm",
            "build/XCBuildData/0123456789abcdef0123456789abcdef.xcbuilddata/build-request.json",
            *(str(path / "Objects-normal/arm64/main.o") for path in native.DIRECTORIES),
        ):
            with self.subTest(path=path):
                self.assertTrue(native.generated(path))

    def test_unproven_outputs_and_noncanonical_paths_stay_protected(self):
        for path in (
            "test/Plugins/Default/Compact Encoding Detection.bundle/Contents/Info.plist",
            str(native.BUNDLE / "Contents/QuickLook/Thumbnail.png"),
            str(native.BUNDLE / "Contents/MacOS/runtime.dylib"),
            str(native.BUNDLE / "Contents/Resources/custom.txt"),
            str(native.BUNDLE / "Contents/_CodeSignature/evil"),
            "build/XCBuildData-evil/build.db",
            "build/XCBuildData/unexpected-source.cpp",
            "build/XCBuildData/build.db-evil",
            "build/XCBuildData/evil.xcbuilddata/build-request.json",
            "build/XCBuildData/ABCDEF0123456789abcdef0123456789.xcbuilddata/request",
            "build/Compact Encoding Detection.build-evil/injected.cpp",
            "build/unexpected-source.cpp", "a/libced.a", "a/libjsoncpp.a",
            "lib/windows64/ced.lib", "Objs/Debug/keep", "Objs/Release-evil/keep",
            "winbuild/nested/Compact Encoding Detection.4DX",
            "../winbuild/Compact Encoding Detection.4DX",
            "/winbuild/Compact Encoding Detection.4DX",
            "winbuild\\Compact Encoding Detection.4DX",
            "winbuild/../winbuild/Compact Encoding Detection.4DX",
            *map(str, source.SOURCE_PATHS),
        ):
            with self.subTest(path=path):
                self.assertFalse(native.generated(path))
