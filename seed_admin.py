"""
seed_admin.py
─────────────
Standalone script to seed the default coach account if none exists.
Usage: python3 seed_admin.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlmodel import Session, select
from app.core.database import engine, init_db
from app.core.security import get_password_hash
from app.models.user import User


def seed_admin() -> None:
    """Check if coach exists; if not, create default coach."""
    init_db()
    with Session(engine) as session:
        coach = session.exec(
            select(User).where((User.role == "coach") | (User.role == "coash"))
        ).first()
        if not coach:
            coach = User(
                username="coach",
                email="coach@kotchy.dev",
                hashed_password=get_password_hash("adminpassword"),
                role="coach",
                is_active=True,
            )
            session.add(coach)
            session.commit()
            session.refresh(coach)
            print(f"Created default coach: username='coach', email='coach@kotchy.dev', password='adminpassword'")
        else:
            print(f"Coach account already exists: username='{coach.username}', role='{coach.role}'")


if __name__ == "__main__":
    seed_admin()
