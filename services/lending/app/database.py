"""PostgreSQL persistence for lending."""

import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, Loan, LoanCreate, LoanOutbox


class DuplicateLoanError(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///./lending.db")
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def configured_loan_period_days() -> int:
    try:
        days = int(os.environ.get("LOAN_PERIOD_DAYS", "14"))
    except ValueError as error:
        raise ValueError("LOAN_PERIOD_DAYS must be a positive integer") from error
    if days < 1:
        raise ValueError("LOAN_PERIOD_DAYS must be a positive integer")
    return days


class LendingStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def ready(self) -> None:
        with Session(self.engine) as session:
            session.execute(text("SELECT 1"))

    def create(
        self,
        data: LoanCreate,
        book_id: UUID,
        loan_period_days: int,
        checked_out_at: datetime | None = None,
    ) -> Loan:
        checkout_time = checked_out_at or datetime.now(timezone.utc)
        loan = Loan(
            book_id=book_id,
            member_id=data.member_id,
            copy_id=data.copy_id,
            reservation_id=data.reservation_id,
            checked_out_at=checkout_time,
            due_at=checkout_time + timedelta(days=loan_period_days),
        )
        with Session(self.engine) as session:
            active_loan = session.scalar(
                select(Loan.loan_id).where(
                    Loan.copy_id == data.copy_id,
                    Loan.returned_at.is_(None),
                )
            )
            if active_loan is not None:
                raise DuplicateLoanError("Copy already has an active loan")
            existing_reservation = session.scalar(
                select(Loan.loan_id).where(Loan.reservation_id == data.reservation_id)
            )
            if existing_reservation is not None:
                raise DuplicateLoanError("Reservation has already been checked out")
            session.add(loan)
            try:
                session.flush()
                # Persist the analytics event with the checkout so retries cannot lose it.
                session.add(self._outbox_row(loan, "LoanCheckedOut", loan.checked_out_at))
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise DuplicateLoanError("Copy or reservation already has a loan") from error
            session.refresh(loan)
            return loan

    def get(self, loan_id: UUID) -> Loan | None:
        with Session(self.engine) as session:
            return session.get(Loan, loan_id)

    def list(
        self,
        book_id: UUID | None,
        member_id: UUID | None,
        active_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Loan], int]:
        statement = select(Loan)
        count_statement = select(func.count()).select_from(Loan)
        if book_id is not None:
            statement = statement.where(Loan.book_id == book_id)
            count_statement = count_statement.where(Loan.book_id == book_id)
        if member_id is not None:
            statement = statement.where(Loan.member_id == member_id)
            count_statement = count_statement.where(Loan.member_id == member_id)
        if active_only:
            statement = statement.where(Loan.returned_at.is_(None))
            count_statement = count_statement.where(Loan.returned_at.is_(None))
        with Session(self.engine) as session:
            loans = session.scalars(
                statement.order_by(Loan.checked_out_at.desc(), Loan.loan_id).limit(limit).offset(offset)
            ).all()
            total = session.scalar(count_statement) or 0
            return loans, total

    def return_loan(self, loan_id: UUID, returned_at: datetime | None = None) -> tuple[Loan | None, bool]:
        with Session(self.engine) as session:
            transition_time = returned_at or datetime.now(timezone.utc)
            changed = session.execute(
                update(Loan).where(Loan.loan_id == loan_id, Loan.returned_at.is_(None))
                .values(returned_at=transition_time)
            ).rowcount == 1
            loan = session.get(Loan, loan_id)
            if changed and loan is not None:
                # The outbox row shares the return transaction and its deterministic event ID.
                session.add(self._outbox_row(loan, "LoanReturned", transition_time))
            session.commit()
            if loan is not None:
                session.refresh(loan)
            return loan, changed

    @staticmethod
    def _outbox_row(loan: Loan, event_type: str, occurred_at: datetime) -> LoanOutbox:
        event_id = uuid5(NAMESPACE_URL, f"digital-library/loans/{loan.loan_id}/{event_type}")
        timestamp = occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return LoanOutbox(
            event_id=str(event_id),
            event_json={
                "eventId": str(event_id),
                "eventType": event_type,
                "schemaVersion": 1,
                "occurredAt": timestamp,
                "aggregateType": "Loan",
                "aggregateId": str(loan.loan_id),
                "payload": {
                    "loanId": str(loan.loan_id),
                    "bookId": str(loan.book_id),
                    "memberId": str(loan.member_id),
                    "copyId": str(loan.copy_id),
                    "reservationId": str(loan.reservation_id),
                },
            },
        )


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
