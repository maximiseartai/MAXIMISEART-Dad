"""Słuchacz kolejki Skrzynki Zgłoszeń bez Spraw taty, dla testów samej kolejki (``outbox.Listener``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rozliczenia.centrum.outbox import Deliveries, Post


@dataclass
class QueueListener:
    """Wysyłki idą bez zmian i bez wysyłek następczych; ``numbers`` to Uruchomienie i numer issue każdej przyjętej."""

    numbers: list[tuple[str, int]] = field(default_factory=list)

    def prepare(self, post: Post, sent: Deliveries) -> Post | None:
        return post

    def delivered(self, post: Post, number: int) -> Sequence[Post]:
        self.numbers.append((post.run_id, number))
        return ()

    def rejected(self, post: Post) -> None:
        return None
