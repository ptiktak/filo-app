from pathlib import Path

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import User, utcnow
from app.timeutil import fmt, fmt_input, fmt_relative

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["dt"] = fmt
templates.env.filters["dt_input"] = fmt_input
templates.env.globals["app_name"] = config.APP_NAME
templates.env.globals["vapid_public_key"] = config.VAPID_PUBLIC_KEY


def _relative(dt):
    return fmt_relative(dt, utcnow())


templates.env.filters["relative"] = _relative


class LoginRequired(Exception):
    pass


class AdminRequired(Exception):
    pass


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise AdminRequired()
    return user


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def render(request: Request, template: str, user: User | None = None, nav: str = "", **ctx):
    message = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request, template, {"user": user, "nav": nav, "flash": message, "now": utcnow(), **ctx}
    )
