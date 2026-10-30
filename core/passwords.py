"""T11 (adelantado, Sprint 1) - hashing de contraseñas con argon2. pip install argon2-cffi"""
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_ph = PasswordHasher()

def hash_password(password: str) -> str:
    return _ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False

def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)
