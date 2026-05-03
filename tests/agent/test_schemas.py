"""Tests for schemas module (Pydantic models and conversion logic)."""

from baloo.agent.schemas import (
    ReviewFinding,
    ReviewOutput,
    _lang_for_file,
    _normalize_category,
    enforce_severity,
    findings_to_comments,
    review_output_schema,
)
from baloo.fidelity.models import (
    FidelityOutput,
    fidelity_output_schema,
)


class TestReviewOutput:
    """Tests for ReviewOutput Pydantic model."""

    def test_validate_full_data(self):
        """Test validation with all fields present."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 10,
                    "severity": "HIGH",
                    "category": "Security",
                    "title": "SQL Injection",
                    "description": "Unsafe query",
                    "impact": "Data breach",
                    "recommendation": "Use params",
                    "code_example": "cursor.execute(?, (id,))",
                }
            ],
            "summary": {
                "total_issues": 1,
                "critical": 0,
                "high": 1,
                "medium": 0,
                "low": 0,
                "files_examined": 3,
                "patterns_searched": ["password"],
                "positive_observations": ["Good tests"],
            },
        }
        output = ReviewOutput.model_validate(data)
        assert len(output.findings) == 1
        assert output.findings[0].file == "test.py"
        assert output.summary.high == 1

    def test_validate_minimal_data(self):
        """Test validation with minimal data."""
        output = ReviewOutput.model_validate({"findings": [], "summary": {}})
        assert output.findings == []
        assert output.summary.total_issues == 0

    def test_validate_missing_optional_fields(self):
        """Test that optional fields default correctly."""
        data = {"findings": [{"file": "test.py"}]}
        output = ReviewOutput.model_validate(data)
        finding = output.findings[0]
        assert finding.line == 1
        assert finding.severity == "MEDIUM"
        assert finding.category == "Quality"
        assert finding.title == "Issue"
        assert finding.impact is None
        assert finding.recommendation is None
        assert finding.code_example is None

    def test_validate_empty_object(self):
        """Test that an empty object produces sensible defaults."""
        output = ReviewOutput.model_validate({})
        assert output.findings == []
        assert output.summary.total_issues == 0

    def test_validate_string_summary(self):
        """Test that a string summary is coerced to default ReviewSummary."""
        data = {
            "findings": [{"file": "a.py", "line": 1, "title": "Issue"}],
            "summary": "This PR has some problems and should not be merged.",
        }
        output = ReviewOutput.model_validate(data)
        assert len(output.findings) == 1
        assert output.summary.total_issues == 0  # default

    def test_validate_none_summary(self):
        """Test that None summary is coerced to default ReviewSummary."""
        data = {"findings": [], "summary": None}
        output = ReviewOutput.model_validate(data)
        assert output.summary.total_issues == 0

    def test_validate_summary_with_list_files_examined(self):
        """Test that files_examined as a list doesn't crash (agent quirk)."""
        data = {
            "findings": [{"file": "a.py", "line": 1, "title": "X"}],
            "summary": {
                "total_issues": 1,
                "files_examined": ["a.py", "b.py", "README.md"],
            },
        }
        output = ReviewOutput.model_validate(data)
        assert len(output.findings) == 1
        # files_examined accepted as Any — just don't crash
        assert isinstance(output.summary.files_examined, list)

    def test_validate_summary_with_extra_fields(self):
        """Test that unknown extra fields in summary are ignored."""
        data = {
            "findings": [],
            "summary": {"total_issues": 0, "overall_quality": "good", "rating": 8.5},
        }
        output = ReviewOutput.model_validate(data)
        assert output.summary.total_issues == 0

    def test_finding_with_string_line_number(self):
        """Test that string line numbers are coerced."""
        data = {"findings": [{"file": "a.py", "line": "42", "title": "X"}]}
        output = ReviewOutput.model_validate(data)
        assert output.findings[0].get_line() == 42

    def test_finding_with_invalid_line_number(self):
        """Test that non-numeric line falls back to 1."""
        data = {"findings": [{"file": "a.py", "line": "near the top", "title": "X"}]}
        output = ReviewOutput.model_validate(data)
        assert output.findings[0].get_line() == 1

    def test_finding_with_null_line_number(self):
        """Test that null line falls back to 1."""
        data = {"findings": [{"file": "a.py", "line": None, "title": "X"}]}
        output = ReviewOutput.model_validate(data)
        assert output.findings[0].get_line() == 1

    def test_finding_with_extra_fields_ignored(self):
        """Test that unknown finding fields are ignored."""
        data = {
            "findings": [
                {
                    "file": "a.py",
                    "line": 1,
                    "title": "X",
                    "confidence": 0.95,
                    "suggested_fix": "do something",
                }
            ]
        }
        output = ReviewOutput.model_validate(data)
        assert len(output.findings) == 1


class TestReviewOutputSchema:
    """Tests for review_output_schema function."""

    def test_returns_correct_format(self):
        """Test that schema has required top-level keys."""
        schema = review_output_schema()
        assert schema["type"] == "json_schema"
        assert "schema" in schema
        assert "properties" in schema["schema"]

    def test_schema_has_findings_and_summary(self):
        """Test that schema includes findings and summary."""
        schema = review_output_schema()
        props = schema["schema"]["properties"]
        assert "findings" in props
        assert "summary" in props


class TestFindingsToComments:
    """Tests for findings_to_comments conversion."""

    def test_single_finding(self):
        """Test converting a single finding to ReviewComment."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 10,
                    "severity": "HIGH",
                    "category": "Security",
                    "title": "SQL Injection Risk",
                    "description": "Unsafe SQL query",
                    "impact": "Data breach possible",
                    "recommendation": "Use parameterized queries",
                    "code_example": "cursor.execute('?', (id,))",
                }
            ],
            "summary": {"total_issues": 1},
        }
        comments = findings_to_comments(data)
        assert len(comments) == 1
        assert comments[0].path == "test.py"
        assert comments[0].line == 10
        assert comments[0].severity == "HIGH"  # Security enforced to HIGH
        assert comments[0].category == "Security"
        assert "SQL Injection Risk" in comments[0].body
        assert "Data breach possible" in comments[0].body
        assert "Use parameterized queries" in comments[0].body
        assert "```python" in comments[0].body

    def test_multiple_findings(self):
        """Test converting multiple findings."""
        data = {
            "findings": [
                {"file": "a.py", "line": 1, "title": "Issue 1"},
                {"file": "b.py", "line": 2, "title": "Issue 2"},
                {"file": "c.py", "line": 3, "title": "Issue 3"},
            ]
        }
        comments = findings_to_comments(data)
        assert len(comments) == 3
        assert comments[0].path == "a.py"
        assert comments[1].path == "b.py"
        assert comments[2].path == "c.py"

    def test_empty_findings(self):
        """Test empty findings returns empty list."""
        comments = findings_to_comments({"findings": [], "summary": {}})
        assert comments == []

    def test_severity_normalization(self):
        """Test that severity is normalized and enforcement is applied."""
        data = {
            "findings": [
                {"file": "a.py", "severity": "critical", "category": "Security"},
                {"file": "b.py", "severity": "MeDiUm", "category": "Quality"},
            ]
        }
        comments = findings_to_comments(data)
        assert (
            comments[0].severity == "CRITICAL"
        )  # Security CRITICAL passes through (floor, not cap)
        assert comments[1].severity == "MEDIUM"  # Quality MEDIUM stays MEDIUM

    def test_optional_fields_missing(self):
        """Test that missing optional fields don't appear in body."""
        data = {"findings": [{"file": "test.py", "line": 5, "title": "Issue"}]}
        comments = findings_to_comments(data)
        body = comments[0].body
        assert "**Impact:**" not in body
        assert "**Recommendation:**" not in body
        assert "```python" not in body

    def test_all_optional_fields_present(self):
        """Test that all optional fields appear in body."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 1,
                    "title": "Test",
                    "description": "Desc",
                    "impact": "High impact",
                    "recommendation": "Fix it",
                    "code_example": "fixed_code()",
                }
            ]
        }
        comments = findings_to_comments(data)
        body = comments[0].body
        assert "**Impact:** High impact" in body
        assert "**Recommendation:**" in body
        assert "Fix it" in body
        assert "```python" in body
        assert "fixed_code()" in body

    def test_default_values(self):
        """Test defaults for missing fields."""
        data = {"findings": [{"file": "test.py"}]}
        comments = findings_to_comments(data)
        assert comments[0].line == 1
        assert comments[0].severity == "MEDIUM"
        assert comments[0].category == "Quality"

    def test_summary_logging(self, caplog):
        """Test that summary is logged."""
        data = {
            "findings": [],
            "summary": {
                "total_issues": 5,
                "critical": 1,
                "high": 2,
                "medium": 2,
                "files_examined": 10,
                "patterns_searched": ["password", "secret"],
                "positive_observations": ["Good test coverage"],
            },
        }
        with caplog.at_level("INFO"):
            findings_to_comments(data)
        assert "Total issues: 5" in caplog.text
        assert "Critical: 1" in caplog.text
        assert "Files examined: 10" in caplog.text

    def test_unicode_content(self):
        """Test handling of unicode in findings."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 1,
                    "title": "测试问题",
                    "description": "这是一个描述",
                    "recommendation": "修复建议",
                }
            ]
        }
        comments = findings_to_comments(data)
        assert "测试问题" in comments[0].body
        assert "这是一个描述" in comments[0].body
        assert "修复建议" in comments[0].body

    def test_null_optional_fields(self):
        """Test that null optional fields are treated as missing."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 1,
                    "impact": None,
                    "recommendation": None,
                    "code_example": None,
                }
            ]
        }
        comments = findings_to_comments(data)
        body = comments[0].body
        assert "**Impact:**" not in body


class TestNormalizeCategory:
    """Tests for category normalization."""

    def test_title_case_passthrough(self):
        assert _normalize_category("Quality") == "Quality"
        assert _normalize_category("Security") == "Security"
        assert _normalize_category("Silent Failures") == "Silent Failures"

    def test_uppercase(self):
        assert _normalize_category("QUALITY") == "Quality"
        assert _normalize_category("SECURITY") == "Security"
        assert _normalize_category("BUGS") == "Bugs"
        assert _normalize_category("PERFORMANCE") == "Performance"
        assert _normalize_category("GUIDELINES") == "Guidelines"
        assert _normalize_category("SILENT FAILURES") == "Silent Failures"

    def test_lowercase(self):
        assert _normalize_category("quality") == "Quality"
        assert _normalize_category("security") == "Security"

    def test_unknown_falls_back_to_quality(self):
        assert _normalize_category("Unknown") == "Quality"
        assert _normalize_category("") == "Quality"

    def test_with_whitespace(self):
        assert _normalize_category(" QUALITY ") == "Quality"

    def test_findings_with_uppercase_category(self):
        """End-to-end: agent returns UPPERCASE category, parsed correctly."""
        data = {
            "findings": [
                {
                    "file": "test.py",
                    "line": 1,
                    "severity": "MEDIUM",
                    "category": "QUALITY",
                    "title": "Test",
                    "description": "Desc",
                }
            ]
        }
        comments = findings_to_comments(data)
        assert len(comments) == 1
        assert comments[0].category == "Quality"

    def test_findings_with_mixed_case_categories(self):
        """Multiple findings with different casings."""
        data = {
            "findings": [
                {"file": "a.py", "line": 1, "category": "SECURITY"},
                {"file": "b.py", "line": 2, "category": "bugs"},
                {"file": "c.py", "line": 3, "category": "Silent Failures"},
                {"file": "d.py", "line": 4, "category": "PERFORMANCE"},
            ]
        }
        comments = findings_to_comments(data)
        assert comments[0].category == "Security"
        assert comments[1].category == "Bugs"
        assert comments[2].category == "Silent Failures"
        assert comments[3].category == "Performance"


class TestEnforceSeverity:
    """Tests for rule-based severity enforcement by category."""

    def test_security_medium_escalated_to_high(self):
        """Security MEDIUM is escalated to HIGH floor."""
        finding = ReviewFinding(file="a.py", line=1, severity="MEDIUM", category="Security")
        assert enforce_severity(finding) == "HIGH"

    def test_security_low_escalated_to_high(self):
        """Security LOW is escalated to HIGH floor."""
        finding = ReviewFinding(file="a.py", line=1, severity="LOW", category="Security")
        assert enforce_severity(finding) == "HIGH"

    def test_security_high_stays_high(self):
        """Security HIGH is at floor, stays HIGH."""
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Security")
        assert enforce_severity(finding) == "HIGH"

    def test_security_critical_passes_through(self):
        """Security CRITICAL is above floor, passes through as CRITICAL."""
        finding = ReviewFinding(file="a.py", line=1, severity="CRITICAL", category="Security")
        assert enforce_severity(finding) == "CRITICAL"

    def test_bugs_low_escalated_to_high(self):
        """Bugs LOW is escalated to HIGH floor."""
        finding = ReviewFinding(file="a.py", line=1, severity="LOW", category="Bugs")
        assert enforce_severity(finding) == "HIGH"

    def test_bugs_critical_passes_through(self):
        """Bugs CRITICAL is above floor, passes through as CRITICAL."""
        finding = ReviewFinding(file="a.py", line=1, severity="CRITICAL", category="Bugs")
        assert enforce_severity(finding) == "CRITICAL"

    def test_silent_failures_low_escalated_to_high(self):
        """Silent Failures LOW is escalated to HIGH floor."""
        finding = ReviewFinding(file="a.py", line=1, severity="LOW", category="Silent Failures")
        assert enforce_severity(finding) == "HIGH"

    def test_silent_failures_critical_passes_through(self):
        """Silent Failures CRITICAL passes through."""
        finding = ReviewFinding(
            file="a.py", line=1, severity="CRITICAL", category="Silent Failures"
        )
        assert enforce_severity(finding) == "CRITICAL"

    def test_guidelines_medium_escalated_to_high(self):
        """Guidelines MEDIUM is escalated to HIGH floor."""
        finding = ReviewFinding(file="a.py", line=1, severity="MEDIUM", category="Guidelines")
        assert enforce_severity(finding) == "HIGH"

    def test_guidelines_critical_passes_through(self):
        """Guidelines CRITICAL passes through."""
        finding = ReviewFinding(file="a.py", line=1, severity="CRITICAL", category="Guidelines")
        assert enforce_severity(finding) == "CRITICAL"

    def test_performance_high_capped_to_medium(self):
        """Performance HIGH is capped down to MEDIUM."""
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Performance")
        assert enforce_severity(finding) == "MEDIUM"

    def test_performance_critical_capped_to_medium(self):
        """Performance CRITICAL is capped down to MEDIUM."""
        finding = ReviewFinding(file="a.py", line=1, severity="CRITICAL", category="Performance")
        assert enforce_severity(finding) == "MEDIUM"

    def test_performance_low_escalated_to_medium(self):
        """Performance is always MEDIUM — LOW is escalated."""
        finding = ReviewFinding(file="a.py", line=1, severity="LOW", category="Performance")
        assert enforce_severity(finding) == "MEDIUM"

    def test_bugs_high_stays_high(self):
        """Bugs HIGH is at floor, stays HIGH."""
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Bugs")
        assert enforce_severity(finding) == "HIGH"

    def test_silent_failures_high_stays_high(self):
        """Silent Failures HIGH is at floor, stays HIGH."""
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Silent Failures")
        assert enforce_severity(finding) == "HIGH"

    def test_guidelines_high_stays_high(self):
        """Guidelines HIGH is at floor, stays HIGH."""
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Guidelines")
        assert enforce_severity(finding) == "HIGH"

    def test_quality_capped_at_medium(self):
        """Quality findings should be capped at MEDIUM even if LLM says CRITICAL."""
        finding = ReviewFinding(file="a.py", line=1, severity="CRITICAL", category="Quality")
        assert enforce_severity(finding) == "MEDIUM"

    def test_quality_low_stays_low(self):
        """Quality LOW should stay LOW (cap, not floor)."""
        finding = ReviewFinding(file="a.py", line=1, severity="LOW", category="Quality")
        assert enforce_severity(finding) == "LOW"

    def test_quality_medium_stays_medium(self):
        finding = ReviewFinding(file="a.py", line=1, severity="MEDIUM", category="Quality")
        assert enforce_severity(finding) == "MEDIUM"

    def test_unknown_category_defaults_medium(self):
        finding = ReviewFinding(file="a.py", line=1, severity="HIGH", category="Unknown")
        assert enforce_severity(finding) == "MEDIUM"

    def test_quality_unknown_severity_normalized_to_medium(self):
        """Unrecognized severity string for Quality is normalized to MEDIUM, not returned as-is."""
        finding = ReviewFinding(file="a.py", line=1, severity="SEVERE", category="Quality")
        assert enforce_severity(finding) == "MEDIUM"

    def test_findings_to_comments_uses_enforcement(self):
        """End-to-end: findings_to_comments should apply severity enforcement."""
        data = {
            "findings": [
                {
                    "file": "a.py",
                    "line": 1,
                    "severity": "MEDIUM",
                    "category": "Security",
                    "title": "SQL Injection",
                    "description": "Unsafe query",
                },
                {
                    "file": "b.py",
                    "line": 2,
                    "severity": "CRITICAL",
                    "category": "Quality",
                    "title": "Naming",
                    "description": "Bad name",
                },
            ]
        }
        comments = findings_to_comments(data)
        # Security MEDIUM should be escalated to HIGH
        assert comments[0].severity == "HIGH"
        # Quality CRITICAL should be capped to MEDIUM
        assert comments[1].severity == "MEDIUM"


class TestFidelityOutput:
    """Tests for FidelityOutput Pydantic model."""

    def test_validate_full_data(self):
        """Test validation with all fields."""
        data = {
            "fidelity_score": 85,
            "logic_summary": "Good alignment.",
            "requirements": [
                {"description": "Add auth", "status": "fulfilled", "evidence": "auth.py:10"}
            ],
            "extras": ["Added logging"],
            "discrepancies": [{"description": "Missing tests", "severity": "MEDIUM"}],
        }
        output = FidelityOutput.model_validate(data)
        assert output.fidelity_score == 85
        assert len(output.requirements) == 1
        assert len(output.discrepancies) == 1

    def test_validate_minimal_data(self):
        """Test validation with empty/default data."""
        output = FidelityOutput.model_validate({})
        assert output.fidelity_score == 0
        assert output.logic_summary == ""
        assert output.requirements == []

    def test_fidelity_output_schema_format(self):
        """Test that fidelity_output_schema returns correct format."""
        schema = fidelity_output_schema()
        assert schema["type"] == "json_schema"
        assert "schema" in schema
        assert "properties" in schema["schema"]


class TestLangForFile:
    """Tests for _lang_for_file helper."""

    def test_python(self):
        assert _lang_for_file("foo.py") == "python"

    def test_go(self):
        assert _lang_for_file("main.go") == "go"

    def test_typescript(self):
        assert _lang_for_file("app.ts") == "typescript"

    def test_tsx(self):
        assert _lang_for_file("component.tsx") == "typescript"

    def test_javascript(self):
        assert _lang_for_file("index.js") == "javascript"

    def test_mjs(self):
        assert _lang_for_file("module.mjs") == "javascript"

    def test_rust(self):
        assert _lang_for_file("lib.rs") == "rust"

    def test_yaml(self):
        assert _lang_for_file("config.yml") == "yaml"
        assert _lang_for_file("config.yaml") == "yaml"

    def test_toml(self):
        assert _lang_for_file("Cargo.toml") == "toml"

    def test_hcl(self):
        assert _lang_for_file("main.tf") == "hcl"

    def test_unknown_extension_returns_text(self):
        assert _lang_for_file("styles.css") == "text"
        assert _lang_for_file("README.md") == "text"

    def test_no_extension_returns_text(self):
        assert _lang_for_file("Makefile") == "text"

    def test_empty_string_returns_text(self):
        assert _lang_for_file("") == "text"

    def test_case_insensitive(self):
        assert _lang_for_file("script.PY") == "python"
        assert _lang_for_file("main.GO") == "go"

    def test_go_finding_produces_go_fence(self):
        """End-to-end: a .go file finding produces ```go code fence."""
        data = {
            "findings": [
                {
                    "file": "cmd/main.go",
                    "line": 10,
                    "title": "Error not checked",
                    "description": "Return value ignored",
                    "code_example": "f, _ := os.Open(path)",
                }
            ]
        }
        comments = findings_to_comments(data)
        assert "```go" in comments[0].body

    def test_ts_finding_produces_typescript_fence(self):
        """End-to-end: a .ts file finding produces ```typescript code fence."""
        data = {
            "findings": [
                {
                    "file": "src/api.ts",
                    "line": 5,
                    "title": "Any type usage",
                    "description": "Avoid any",
                    "code_example": "const x: any = getValue();",
                }
            ]
        }
        comments = findings_to_comments(data)
        assert "```typescript" in comments[0].body
