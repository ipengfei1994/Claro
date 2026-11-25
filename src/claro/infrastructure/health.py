from __future__ import annotations

from sqlalchemy import Engine, text


class DatabaseHealthCheck:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def check(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
