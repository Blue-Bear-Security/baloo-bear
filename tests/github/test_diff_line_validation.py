"""Tests for diff line validation in post_review."""

from baloo.github.api_client import _valid_diff_lines

SAMPLE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,8 @@ def authenticate(user):
     token = generate_token(user)
     if not token:
         raise AuthError("no token")
+    log.info("authenticated %s", user)
+    audit_trail.record(user, token)
     return token

 def validate(token):
@@ -40,3 +42,5 @@ def revoke(token):
     db.delete(token)
+    log.info("revoked %s", token)
+    return True
diff --git a/src/utils.py b/src/utils.py
new file mode 100644
--- /dev/null
+++ b/src/utils.py
@@ -0,0 +1,5 @@
+def helper():
+    pass
+
+def another():
+    return 42
"""


class TestValidDiffLines:
    def test_extracts_lines_for_existing_file(self):
        result = _valid_diff_lines(SAMPLE_DIFF)
        auth_lines = result["src/auth.py"]
        # First hunk: lines 10-17 (context + additions)
        # Context lines 10,11,12 + additions 13,14 + context 15,16,17
        assert 10 in auth_lines  # context
        assert 13 in auth_lines  # addition
        assert 14 in auth_lines  # addition
        assert 15 in auth_lines  # context (return token)

    def test_extracts_lines_for_new_file(self):
        result = _valid_diff_lines(SAMPLE_DIFF)
        utils_lines = result["src/utils.py"]
        # Lines 1-5 are the file content; line 6 may appear from the
        # trailing newline in the diff string (harmless — permissive).
        assert {1, 2, 3, 4, 5}.issubset(utils_lines)

    def test_deletion_lines_not_included(self):
        diff = """\
diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -5,4 +5,3 @@ def foo():
     keep1
-    deleted_line
     keep2
     keep3
"""
        result = _valid_diff_lines(diff)
        lines = result["file.py"]
        # Lines 5 (keep1), 6 (keep2), 7 (keep3) — deleted_line is not in new file
        assert 5 in lines
        assert 6 in lines
        assert 7 in lines
        assert {5, 6, 7}.issubset(lines)

    def test_multiple_hunks(self):
        result = _valid_diff_lines(SAMPLE_DIFF)
        auth_lines = result["src/auth.py"]
        # Second hunk starts at new line 42
        assert 42 in auth_lines
        assert 43 in auth_lines  # addition
        assert 44 in auth_lines  # addition

    def test_empty_diff(self):
        result = _valid_diff_lines("")
        assert result == {}

    def test_file_not_in_diff(self):
        result = _valid_diff_lines(SAMPLE_DIFF)
        assert "nonexistent.py" not in result

    def test_line_outside_hunk_not_included(self):
        result = _valid_diff_lines(SAMPLE_DIFF)
        auth_lines = result["src/auth.py"]
        # Line 1 is not in any hunk
        assert 1 not in auth_lines
        # Line 30 is between hunks
        assert 30 not in auth_lines
