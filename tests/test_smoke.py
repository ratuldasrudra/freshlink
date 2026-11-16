"""Check that the approved project definition is present in a checkout."""

import unittest
from pathlib import Path


class ProjectSmokeTest(unittest.TestCase):
    """Verify essential project artifacts before application code exists."""

    def test_project_definition_and_license_exist(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.assertIn("FreshLink", (root / "docs" / "PROJECT.md").read_text(encoding="utf-8"))
        self.assertIn("MIT License", (root / "LICENSE").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
