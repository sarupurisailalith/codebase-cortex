"""Shared test fixtures."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def sample_diff() -> str:
    """A sample unified diff for testing."""
    return """diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,7 @@
 import os
+import sys

 def main():
-    print("hello")
+    print("hello world")
+    return 0

diff --git a/src/utils.py b/src/utils.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/src/utils.py
@@ -0,0 +1,3 @@
+def helper():
+    pass
+
diff --git a/old_file.py b/old_file.py
deleted file mode 100644
index 9876543..0000000
--- a/old_file.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old():
-    pass
"""


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory."""
    d = tmp_path / "data"
    d.mkdir()
    return d
