"""Durably publish lending events to Kafka from the SQL outbox."""

import json
import logging
import os
from datetime import datetime, timezone
from threading import Event, Thread

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LoanOutbox

logger = logging.getLogger("lending-outbox")


class OutboxWorker:
    """Retries unpublished rows so API requests do not depend on Kafka uptime."""

    def __init__(self, engine, bootstrap_servers: str, topic: str):
        self.engine = engine
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="lending-kafka-outbox", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            producer = None
            try:
                from kafka import KafkaProducer

                producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers,
                    acks="all",
                    retries=5,
                    value_serializer=lambda value: json.dumps(value, separators=(",", ":")).encode("utf-8"),
                    key_serializer=lambda value: value.encode("utf-8"),
                )
                while not self.stop_event.is_set():
                    with Session(self.engine) as session:
                        statement = (
                            select(LoanOutbox)
                            .where(LoanOutbox.published_at.is_(None))
                            .order_by(LoanOutbox.created_at)
                            .limit(25)
                        )
                        if self.engine.dialect.name == "postgresql":
                            statement = statement.with_for_update(skip_locked=True)
                        rows = session.scalars(statement).all()
                        if not rows:
                            session.rollback()
                            self.stop_event.wait(1)
                            continue
                        for row in rows:
                            try:
                                producer.send(
                                    self.topic,
                                    key=row.event_json["aggregateId"],
                                    value=row.event_json,
                                ).get(timeout=15)
                                row.published_at = datetime.now(timezone.utc)
                            except Exception as error:
                                row.attempts += 1
                                logger.warning("kafka_outbox_publish_failed event_id=%s error=%s", row.event_id, type(error).__name__)
                        session.commit()
            except Exception as error:
                logger.warning("kafka_outbox_worker_unavailable error=%s", type(error).__name__)
                self.stop_event.wait(5)
            finally:
                if producer is not None:
                    try:
                        producer.close(timeout=5)
                    except Exception as error:
                        logger.debug("kafka_outbox_close_failed error=%s", type(error).__name__)


def start_outbox_worker(engine) -> OutboxWorker | None:
    """Starts Kafka publishing only when the deployment config enables it."""
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not bootstrap_servers:
        return None
    topic = os.environ.get("KAFKA_INPUT_TOPIC", "library.events.v1")
    return OutboxWorker(engine, bootstrap_servers, topic)
