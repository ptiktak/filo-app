"""Testomgeving instellen vóórdat de app (en dus config/db) geïmporteerd wordt."""

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/test.db",
    INVITE_TOKEN="vrienden-token",
    ADMIN_TOKEN="beheer-token",
    RUN_SCHEDULER="false",
    MIN_STATS_ANSWERS="6",
    MIN_LIVE_ANSWERS="3",
    VAPID_PUBLIC_KEY="",
    VAPID_PRIVATE_KEY="",
)
os.environ.pop("ANTHROPIC_API_KEY", None)
