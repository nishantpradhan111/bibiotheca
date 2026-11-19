"""Reservation persistence operations."""

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import Reservation, ReservationCreate, ReservationOutbox, ReservationStatus


class DuplicateReservationError(Exception):
    pass


def configured_engine() -> Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///./reservation.db")
    return create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})


class ReservationStore:
    """Owns database operations while the API owns HTTP concerns."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, data: ReservationCreate, ready: bool, copy_id: UUID | None = None) -> Reservation:
        with Session(self.engine) as session:
            duplicate = session.scalar(
                select(Reservation).where(
                    Reservation.book_id == data.book_id,
                    Reservation.member_id == data.member_id,
                    Reservation.status.in_([ReservationStatus.READY, ReservationStatus.WAITLISTED]),
                )
            )
            if duplicate:
                raise DuplicateReservationError
            active = session.scalar(
                select(func.count()).select_from(Reservation).where(
                    Reservation.book_id == data.book_id,
                    Reservation.status.in_([ReservationStatus.READY, ReservationStatus.WAITLISTED]),
                )
            )
            reservation = Reservation(
                book_id=data.book_id,
                member_id=data.member_id,
                status=ReservationStatus.READY if ready and active == 0 else ReservationStatus.WAITLISTED,
                queue_position=(active or 0) + 1,
                copy_id=copy_id if ready and active == 0 else None,
            )
            session.add(reservation)
            session.flush()
            # Keep the event in the same transaction so a saved reservation is never silently omitted.
            event_id = uuid4()
            created_at = reservation.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            occurred_at = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            session.add(ReservationOutbox(
                event_id=str(event_id),
                event_json={
                    "eventId": str(event_id),
                    "eventType": "ReservationCreated",
                    "schemaVersion": 1,
                    "occurredAt": occurred_at,
                    "aggregateType": "Reservation",
                    "aggregateId": str(reservation.reservation_id),
                    "payload": {
                        "reservationId": str(reservation.reservation_id),
                        "bookId": str(reservation.book_id),
                        "memberId": str(reservation.member_id),
                        "reservationStatus": reservation.status.value,
                        "copyId": str(reservation.copy_id) if reservation.copy_id else None,
                    },
                },
            ))
            session.commit()
            session.refresh(reservation)
            return reservation

    def get(self, reservation_id: UUID) -> Reservation | None:
        with Session(self.engine) as session:
            return session.get(Reservation, reservation_id)

    def list_for_member(self, member_id: UUID, limit: int, offset: int) -> tuple[list[Reservation], int]:
        statement = select(Reservation).where(Reservation.member_id == member_id)
        count_statement = select(func.count()).select_from(Reservation).where(Reservation.member_id == member_id)
        with Session(self.engine) as session:
            items = session.scalars(
                statement.order_by(Reservation.created_at.desc(), Reservation.reservation_id)
                .limit(limit).offset(offset)
            ).all()
            return items, session.scalar(count_statement) or 0

    def cancel(self, reservation_id: UUID) -> Reservation | None:
        with Session(self.engine) as session:
            reservation = session.get(Reservation, reservation_id)
            if reservation is None:
                return None
            if reservation.status == ReservationStatus.CANCELLED:
                return reservation
            was_ready = reservation.status == ReservationStatus.READY
            reservation.status = ReservationStatus.CANCELLED
            if was_ready:
                next_reservation = session.scalar(
                    select(Reservation)
                    .where(
                        Reservation.book_id == reservation.book_id,
                        Reservation.status == ReservationStatus.WAITLISTED,
                    )
                    .order_by(Reservation.queue_position, Reservation.created_at)
                    .limit(1)
                )
                if next_reservation:
                    next_reservation.status = ReservationStatus.READY
                    next_reservation.copy_id = reservation.copy_id
            session.commit()
            session.refresh(reservation)
            return reservation


def initialize_database(engine: Engine) -> None:
    from app.models import Base

    Base.metadata.create_all(engine)
