"""Raw bytes and exact index modes remain mandatory on Windows."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from helper_support import GitFixture, cwd
import repository


class RepositoryTests(GitFixture):
    def test_windows_only_regular_worktree_mode_compatibility(self):
        relative = ".github/hooks/pre-push"
        target = self.local / relative
        raw = target.read_bytes()
        target.chmod(0o644)
        self.git("config", "core.filemode", "false")
        with cwd(self.local):
            with self.assertRaisesRegex(ValueError, "Working source"):
                repository.verify_checkout(self.sha)
            with patch.object(repository, "sys", SimpleNamespace(platform="win32")):
                repository.verify_checkout(self.sha)
                target.write_bytes(raw + b"# raw mutation\n")
                with self.assertRaisesRegex(ValueError, "Working source"):
                    repository.verify_checkout(self.sha)
                target.write_bytes(raw)
                self.git("update-index", "--chmod=-x", "--", relative)
                with self.assertRaisesRegex(ValueError, "Index source"):
                    repository.verify_checkout(self.sha)

    def test_regular_and_ancestor_reparse_points_fail_closed(self):
        target = self.local / ".github/hooks/pre-push"
        real = Path.lstat
        for marker in (target, target.parent):
            def reparse(path, *args, **kwargs):
                status = real(path, *args, **kwargs)
                if path == marker:
                    return SimpleNamespace(st_mode=status.st_mode, st_file_attributes=0x400)
                return status

            with patch.object(Path, "lstat", new=reparse):
                with self.assertRaisesRegex(ValueError, "symlink|reparse"):
                    repository.actual_blob(target)
