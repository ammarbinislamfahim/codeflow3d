"""One-time script to seed the initial admin user."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, User, Subscription, APIKey, init_db
from auth.security import generate_api_key, hash_api_key

import bcrypt

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@1234")

def _hash_password_no_strength_check(password: str) -> str:
    """Hash password with bcrypt, bypassing strength validation (for seeding only)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def seed():
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if existing:
            existing.is_admin = True
            db.commit()
            print(f"User '{existing.username}' already exists — promoted to admin.")
            return

        try:
            user = User(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                password_hash=_hash_password_no_strength_check(ADMIN_PASSWORD),
                is_active=True,
                is_admin=True,
            )
            db.add(user)
            db.flush()

            db.add(Subscription(user_id=user.id, plan="enterprise", requests_per_day=10000))

            raw_key = generate_api_key()
            db.add(APIKey(
                user_id=user.id,
                key_hash=hash_api_key(raw_key),
                key_prefix=raw_key[:20],
                name="Admin-Default",
            ))
            db.commit()

            print("=" * 50)
            print("Admin user created!")
            print(f"  Email:    {ADMIN_EMAIL}")
            print(f"  Username: {ADMIN_USERNAME}")
            print(f"  API Key:  {raw_key}")
            print("=" * 50)
            print("Store the API key — it will not be shown again.")
            print("Change your password after first login.")
        except Exception:
            db.rollback()
            print("Admin already exists (concurrent creation) — skipping.")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
