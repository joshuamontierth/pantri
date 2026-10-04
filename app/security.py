import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.responses import Response

from . import config
from .models import AuthSession, User, utcnow

_hasher = PasswordHasher()
# Used to spend comparable time when the username doesn't exist.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password):
    return _hasher.hash(password)


def verify_password(user, password):
    if user is None:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return False
    try:
        return _hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_new_password(password, confirm):
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "Passwords don't match."
    return None


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user):
    """Create a login session; returns the raw token to put in the cookie."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            csrf_token=secrets.token_urlsafe(24),
            expires_at=utcnow() + timedelta(days=config.SESSION_DAYS),
        )
    )
    db.commit()
    return token


def load_session(db, token):
    if not token:
        return None
    sess = db.query(AuthSession).filter_by(token_hash=_token_hash(token)).one_or_none()
    if sess is None:
        return None
    now = utcnow()
    if sess.expires_at < now:
        db.delete(sess)
        db.commit()
        return None
    # Sliding expiry: stay logged in as long as the device is used at least once a year.
    if sess.expires_at - now < timedelta(days=config.SESSION_DAYS - 1):
        sess.expires_at = now + timedelta(days=config.SESSION_DAYS)
        db.commit()
        sess.refreshed = True
    return sess


def delete_session(db, token):
    if token:
        db.query(AuthSession).filter_by(token_hash=_token_hash(token)).delete()
        db.commit()


def delete_other_sessions(db, user_id, keep_token=None):
    q = db.query(AuthSession).filter(AuthSession.user_id == user_id)
    if keep_token:
        q = q.filter(AuthSession.token_hash != _token_hash(keep_token))
    q.delete(synchronize_session=False)
    db.commit()


def set_session_cookie(response, token):
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
    )


def session_cookie_header(token):
    r = Response()
    set_session_cookie(r, token)
    return r.headers["set-cookie"]


def clear_session_cookie(response):
    response.delete_cookie(config.SESSION_COOKIE, samesite="lax", secure=config.COOKIE_SECURE)


def find_user(db, username):
    return db.query(User).filter_by(username_lower=(username or "").strip().lower()).one_or_none()
