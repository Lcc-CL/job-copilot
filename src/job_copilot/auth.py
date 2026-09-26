"""单用户本地账号认证、Session 校验与账号管理。"""

from __future__ import annotations

import datetime
import json
import math
import os
import secrets
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, MutableMapping, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .database import get_engine
from .models import AccountAuditEvent, LocalAccount


_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hash_val: str) -> bool:
    return _password_hasher.verify(password, hash_val)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_hash(raw_hash: str) -> str:
    raw_hash = raw_hash.strip()
    if raw_hash and len(raw_hash) > 2:
        if raw_hash[0] == raw_hash[-1] and raw_hash[0] in ('"', "'"):
            raw_hash = raw_hash[1:-1]
    return raw_hash.replace("\\n", "").replace("\\r", "")


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password_hash: str
    session_secret: str
    session_max_age: int = 604800
    env: str = "development"
    source_type: str = "unconfigured"
    allow_dev_defaults: bool = False

    @classmethod
    def from_env(cls) -> "AuthConfig":
        env = (os.getenv("APP_ENV", "development") or "development").strip().lower()
        username = (os.getenv("APP_USERNAME", "") or "").strip()
        password_hash = _normalize_hash(os.getenv("APP_PASSWORD_HASH", "") or "")
        session_secret = (os.getenv("SESSION_SECRET", "") or "").strip()
        session_max_age = int(os.getenv("SESSION_MAX_AGE_SECONDS", "604800"))
        allow_dev_defaults = _env_bool("APP_ALLOW_DEV_DEFAULTS") and env != "production"

        if env == "production":
            if not session_secret:
                raise RuntimeError("Production requires SESSION_SECRET")
            if len(session_secret) < 32:
                raise RuntimeError("SESSION_SECRET must be at least 32 characters")
        elif not session_secret:
            session_secret = secrets.token_hex(32)

        if bool(username) != bool(password_hash):
            source_type = "misconfigured"
            username = ""
            password_hash = ""
        elif username and password_hash:
            source_type = "environment"
        elif allow_dev_defaults:
            source_type = "development_default"
            username = "admin"
            password_hash = hash_password("admin")
        else:
            source_type = "unconfigured"

        return cls(
            username=username,
            password_hash=password_hash,
            session_secret=session_secret,
            session_max_age=session_max_age,
            env=env,
            source_type=source_type,
            allow_dev_defaults=allow_dev_defaults,
        )


_auth_config: Optional[AuthConfig] = None


def get_auth_config() -> AuthConfig:
    global _auth_config
    if _auth_config is None:
        _auth_config = AuthConfig.from_env()
    return _auth_config


def reset_auth_config_cache() -> None:
    """测试与显式配置刷新使用；不会修改环境变量。"""
    global _auth_config
    _auth_config = None


@dataclass(frozen=True)
class ResolvedAccount:
    id: Optional[int]
    username: str
    password_hash: str
    session_version: int
    source_type: str


class AuthFailure(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers

    @property
    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def _http_error(failure: AuthFailure) -> HTTPException:
    return HTTPException(
        status_code=failure.status_code,
        detail=failure.detail,
        headers=failure.headers,
    )


class LoginRateLimiter:
    """按客户端 IP 统计登录失败次数的滑动窗口限流器。

    状态只保存在进程内存中：单进程 uvicorn 部署足够，重启即清零。
    窗口内失败次数达到上限后，该 IP 的登录请求在最早一次失败滑出窗口前
    一律直接拒绝（不再校验密码）；登录成功会清空该 IP 的失败记录。
    """

    _SWEEP_THRESHOLD = 4096

    def __init__(
        self,
        max_failures: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_failures = max(1, max_failures)
        self.window_seconds = max(1.0, float(window_seconds))
        self._clock = clock
        self._failures: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Optional[Deque[float]]:
        failures = self._failures.get(key)
        if failures is None:
            return None
        while failures and failures[0] <= now - self.window_seconds:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures

    def retry_after(self, key: str) -> int:
        """返回该 IP 还需等待的秒数；0 表示允许尝试登录。"""
        with self._lock:
            now = self._clock()
            failures = self._prune(key, now)
            if failures is None or len(failures) < self.max_failures:
                return 0
            return max(1, math.ceil(failures[0] + self.window_seconds - now))

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            if len(self._failures) >= self._SWEEP_THRESHOLD:
                for stale_key in list(self._failures):
                    self._prune(stale_key, now)
            failures = self._failures.setdefault(
                key, deque(maxlen=self.max_failures)
            )
            failures.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    @classmethod
    def from_env(cls) -> "LoginRateLimiter":
        return cls(
            max_failures=int(os.getenv("LOGIN_MAX_FAILURES", "5")),
            window_seconds=float(os.getenv("LOGIN_FAILURE_WINDOW_SECONDS", "900")),
        )


_login_rate_limiter: Optional[LoginRateLimiter] = None


def get_login_rate_limiter() -> LoginRateLimiter:
    global _login_rate_limiter
    if _login_rate_limiter is None:
        _login_rate_limiter = LoginRateLimiter.from_env()
    return _login_rate_limiter


def reset_login_rate_limiter() -> None:
    """测试与显式配置刷新使用：丢弃全部失败记录并重新读取环境变量。"""
    global _login_rate_limiter
    _login_rate_limiter = None


def _client_ip(request: Request) -> str:
    # request.client 是 TCP 对端地址；只有在 uvicorn 的 FORWARDED_ALLOW_IPS
    # 信任了反向代理时才会被改写为 X-Forwarded-For 中的真实客户端，
    # 因此客户端无法通过伪造请求头绕过限流。
    return request.client.host if request.client else "unknown"


def _server_failure(context: str, error: Exception) -> AuthFailure:
    print(f"[auth] {context}: {type(error).__name__}", file=sys.stderr)
    return AuthFailure(500, "AUTH_SERVER_ERROR", "账号服务发生异常")


def _is_username_conflict(error: IntegrityError) -> bool:
    message = str(error.orig).lower()
    return "unique" in message and "username" in message


def _config_account(config: Optional[AuthConfig] = None) -> Optional[ResolvedAccount]:
    cfg = config or get_auth_config()
    if cfg.source_type == "misconfigured":
        raise AuthFailure(500, "AUTH_SERVER_ERROR", "账号环境变量配置不完整")
    if not cfg.username or not cfg.password_hash:
        return None
    return ResolvedAccount(
        id=None,
        username=cfg.username,
        password_hash=cfg.password_hash,
        session_version=1,
        source_type=cfg.source_type,
    )


def _account_storage_ready(bind) -> bool:
    inspector = inspect(bind)
    return inspector.has_table("local_accounts") and inspector.has_table(
        "account_audit_events"
    )


def _database_account(session: Session) -> Optional[LocalAccount]:
    if not inspect(session.get_bind()).has_table("local_accounts"):
        return None
    return session.scalar(select(LocalAccount).order_by(LocalAccount.id).limit(1))


def resolve_account(
    *,
    engine: Optional[Engine] = None,
    session: Optional[Session] = None,
) -> Optional[ResolvedAccount]:
    """按数据库 → 环境变量 → 显式开发默认值的优先级解析账号。"""
    owns_session = session is None
    target_session = session or Session(engine or get_engine())
    try:
        stored = _database_account(target_session)
        if stored is not None:
            return ResolvedAccount(
                id=stored.id,
                username=stored.username,
                password_hash=stored.password_hash,
                session_version=stored.session_version,
                source_type="database",
            )
        return _config_account()
    except AuthFailure:
        raise
    except SQLAlchemyError as error:
        raise _server_failure("account lookup failed", error) from error
    finally:
        if owns_session:
            target_session.close()


def get_account_source_type() -> str:
    try:
        account = resolve_account()
        return account.source_type if account else "unconfigured"
    except AuthFailure:
        return "error"


def _verify_current_password(password: str, account: ResolvedAccount) -> None:
    try:
        valid = verify_password(password, account.password_hash)
    except Exception as error:
        raise _server_failure("password verification failed", error) from error
    if not valid:
        raise AuthFailure(403, "CURRENT_PASSWORD_INVALID", "当前密码错误")


def _validate_new_password(password: str) -> None:
    if len(password) < 10 or not password.strip():
        raise AuthFailure(422, "PASSWORD_INVALID", "新密码至少需要 10 个字符")


def _add_audit_event(
    session: Session,
    account: LocalAccount,
    event_type: str,
    details: dict[str, str],
    occurred_at: str,
) -> None:
    session.flush()
    session.add(AccountAuditEvent(
        account_id=account.id,
        event_type=event_type,
        details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
        occurred_at=occurred_at,
    ))


def _stored_account_from_effective(
    session: Session,
    effective: ResolvedAccount,
    now: str,
) -> LocalAccount:
    stored = _database_account(session)
    if stored is not None:
        return stored
    stored = LocalAccount(
        username=effective.username,
        password_hash=effective.password_hash,
        session_version=effective.session_version,
        source_type="database",
        created_at=now,
        updated_at=now,
    )
    session.add(stored)
    session.flush()
    return stored


def change_username(
    current_password: str,
    new_username: str,
    *,
    engine: Optional[Engine] = None,
) -> ResolvedAccount:
    target_engine = engine or get_engine()
    session = Session(target_engine)
    try:
        if not _account_storage_ready(session.get_bind()):
            raise AuthFailure(
                503,
                "ACCOUNT_STORAGE_NOT_READY",
                "账号存储尚未初始化，请先运行数据库 migration",
            )
        effective = resolve_account(session=session)
        if effective is None:
            raise AuthFailure(404, "ACCOUNT_NOT_FOUND", "本地账号不存在")
        _verify_current_password(current_password, effective)

        stored = _stored_account_from_effective(session, effective, _utc_now())
        conflict = session.scalar(
            select(LocalAccount).where(
                LocalAccount.username == new_username,
                LocalAccount.id != stored.id,
            )
        )
        if conflict is not None:
            raise AuthFailure(409, "USERNAME_CONFLICT", "用户名已被占用")

        old_username = stored.username
        now = _utc_now()
        stored.username = new_username
        stored.session_version += 1
        stored.source_type = "database"
        stored.updated_at = now
        _add_audit_event(
            session,
            stored,
            "username_changed",
            {
                "from_username": old_username,
                "to_username": new_username,
                "previous_source": effective.source_type,
            },
            now,
        )
        session.commit()
        return ResolvedAccount(
            id=stored.id,
            username=stored.username,
            password_hash=stored.password_hash,
            session_version=stored.session_version,
            source_type="database",
        )
    except AuthFailure:
        session.rollback()
        raise
    except IntegrityError as error:
        session.rollback()
        if _is_username_conflict(error):
            raise AuthFailure(409, "USERNAME_CONFLICT", "用户名已被占用") from error
        raise _server_failure("username update failed", error) from error
    except Exception as error:
        session.rollback()
        raise _server_failure("username update failed", error) from error
    finally:
        session.close()


def change_password(
    current_password: str,
    new_password: str,
    *,
    engine: Optional[Engine] = None,
) -> ResolvedAccount:
    _validate_new_password(new_password)
    target_engine = engine or get_engine()
    session = Session(target_engine)
    try:
        if not _account_storage_ready(session.get_bind()):
            raise AuthFailure(
                503,
                "ACCOUNT_STORAGE_NOT_READY",
                "账号存储尚未初始化，请先运行数据库 migration",
            )
        effective = resolve_account(session=session)
        if effective is None:
            raise AuthFailure(404, "ACCOUNT_NOT_FOUND", "本地账号不存在")
        _verify_current_password(current_password, effective)

        now = _utc_now()
        stored = _stored_account_from_effective(session, effective, now)
        stored.password_hash = hash_password(new_password)
        stored.session_version += 1
        stored.source_type = "database"
        stored.updated_at = now
        _add_audit_event(
            session,
            stored,
            "password_changed",
            {"username": stored.username, "previous_source": effective.source_type},
            now,
        )
        session.commit()
        return ResolvedAccount(
            id=stored.id,
            username=stored.username,
            password_hash=stored.password_hash,
            session_version=stored.session_version,
            source_type="database",
        )
    except AuthFailure:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise _server_failure("password update failed", error) from error
    finally:
        session.close()


def reset_local_account_password(
    new_password: str,
    *,
    username: Optional[str] = None,
    engine: Optional[Engine] = None,
) -> ResolvedAccount:
    """CLI 服务函数：创建或更新数据库账号，并使全部旧 Session 失效。"""
    _validate_new_password(new_password)
    target_engine = engine or get_engine()

    from .database import init_db

    init_db(engine=target_engine)
    session = Session(target_engine)
    try:
        new_password_hash = hash_password(new_password)
        stored = _database_account(session)
        account_existed = stored is not None
        requested_username = (username or "").strip()
        if stored is not None:
            if requested_username and requested_username != stored.username:
                raise AuthFailure(404, "ACCOUNT_NOT_FOUND", "指定的本地账号不存在")
            effective_username = stored.username
            previous_source = "database"
        else:
            configured = _config_account()
            effective_username = requested_username or (
                configured.username if configured is not None else ""
            )
            if not effective_username:
                raise AuthFailure(
                    503,
                    "ACCOUNT_NOT_CONFIGURED",
                    "未配置账号，请通过 --username 指定本地用户名",
                )
            previous_source = configured.source_type if configured else "unconfigured"
            now = _utc_now()
            stored = LocalAccount(
                username=effective_username,
                password_hash=new_password_hash,
                session_version=(configured.session_version if configured else 0) + 1,
                source_type="database",
                created_at=now,
                updated_at=now,
            )
            session.add(stored)
            session.flush()

        now = _utc_now()
        stored.password_hash = new_password_hash
        if account_existed:
            stored.session_version += 1
        stored.updated_at = now
        stored.source_type = "database"
        _add_audit_event(
            session,
            stored,
            "password_reset",
            {"username": effective_username, "previous_source": previous_source},
            now,
        )
        session.commit()
        return ResolvedAccount(
            id=stored.id,
            username=stored.username,
            password_hash=stored.password_hash,
            session_version=stored.session_version,
            source_type="database",
        )
    except AuthFailure:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise _server_failure("password reset failed", error) from error
    finally:
        session.close()


def validate_session_data(session_data: MutableMapping) -> ResolvedAccount:
    user = session_data.get("user")
    if not user:
        raise AuthFailure(401, "AUTH_REQUIRED", "请先登录")
    session_version = session_data.get("session_version")
    if session_version is None:
        raise AuthFailure(401, "SESSION_INVALID", "登录 Session 已失效，请重新登录")

    account = resolve_account()
    if (
        account is None
        or account.username != user
        or account.session_version != session_version
    ):
        session_data.clear()
        raise AuthFailure(401, "SESSION_INVALID", "登录 Session 已失效，请重新登录")
    return account


def add_session_middleware(app) -> None:
    cfg = get_auth_config()
    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret,
        session_cookie="jc_session",
        max_age=cfg.session_max_age,
        same_site="lax",
        https_only=(cfg.env == "production"),
    )


async def require_auth(request: Request) -> str:
    try:
        return validate_session_data(request.session).username
    except AuthFailure as failure:
        raise _http_error(failure) from failure


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UsernameUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_username: str = Field(min_length=1, max_length=128)

    @field_validator("new_username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("new_username contains invalid characters")
        return normalized


class PasswordUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=10, max_length=1024)


def register_auth_routes(app) -> None:
    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        try:
            account = validate_session_data(request.session)
            return {"username": account.username}
        except AuthFailure as failure:
            raise _http_error(failure) from failure

    @app.post("/api/auth/login")
    async def auth_login(body: LoginBody, request: Request):
        limiter = get_login_rate_limiter()
        client_ip = _client_ip(request)
        try:
            retry_after = limiter.retry_after(client_ip)
            if retry_after:
                raise AuthFailure(
                    429,
                    "LOGIN_RATE_LIMITED",
                    "登录失败次数过多，请稍后再试",
                    headers={"Retry-After": str(retry_after)},
                )
            account = resolve_account()
            if account is None:
                raise AuthFailure(503, "ACCOUNT_NOT_CONFIGURED", "本地账号尚未配置")
            if body.username.strip() != account.username:
                limiter.record_failure(client_ip)
                raise AuthFailure(401, "INVALID_CREDENTIALS", "用户名或密码错误")
            try:
                valid = verify_password(body.password, account.password_hash)
            except Exception as error:
                raise _server_failure("login password verification failed", error) from error
            if not valid:
                limiter.record_failure(client_ip)
                raise AuthFailure(401, "INVALID_CREDENTIALS", "用户名或密码错误")
            limiter.reset(client_ip)
            request.session.clear()
            request.session["user"] = account.username
            request.session["session_version"] = account.session_version
            return {"username": account.username}
        except AuthFailure as failure:
            raise _http_error(failure) from failure
        except Exception as error:
            failure = _server_failure("login failed", error)
            raise _http_error(failure) from error

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        request.session.clear()
        response = JSONResponse({"status": "ok"})
        response.delete_cookie("jc_session")
        return response

    @app.get("/api/account")
    async def account_details(request: Request):
        try:
            account = validate_session_data(request.session)
            return {"username": account.username, "source_type": account.source_type}
        except AuthFailure as failure:
            raise _http_error(failure) from failure

    @app.patch("/api/account/username")
    async def account_username(body: UsernameUpdateBody, request: Request):
        try:
            validate_session_data(request.session)
            account = change_username(body.current_password, body.new_username)
            request.session.clear()
            request.session["user"] = account.username
            request.session["session_version"] = account.session_version
            return {"username": account.username, "source_type": account.source_type}
        except AuthFailure as failure:
            raise _http_error(failure) from failure

    @app.patch("/api/account/password")
    async def account_password(body: PasswordUpdateBody, request: Request):
        try:
            validate_session_data(request.session)
            change_password(body.current_password, body.new_password)
            request.session.clear()
            response = JSONResponse({
                "status": "ok",
                "reauthentication_required": True,
            })
            response.delete_cookie("jc_session")
            return response
        except AuthFailure as failure:
            raise _http_error(failure) from failure


def auth_error_payload(failure: AuthFailure) -> dict[str, dict[str, str]]:
    return {"detail": failure.detail}


def cmd_hash_password(password: str = "") -> str:
    """生成密码 Hash（交互式 getpass 或由现有兼容调用传参）。"""
    if not password:
        import getpass

        pw1 = getpass.getpass("New password: ")
        if len(pw1) < 10:
            return "ERROR: Password must be at least 10 characters"
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            return "ERROR: Passwords do not match"
        password = pw1
    return hash_password(password)


def cmd_reset_password(username: str = "") -> str:
    """交互式重置本地账号密码，命令行不接受或回显明文密码。"""
    import getpass

    selected_username = username.strip()
    if not selected_username:
        try:
            account = resolve_account()
        except AuthFailure:
            account = None
        if account is None:
            selected_username = input("Username: ").strip()

    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        return "ERROR: Passwords do not match"

    try:
        result = reset_local_account_password(
            password,
            username=selected_username or None,
        )
    except AuthFailure as failure:
        return f"ERROR [{failure.code}]: {failure.message}"
    return (
        f"✓ 本地账号 {result.username} 的密码已重置；"
        "所有旧 Session 已失效，请重新登录。"
    )
