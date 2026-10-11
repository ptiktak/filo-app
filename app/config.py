import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


APP_NAME = "jeroen & pep filosofie app"

_ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{(_ROOT / 'filosofie.db').as_posix()}"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-verander-mij")
# Geheime tokens in de uitnodigingslinks: /uitnodiging/<INVITE_TOKEN> en /beheer/<ADMIN_TOKEN>
INVITE_TOKEN = os.environ.get("INVITE_TOKEN", "dev-uitnodiging")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-beheer")
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Amsterdam"))
# Push-notificaties alleen tussen deze uren (lokale tijd)
NOTIFY_FROM_HOUR = _int("NOTIFY_FROM_HOUR", 9)
NOTIFY_UNTIL_HOUR = _int("NOTIFY_UNTIL_HOUR", 21)
# Hoe lang de laatste ronde open blijft
LAST_ROUND_DAYS = _int("LAST_ROUND_DAYS", 3)
# Groepsstatistieken pas tonen vanaf zoveel antwoorden
MIN_STATS_ANSWERS = _int("MIN_STATS_ANSWERS", 6)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")

RUN_SCHEDULER = os.environ.get("RUN_SCHEDULER", "true").lower() == "true"
