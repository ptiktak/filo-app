from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Alle tijden worden als naive UTC opgeslagen."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    name_key: Mapped[str] = mapped_column(String(60), unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Round(Base):
    __tablename__ = "rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, default=0)
    opens_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    questions: Mapped[list["Question"]] = relationship(back_populates="round", order_by="Question.position")

    def is_open(self, now: datetime) -> bool:
        return self.opens_at <= now < self.closes_at

    def is_closed(self, now: datetime) -> bool:
        return now >= self.closes_at


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(120))
    scenario: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id", ondelete="SET NULL"), nullable=True)

    round: Mapped[Round | None] = relationship(back_populates="questions")
    options: Mapped[list["Option"]] = relationship(
        back_populates="question", order_by="Option.position", cascade="all, delete-orphan"
    )


class Option(Base):
    __tablename__ = "options"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(String(255))
    reflection: Mapped[str] = mapped_column(String(255), default="")

    question: Mapped[Question] = relationship(back_populates="options")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("user_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    option_id: Mapped[int] = mapped_column(ForeignKey("options.id", ondelete="CASCADE"))
    explanation: Mapped[str | None] = mapped_column(String(140), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    option: Mapped[Option] = relationship()


class GroupPrediction(Base):
    """Voorspelling: welke optie kiest de meerderheid?"""

    __tablename__ = "group_predictions"
    __table_args__ = (UniqueConstraint("user_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    option_id: Mapped[int] = mapped_column(ForeignKey("options.id", ondelete="CASCADE"))


class FriendPrediction(Base):
    """Voorspelling: wat kiest deze vriend?"""

    __tablename__ = "friend_predictions"
    __table_args__ = (UniqueConstraint("user_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    option_id: Mapped[int] = mapped_column(ForeignKey("options.id", ondelete="CASCADE"))


class Evening(Base):
    __tablename__ = "evenings"
    id: Mapped[int] = mapped_column(primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("evening_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    evening_id: Mapped[int] = mapped_column(ForeignKey("evenings.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    attending: Mapped[bool] = mapped_column(Boolean)

    user: Mapped[User] = relationship()


class TopicVote(Base):
    """Een vraag die iemand interessant vindt om op de avond te bespreken."""

    __tablename__ = "topic_votes"
    __table_args__ = (UniqueConstraint("evening_id", "user_id", "question_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    evening_id: Mapped[int] = mapped_column(ForeignKey("evenings.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))


CONTRIBUTION_KINDS = {"vraag": "Een vraag", "inzicht": "Een inzicht"}


class Contribution(Base):
    """Iets wat iemand zelf wil inbrengen op de avond."""

    __tablename__ = "contributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    evening_id: Mapped[int] = mapped_column(ForeignKey("evenings.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()

    @property
    def kind_label(self) -> str:
        return CONTRIBUTION_KINDS.get(self.kind, self.kind)
