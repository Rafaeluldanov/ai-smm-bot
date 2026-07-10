"""REST API аутентификации SaaS-платформы (v0.3.2: сессии + refresh + cookies).

Регистрация/логин создают серверную сессию и выдают access-токен (тело) + refresh-cookie
(+ csrf-cookie, если CSRF включён). Access-токен — HMAC-SHA256 (``AuthTokenService``).
``/auth/refresh`` ротирует refresh-токен, ``/auth/logout`` ревокирует сессию,
``/auth/logout-all`` — все сессии пользователя, ``/auth/sessions`` — список активных.
Пароли/токены/секреты в ответах и логах не раскрываются.
"""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_auth_service,
    get_auth_session_service,
    get_current_user,
    get_db,
)
from app.config import Settings, get_settings
from app.models.user import User
from app.schemas.auth import (
    AccountRead,
    AuthResult,
    AuthSessionRead,
    LogoutResult,
    MeResponse,
    RefreshResult,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)
from app.services.audit_log_service import (
    ACTION_USER_LOGIN,
    ACTION_USER_LOGOUT,
    ACTION_USER_LOGOUT_ALL,
    ACTION_USER_REFRESH,
    ACTION_USER_REGISTERED,
    AuditLogService,
    get_audit_log_service,
)
from app.services.auth_service import (
    AuthError,
    AuthService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
)
from app.services.auth_session_service import AuthSessionError, AuthSessionService, SessionTokens

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]
AuthSvc = Annotated[AuthService, Depends(get_auth_service)]
SessionSvc = Annotated[AuthSessionService, Depends(get_auth_session_service)]
AuditSvc = Annotated[AuditLogService, Depends(get_audit_log_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _samesite(settings: Settings) -> Literal["lax", "strict", "none"]:
    value = (settings.auth_cookie_samesite or "lax").strip().lower()
    if value in ("lax", "strict", "none"):
        return cast(Literal["lax", "strict", "none"], value)
    return "lax"


def _set_auth_cookies(response: Response, settings: Settings, tokens: SessionTokens) -> None:
    """Установить refresh (+access если cookie-auth, +csrf если CSRF) cookies."""
    secure = settings.secure_cookies_effective
    samesite = _samesite(settings)
    refresh_max_age = settings.auth_refresh_token_expire_days * 86400
    access_max_age = settings.auth_access_token_expire_minutes * 60
    response.set_cookie(
        settings.auth_refresh_cookie_name,
        tokens.refresh_token,
        max_age=refresh_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    if settings.auth_cookie_auth_enabled:
        response.set_cookie(
            settings.auth_session_cookie_name,
            tokens.access_token,
            max_age=access_max_age,
            httponly=settings.auth_cookie_httponly,
            secure=secure,
            samesite=samesite,
            path="/",
        )
    if settings.csrf_enabled_effective:
        # CSRF-cookie НЕ httponly — фронтенд читает его и шлёт X-CSRF-Token.
        response.set_cookie(
            settings.csrf_cookie_name,
            tokens.csrf_token,
            max_age=refresh_max_age,
            httponly=False,
            secure=secure,
            samesite=samesite,
            path="/",
        )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in (
        settings.auth_refresh_cookie_name,
        settings.auth_session_cookie_name,
        settings.csrf_cookie_name,
    ):
        response.delete_cookie(name, path="/")


def _auth_result(
    service: AuthService,
    db: Session,
    user: User,
    tokens: SessionTokens,
    settings: Settings,
) -> AuthResult:
    accounts = service.list_user_accounts(db, user.id)
    return AuthResult(
        token=tokens.access_token,
        access_token=tokens.access_token,
        token_type="bearer",
        expires_in=tokens.expires_in,
        csrf_token=tokens.csrf_token if settings.csrf_enabled_effective else None,
        user=UserRead.model_validate(user),
        accounts=[AccountRead.model_validate(a) for a in accounts],
    )


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    service: AuthSvc,
    session_svc: SessionSvc,
    audit: AuditSvc,
    settings: SettingsDep,
) -> AuthResult:
    """Зарегистрировать пользователя (создаёт аккаунт + членство + сессию). 409 — дубль."""
    try:
        user, account = service.register_user(
            db, payload.email, payload.password, payload.full_name, payload.account_name
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    tokens = session_svc.create_login_session(db, user, _client_ip(request), _user_agent(request))
    _set_auth_cookies(response, settings, tokens)
    audit.record(
        db,
        ACTION_USER_REGISTERED,
        account_id=account.id if account is not None else None,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"session_id": tokens.session.session_id},
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return _auth_result(service, db, user, tokens, settings)


@router.post("/login", response_model=AuthResult)
def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    service: AuthSvc,
    session_svc: SessionSvc,
    audit: AuditSvc,
    settings: SettingsDep,
) -> AuthResult:
    """Вход по email/паролю → сессия + access-токен. 401 — неверные данные."""
    try:
        user = service.authenticate_user(db, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    tokens = session_svc.create_login_session(db, user, _client_ip(request), _user_agent(request))
    _set_auth_cookies(response, settings, tokens)
    audit.record(
        db,
        ACTION_USER_LOGIN,
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"session_id": tokens.session.session_id},
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return _auth_result(service, db, user, tokens, settings)


@router.post("/refresh", response_model=RefreshResult)
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    session_svc: SessionSvc,
    audit: AuditSvc,
    settings: SettingsDep,
    refresh_token_body: str | None = None,
) -> RefreshResult:
    """Ротировать refresh-токен (из cookie или тела) и выдать новый access-токен."""
    refresh_cookie: str | None = request.cookies.get(settings.auth_refresh_cookie_name)
    token = refresh_cookie or refresh_token_body
    try:
        tokens = session_svc.refresh_session(db, token or "")
    except AuthSessionError as exc:
        _clear_auth_cookies(response, settings)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_auth_cookies(response, settings, tokens)
    audit.record(
        db,
        ACTION_USER_REFRESH,
        user_id=tokens.session.user_id,
        entity_type="session",
        entity_id=tokens.session.session_id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return RefreshResult(
        token=tokens.access_token,
        access_token=tokens.access_token,
        token_type="bearer",
        expires_in=tokens.expires_in,
        csrf_token=tokens.csrf_token if settings.csrf_enabled_effective else None,
    )


@router.post("/logout", response_model=LogoutResult)
def logout(
    request: Request,
    response: Response,
    db: DbSession,
    current_user: CurrentUser,
    session_svc: SessionSvc,
    audit: AuditSvc,
    settings: SettingsDep,
) -> LogoutResult:
    """Выйти: ревокировать текущую сессию (по refresh-cookie) и очистить cookies."""
    revoked = 0
    refresh_cookie = request.cookies.get(settings.auth_refresh_cookie_name)
    identity = session_svc.refresh_identity(refresh_cookie) if refresh_cookie else None
    if (
        identity is not None
        and identity[0] == current_user.id
        and session_svc.logout_session(db, identity[1])
    ):
        revoked = 1
    _clear_auth_cookies(response, settings)
    audit.record(
        db,
        ACTION_USER_LOGOUT,
        user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return LogoutResult(status="ok", revoked_sessions=revoked)


@router.post("/logout-all", response_model=LogoutResult)
def logout_all(
    request: Request,
    response: Response,
    db: DbSession,
    current_user: CurrentUser,
    session_svc: SessionSvc,
    audit: AuditSvc,
    settings: SettingsDep,
) -> LogoutResult:
    """Выйти со всех устройств: ревокировать все сессии пользователя."""
    revoked = session_svc.logout_all(db, current_user.id)
    _clear_auth_cookies(response, settings)
    audit.record(
        db,
        ACTION_USER_LOGOUT_ALL,
        user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
        metadata={"revoked_sessions": revoked},
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return LogoutResult(status="ok", revoked_sessions=revoked)


@router.get("/sessions", response_model=list[AuthSessionRead])
def list_sessions(
    current_user: CurrentUser, db: DbSession, session_svc: SessionSvc
) -> list[AuthSessionRead]:
    """Активные сессии текущего пользователя (без хешей токенов)."""
    return [
        AuthSessionRead.model_validate(s) for s in session_svc.list_sessions(db, current_user.id)
    ]


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser, db: DbSession, service: AuthSvc) -> MeResponse:
    """Текущий пользователь и его аккаунты."""
    accounts = service.list_user_accounts(db, current_user.id)
    return MeResponse(
        user=UserRead.model_validate(current_user),
        accounts=[AccountRead.model_validate(a) for a in accounts],
    )
