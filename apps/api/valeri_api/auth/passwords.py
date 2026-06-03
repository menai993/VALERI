"""Password hashing (bcrypt). Plaintext passwords never touch the database."""

import bcrypt


def hash_password(plain: str) -> str:
    """Bcrypt hash for storage in app.app_user.password_hash."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, password_hash: str) -> bool:
    """Constant-time verification of a login attempt."""
    try:
        return bcrypt.checkpw(plain.encode(), password_hash.encode())
    except ValueError:
        # Malformed stored hash — treat as a failed login, never raise to the client.
        return False
