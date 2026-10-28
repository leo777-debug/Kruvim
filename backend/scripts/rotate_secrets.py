"""Re-encrypt every stored secret with the current KRUVIM_SECRET_KEY.

    KRUVIM_PREVIOUS_SECRET_KEYS=<old key> python -m scripts.rotate_secrets

Run after deploying a new secret key; afterwards the old key can be removed from KRUVIM_PREVIOUS_SECRET_KEYS."""
from __future__ import annotations

import asyncio

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.core.crypto import rotate
from app.db.session import session_scope
from app.models import Connector, ProviderConfig, SocialConnection

COLUMNS = ((ProviderConfig, "api_key_enc"), (Connector, "secrets_enc"), (SocialConnection, "tokens_enc"))


async def main() -> None:
    done = failed = 0
    async with session_scope() as s:
        for model, column in COLUMNS:
            for row in (await s.execute(select(model).where(getattr(model, column).is_not(None)))).scalars():
                try:
                    setattr(row, column, rotate(getattr(row, column)))
                    done += 1
                except InvalidToken:
                    failed += 1
                    print(f"cannot decrypt {model.__tablename__} {row.id}: add the key it was written with")
    print(f"re-encrypted {done} secrets; {failed} unreadable")


if __name__ == "__main__":
    asyncio.run(main())
