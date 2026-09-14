"""BalanceQueue: concurrency-safe 5v5 Elo matchmaking."""

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "balancequeue.api:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8010")),
    )
