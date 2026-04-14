"""Mock PR contexts for testing."""

from baloo.github.models import FileChange, PRContext, PRDiscussionContext, PRMetadata


def mock_file_change(
    filename: str = "test.py",
    status: str = "modified",
    additions: int = 5,
    deletions: int = 2,
    patch: str = "",
) -> FileChange:
    """Create a mock FileChange object."""
    return FileChange(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        changes=additions + deletions,
        patch=patch or f"@@ -1,2 +1,{additions} @@\n-old line\n+new line",
    )


# Mock PR with security issue (hardcoded password)
mock_pr_with_security_issue = PRContext(
    metadata=PRMetadata(
        pr_number=1,
        title="Test PR: Add authentication function",
        description="Adding a simple authentication function",
        author="test-user",
        repo_full_name="test/repo",
        base_branch="main",
        head_branch="feature/auth",
        files_changed=[
            FileChange(
                filename="auth.py",
                status="added",
                additions=10,
                deletions=0,
                changes=10,
                patch="""@@ -0,0 +1,10 @@
+def authenticate(username):
+    # TODO: This should be moved to environment variables
+    admin_password = 'hardcoded123'
+    api_key = 'sk-1234567890abcdef'
+
+    if username == 'admin':
+        return admin_password
+    return None
+
+# Database query with potential SQL injection
+def get_user(user_id):
+    query = "SELECT * FROM users WHERE id = " + user_id
+    return execute_query(query)
""",
            )
        ],
    ),
    discussion=PRDiscussionContext(),
    diff="""diff --git a/auth.py b/auth.py
new file mode 100644
index 0000000..abcdef
--- /dev/null
+++ b/auth.py
@@ -0,0 +1,10 @@
+def authenticate(username):
+    # TODO: This should be moved to environment variables
+    admin_password = 'hardcoded123'
+    api_key = 'sk-1234567890abcdef'
+
+    if username == 'admin':
+        return admin_password
+    return None
+
+# Database query with potential SQL injection
+def get_user(user_id):
+    query = "SELECT * FROM users WHERE id = " + user_id
+    return execute_query(query)
""",
)


# Mock PR with clean code (no issues)
mock_pr_clean = PRContext(
    metadata=PRMetadata(
        pr_number=2,
        title="Update README documentation",
        description="Improving the README with better examples",
        author="contributor",
        repo_full_name="test/repo",
        base_branch="main",
        head_branch="docs/readme-update",
        files_changed=[
            FileChange(
                filename="README.md",
                status="modified",
                additions=15,
                deletions=5,
                changes=20,
                patch="""@@ -10,5 +10,15 @@
 ## Installation

-Install with pip:
-```
-pip install baloo
+Install with pip (requires Python 3.10+):
+
+```bash
+pip install baloo
+```
+
+## Quick Start
+
+1. Clone the repository
+2. Install dependencies
+3. Configure your GitHub App
+4. Run the server
""",
            )
        ],
    ),
    discussion=PRDiscussionContext(),
    diff="""diff --git a/README.md b/README.md
index 1234567..abcdef0 100644
--- a/README.md
+++ b/README.md
@@ -10,5 +10,15 @@
 ## Installation

-Install with pip:
-```
-pip install baloo
+Install with pip (requires Python 3.10+):
+
+```bash
+pip install baloo
+```
+
+## Quick Start
+
+1. Clone the repository
+2. Install dependencies
+3. Configure your GitHub App
+4. Run the server
""",
)


# Mock PR with many files (should use Sonnet)
mock_pr_large = PRContext(
    metadata=PRMetadata(
        pr_number=3,
        title="Refactor database layer",
        description="Major refactoring of the database access layer for better performance",
        author="senior-dev",
        repo_full_name="test/repo",
        base_branch="main",
        head_branch="refactor/database",
        files_changed=[
            mock_file_change(f"db/models/model_{i}.py", "modified", 50, 30)
            for i in range(1, 6)
        ],
    ),
    discussion=PRDiscussionContext(),
    diff="... large diff with 5 files and 400+ line changes ...",
)
