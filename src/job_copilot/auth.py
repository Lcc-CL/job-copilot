"""单用户登录保护 —— Session-based auth with argon2 password hashing.

环境变量：
  APP_USERNAME / APP_PASSWORD_HASH / SESSION_SECRET / SESSION_MAX_AGE_SECONDS
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, HTTPException
from pwdlib import PasswordHash
from starlette.middleware.sessions import SessionMiddleware

# ---- Password ----

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hash_val: str) -> bool:
    return _password_hasher.verify(password, hash_val)


# ---- Config ----

@dataclass
class AuthConfig:
    username: str
    password_hash: str
    session_secret: str
    session_max_age: int = 604800  # 7 days
    env: str = "development"

    @classmethod
    def from_env(cls) -> AuthConfig:
        env = os.getenv("APP_ENV", "development")
        username = os.getenv("APP_USERNAME", "")
        password_hash = os.getenv("APP_PASSWORD_HASH", "")
        session_secret = os.getenv("SESSION_SECRET", "")
        session_max_age = int(os.getenv("SESSION_MAX_AGE_SECONDS", "604800"))

        if env == "production":
            missing = []
            if not username:
                missing.append("APP_USERNAME")
            if not password_hash:
                missing.append("APP_PASSWORD_HASH")
            if not session_secret:
                missing.append("SESSION_SECRET")
            if missing:
                raise RuntimeError(
                    f"Production requires: {', '.join(missing)}. "
                    "Set in environment or .env file."
                )
            if len(session_secret) < 32:
                raise RuntimeError("SESSION_SECRET must be at least 32 characters")

        # Development defaults
        if not session_secret:
            session_secret = secrets.token_hex(32)

        return cls(
            username=username or "admin",
            password_hash=password_hash or hash_password("admin"),
            session_secret=session_secret,
            session_max_age=session_max_age,
            env=env,
        )


_auth_config: Optional[AuthConfig] = None


def get_auth_config() -> AuthConfig:
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig.from_env()
    return _auth_config


# ---- Session Middleware ----

def add_session_middleware(app):
    cfg = get_auth_config()
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret,
        session_cookie="jc_session",
        max_age=cfg.session_max_age,
        same_site="lax",
        https_only=(cfg.env == "production"),
    )


# ---- Auth dependency ----

async def require_auth(request: Request):
    """FastAPI dependency: require authenticated session."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# ---- Auth endpoints (registered in web.py) ----

from pydantic import BaseModel as PydBaseModel


class LoginBody(PydBaseModel):
    username: str
    password: str


def register_auth_routes(app):

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"username": user}

    @app.post("/api/auth/login")
    async def auth_login(body: LoginBody, request: Request):
        cfg = get_auth_config()
        if body.username != cfg.username:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not verify_password(body.password, cfg.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        request.session["user"] = body.username
        return {"username": body.username}

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        request.session.clear()
        return {"status": "ok"}


# ---- CLI helper ----

def cmd_hash_password(password: str) -> str:
    """打印密码 hash（用于生成 APP_PASSWORD_HASH 环境变量）。"""
    h = hash_password(password)
    return f"APP_PASSWORD_HASH={h}"
