"""auth.py — JWT authentication (HS256, 24 h) and role-based access control for the API."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models_db import User

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set. Refusing to start with an insecure default.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def verify_password(plain_password, hashed_password):
    """Constant-time bcrypt check of a plaintext password against its stored hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """bcrypt-hash a password for storage."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Sign a JWT (HS256) with an `exp` claim; defaults to ACCESS_TOKEN_EXPIRE_MINUTES (24 h)."""
    to_encode = data.copy()
    # Use the configured expiry constant if no override is provided
    expire = datetime.now(timezone.utc) + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_from_token(token: str, db: Session) -> Optional[User]:
    """Resolve a JWT to a User, or None if the token is invalid/expired/unknown."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if username is None:
        return None
    return db.query(User).filter(User.username == username).first()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """FastAPI dependency: resolve the Bearer token to a User or raise 401."""
    user = get_user_from_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def require_role(allowed_roles: list[str]):
    """Dependency factory: allow only users whose role is in `allowed_roles`, else 403 (RBAC)."""
    def role_checker(current_user: User = Depends(get_current_user)):
        """Inner dependency produced by require_role."""
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires one of: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker
