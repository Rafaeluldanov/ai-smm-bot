"""REST API аутентификации SaaS-платформы (dev-каркас).

Регистрация создаёт пользователя + аккаунт + членство и возвращает подписанный
dev-токен (не продакшн-JWT). ``GET /auth/me`` требует токен в заголовке
``Authorization``. Пароли/секреты в ответах не возвращаются.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    AccountRead,
    AuthResult,
    MeResponse,
    UserLoginRequest,
    UserRead,
    UserRegisterRequest,
)
from app.services.auth_service import (
    AuthError,
    AuthService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]
AuthSvc = Annotated[AuthService, Depends(get_auth_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _auth_result(service: AuthService, db: Session, user: User) -> AuthResult:
    accounts = service.list_user_accounts(db, user.id)
    return AuthResult(
        token=service.issue_token(user),
        user=UserRead.model_validate(user),
        accounts=[AccountRead.model_validate(a) for a in accounts],
    )


@router.post("/register", response_model=AuthResult, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegisterRequest, db: DbSession, service: AuthSvc) -> AuthResult:
    """Зарегистрировать пользователя (создаёт аккаунт + членство). 409 — дубль email."""
    try:
        user, _account = service.register_user(
            db, payload.email, payload.password, payload.full_name, payload.account_name
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _auth_result(service, db, user)


@router.post("/login", response_model=AuthResult)
def login(payload: UserLoginRequest, db: DbSession, service: AuthSvc) -> AuthResult:
    """Вход по email/паролю. 401 — неверные учётные данные."""
    try:
        user = service.authenticate_user(db, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return _auth_result(service, db, user)


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser, db: DbSession, service: AuthSvc) -> MeResponse:
    """Текущий пользователь и его аккаунты (по dev-токену)."""
    accounts = service.list_user_accounts(db, current_user.id)
    return MeResponse(
        user=UserRead.model_validate(current_user),
        accounts=[AccountRead.model_validate(a) for a in accounts],
    )
