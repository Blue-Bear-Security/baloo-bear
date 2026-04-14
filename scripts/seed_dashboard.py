"""Seed the database with sample review data for local dashboard development."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from baloo.config.settings import get_settings
from baloo.db.engine import get_session_factory, init_db
from baloo.db.models import Finding, Review

REPOS = [
    "acme/backend",
    "acme/frontend",
    "acme/infra",
    "acme/mobile-app",
    "acme/docs",
]

AUTHORS = ["alice", "bob", "carol", "dave", "eve"]

STATUSES = ["approved", "changes_requested", "commented", "error"]
STATUS_WEIGHTS = [50, 25, 20, 5]

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
CATEGORIES = ["Security", "Bugs", "Performance", "Quality"]

MODELS = ["claude-sonnet-4-6", "claude-sonnet-4-6"]


async def seed(n: int = 100) -> None:
    settings = get_settings()
    if not settings.database_url:
        print("Set DATABASE_URL in .env first")
        return

    await init_db(settings.database_url)
    factory = get_session_factory(settings.database_url)

    now = datetime.now(timezone.utc)

    async with factory() as session:
        async with session.begin():
            for i in range(n):
                started = now - timedelta(
                    days=random.randint(0, 60),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                )
                duration = round(random.uniform(15, 180), 1)
                status = random.choices(STATUSES, STATUS_WEIGHTS)[0]
                cost = round(random.uniform(0.002, 0.15), 4)

                review = Review(
                    repo_full_name=random.choice(REPOS),
                    pr_number=random.randint(1, 500),
                    pr_title=f"PR title #{i + 1}",
                    pr_author=random.choice(AUTHORS),
                    commit_sha=f"{random.getrandbits(160):040x}",
                    review_status=status,
                    trigger_reason="pull_request:opened",
                    started_at=started,
                    completed_at=started + timedelta(seconds=duration),
                    duration_seconds=duration,
                    model_used=random.choice(MODELS),
                    tokens_input=random.randint(5000, 80000),
                    tokens_output=random.randint(500, 8000),
                    cost_usd=cost,
                    agent_turns=random.randint(1, 8),
                    files_examined=random.randint(1, 30),
                    auto_approved=status == "approved",
                    fidelity_score=(
                        round(random.uniform(50, 100), 1) if random.random() > 0.3 else None
                    ),
                    error_message="Prompt is too long" if status == "error" else None,
                )
                session.add(review)
                await session.flush()

                # Add random findings
                num_findings = random.randint(0, 6) if status != "error" else 0
                for _ in range(num_findings):
                    session.add(
                        Finding(
                            review_id=review.id,
                            file_path=f"src/{random.choice(['api','lib','utils'])}/{random.choice(['auth','db','handler'])}.py",
                            line_number=random.randint(1, 500),
                            severity=random.choice(SEVERITIES),
                            category=random.choice(CATEGORIES),
                            body=f"Sample finding for review {review.id}",
                        )
                    )

    print(f"Seeded {n} reviews")


if __name__ == "__main__":
    asyncio.run(seed())
