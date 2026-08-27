"""A minimal check that the foundation and test discovery are connected."""

from pathlib import Path
import unittest


class RepositoryHealthTest(unittest.TestCase):
    def test_foundation_documents_exist(self):
        root = Path(__file__).resolve().parents[2]
        for relative in ("README.md", "AGENTS.md", "docs/architecture.md",
                         "docs/data-contracts.md"):
            with self.subTest(path=relative):
                self.assertTrue((root / relative).is_file())


if __name__ == "__main__":
    unittest.main()
