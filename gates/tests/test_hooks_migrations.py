"""migration new: numbers under a lock across worktrees and branches, snake_case names, one migration directory."""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import support  # noqa: E402

from lib import migrations  # noqa: E402

DIRECTORY = "packages/server/migrations"


class MigrationNew(unittest.TestCase):
    """Parallel worktrees and threads draw distinct gapless numbers; a bad name or an ambiguous layout is refused."""

    def setUp(self) -> None:
        self.root = support.make_tree({f"{DIRECTORY}/0001_init.sql": "-- 0001_init\n"})
        self.other = tempfile.mkdtemp(prefix="gates-wt-")
        os.rmdir(self.other)

    def tearDown(self) -> None:
        shutil.rmtree(self.other, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_signature_matches_gate_py(self) -> None:
        self.assertEqual(list(inspect.signature(migrations.new).parameters), ["tree", "name"])

    def test_parallel_worktrees_draw_distinct_numbers(self) -> None:
        support.git(self.root, "worktree", "add", "-q", "-b", "other", self.other)
        self.assertEqual(migrations.sql_directory(self.root), DIRECTORY)
        first = migrations.new(self.other, "add_sources")
        second = migrations.new(self.root, "add_quotes")
        self.assertEqual(first, f"{DIRECTORY}/0002_add_sources.sql")
        self.assertEqual(second, f"{DIRECTORY}/0003_add_quotes.sql")
        self.assertTrue(os.path.isfile(os.path.join(self.root, second)))

    def test_committed_branch_numbers_are_skipped(self) -> None:
        support.git(self.root, "checkout", "-q", "-b", "claude/a")
        support.write(self.root, f"{DIRECTORY}/0002_on_branch.sql", "-- 0002\n")
        support.git(self.root, "add", "-A")
        support.git(self.root, *support.GIT_ID, "commit", "-q", "-m", "a")
        support.git(self.root, "checkout", "-q", "-")
        self.assertEqual(migrations.new(self.root, "next"), f"{DIRECTORY}/0003_next.sql")

    def test_concurrent_calls_in_one_tree(self) -> None:
        made: list = []
        threads = [threading.Thread(target=lambda n=n: made.append(migrations.new(self.root, f"m{n}"))) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        numbers = sorted(os.path.basename(p)[:4] for p in made)
        self.assertEqual(numbers, ["0002", "0003", "0004", "0005"])
        self.assertEqual(migrations.sql_violations(self.root, DIRECTORY, "M"), [])

    def test_bad_name_is_refused(self) -> None:
        for name in ("Add Table", "add-table", "", "../x"):
            with self.assertRaises(ValueError):
                migrations.new(self.root, name)

    def test_two_migration_directories_are_refused(self) -> None:
        path = os.path.join(self.root, "gates", "roles.json")
        with open(path, encoding="utf-8") as handle:
            cfg = json.load(handle)
        cfg["components"]["core"]["migrations_dir"] = "db/migrations"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle)
        with self.assertRaises(ValueError):
            migrations.new(self.root, "x")


if __name__ == "__main__":
    unittest.main()
