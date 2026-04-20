import asyncio
import logging
import os

from dotenv import load_dotenv

from supervisor.supervisor import Supervisor

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def main() -> None:
    dsn = os.environ.get("APP_DB_URL", os.environ["DATABASE_URL"])
    redis_url = os.environ["REDIS_URL"]
    alert_bot_token = os.environ.get("ORCHESTRATOR_BOT_TOKEN")
    alert_chat_id = os.environ.get("ORCHESTRATOR_CHAT_ID")
    supervisor = Supervisor(
        dsn=dsn,
        redis_url=redis_url,
        alert_bot_token=alert_bot_token,
        alert_chat_id=alert_chat_id,
    )
    asyncio.run(supervisor.run())


if __name__ == "__main__":
    main()
