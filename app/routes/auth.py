import hmac
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.deps import current_user, render, require_user
from app.models import User

router = APIRouter()


def _check(token: str, expected: str) -> None:
    if not hmac.compare_digest(token, expected):
        raise HTTPException(404, "Deze link klopt niet")


def _join_page(request: Request, admin: bool, **ctx):
    return render(request, "join.html", action=request.url.path, admin=admin, **ctx)


def _join(request: Request, db: Session, name: str, admin: bool):
    name = " ".join(name.split())[:60]
    if not name:
        return _join_page(request, admin, error="Vul je naam in.")
    key = name.lower()
    user = db.scalar(select(User).where(User.name_key == key))
    if user is None:
        user = User(name=name[:1].upper() + name[1:], name_key=key, is_admin=admin)
        db.add(user)
    elif user.is_admin and not admin:
        # Via de vriendenlink kun je niet inloggen als beheerder
        return _join_page(request, admin, error="Deze naam is al in gebruik. Kies een andere, bijvoorbeeld met de eerste letter van je achternaam.", name=name)
    elif admin:
        user.is_admin = True
    db.commit()
    request.session["user_id"] = user.id
    return RedirectResponse("/installeer?welkom=1", status_code=303)


@router.get("/uitnodiging/{token}")
def invite_form(token: str, request: Request, user: User | None = Depends(current_user)):
    _check(token, config.INVITE_TOKEN)
    if user:
        return RedirectResponse("/", status_code=303)
    return _join_page(request, admin=False)


@router.post("/uitnodiging/{token}")
def invite(token: str, request: Request, name: str = Form(""), db: Session = Depends(get_db)):
    _check(token, config.INVITE_TOKEN)
    return _join(request, db, name, admin=False)


@router.get("/beheer/{token}")
def admin_invite_form(token: str, request: Request, user: User | None = Depends(current_user)):
    _check(token, config.ADMIN_TOKEN)
    return _join_page(request, admin=True, name=user.name if user else "")


@router.post("/beheer/{token}")
def admin_invite(token: str, request: Request, name: str = Form(""), db: Session = Depends(get_db)):
    _check(token, config.ADMIN_TOKEN)
    return _join(request, db, name, admin=True)


@router.get("/login")
def login_info(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_with_link(request: Request, link: str = Form("")):
    """Een geplakte uitnodigingslink doorsturen. Nodig voor de app op het iOS-beginscherm,
    die de inlog van Safari niet deelt en waar je geen adres kunt intypen."""
    match = re.search(r"/(uitnodiging|beheer)/([A-Za-z0-9_\-]+)", link.strip())
    if match:
        kind, token = match.groups()
        expected = config.INVITE_TOKEN if kind == "uitnodiging" else config.ADMIN_TOKEN
        if hmac.compare_digest(token, expected):
            return RedirectResponse(f"/{kind}/{token}", status_code=303)
    return render(request, "login.html", error="Deze link werkt niet. Kopieer de hele link uit de groepsapp.", link=link)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/installeer")
def install(request: Request, user: User = Depends(require_user)):
    base = str(request.base_url).rstrip("/")
    login_link = f"{base}/beheer/{config.ADMIN_TOKEN}" if user.is_admin else f"{base}/uitnodiging/{config.INVITE_TOKEN}"
    return render(request, "install.html", user, welcome=request.query_params.get("welkom") == "1", login_link=login_link)
