"""Format review comments and summaries as Markdown."""

from typing import Any

from baloo.github.models import ReviewComment


class CommentFormatter:
    """Format review comments and summaries for GitHub."""

    SEVERITY_EMOJIS = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🔵",
    }

    @staticmethod
    def format_summary(comments: list[ReviewComment], metadata: dict[str, Any] = None) -> str:
        """
        Format a review summary markdown.

        Args:
            comments: List of review comments
            metadata: Optional agent metadata (costs, tokens)

        Returns:
            Formatted Markdown summary
        """
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for comment in comments:
            sev = comment.severity.value if hasattr(comment.severity, "value") else comment.severity
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        critical = severity_counts["CRITICAL"]
        high = severity_counts["HIGH"]
        medium = severity_counts["MEDIUM"]
        low = severity_counts["LOW"]

        summary_parts = []
        summary_parts.append("## 🐻 Baloo Review Summary\n")

        if not comments:
            summary_parts.append("✅ **No issues found!** Code looks good.")
        else:
            stats = []
            if critical > 0:
                stats.append(f"🔴 **{critical}** Critical")
            if high > 0:
                stats.append(f"🟠 **{high}** High")
            if medium > 0:
                stats.append(f"🟡 **{medium}** Medium")
            if low > 0:
                stats.append(f"🔵 **{low}** Low")

            summary_parts.append(" | ".join(stats))
            summary_parts.append(f"\n**Total**: {len(comments)} issue(s) found")

            if critical > 0 or high > 0:
                summary_parts.append("\n⚠️ **Please address CRITICAL/HIGH issues before merging**")
            else:
                summary_parts.append(
                    "\n✅ **No blocking issues - safe to merge** (consider addressing MEDIUM/LOW items)"
                )

        if metadata:
            summary_parts.append(CommentFormatter.format_metadata_section(metadata))

        return "\n".join(summary_parts)

    @staticmethod
    def format_metadata_section(metadata: dict[str, Any]) -> str:
        """
        Format agent metadata as a collapsible HTML details section.

        Args:
            metadata: Metadata dictionary

        Returns:
            HTML Markdown string
        """
        if not metadata:
            return ""

        model = metadata.get("model", "unknown")
        in_tok = metadata.get("input_tokens", 0)
        out_tok = metadata.get("output_tokens", 0)
        think_tok = metadata.get("thinking_tokens", 0)
        cost = metadata.get("cost_usd", 0)
        turns = metadata.get("num_turns", 0)
        duration = metadata.get("duration_seconds", 0)

        thinking_info = ""
        if think_tok > 0:
            thinking_info = f"<li>**Thinking Tokens:** {think_tok:,}</li>"

        return f"""
<details>
<summary>📊 Review Metadata</summary>

<ul>
  <li>**Model:** `{model}`</li>
  <li>**Tokens:** {in_tok:,} (in) / {out_tok:,} (out)</li>
  {thinking_info}
  <li>**Cost:** ${cost:.4f}</li>
  <li>**Turns:** {turns}</li>
  <li>**Duration:** {duration:.1f}s</li>
</ul>

</details>
"""
