from datetime import datetime, timedelta, timezone
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import Usuario

SECRET_KEY = os.getenv('JWT_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = 'local-development-only-change-me'

ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('JWT_EXPIRE_MINUTES', '480'))
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/login', auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    if password_hash.startswith('$2'):
        return pwd_context.verify(password, password_hash)
    return password == password_hash


def create_access_token(user: Usuario) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {'sub': user.nombreuser, 'role': user.role or 'user', 'exp': expires_at}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Credenciales inválidas',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    if not token:
        raise credentials_error

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('sub')
        if not username:
            raise credentials_error
    except JWTError as error:
        raise credentials_error from error

    user = db.query(Usuario).filter(Usuario.nombreuser == username).first()
    if not user:
        raise credentials_error
    return user


def require_admin(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if (current_user.role or '').lower() != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Solo un administrador puede realizar esta acción')
    return current_user