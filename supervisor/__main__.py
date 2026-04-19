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
    supervisor = Supervisor(dsn=dsn, redis_url=redis_url)
    asyncio.run(supervisor.run())


if __name__ == "__main__":
    main()
