"""scripts/clean_tree.py: only empty leftover folders go; ignored folders and submodules stay."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import clean_tree  # noqa: E402


class TestCleanTree(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".gitignore", "logs/\n.venv/\n__pycache__/\n")
        self.write(".gitmodules", '[submodule "assets"]\n\tpath = assets\n\turl = x\n')
        for d in ("old/a/b", "assets", "logs", ".venv/empty", "code/__pycache__", "gone/__pycache__", "code/empty"):
            os.makedirs(os.path.join(self.root, d))
        self.write("code/m.py", "")
        self.write("code/__pycache__/m.pyc", "")
        self.write("gone/__pycache__/x.pyc", "")

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w") as f:
            f.write(text)

    def test_lists_only_leftovers(self):
        self.assertEqual(clean_tree.leftovers(self.root), ["code/empty", "gone", "old"])


if __name__ == "__main__":
    unittest.main()
