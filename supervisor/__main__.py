import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)

from supervisor.supervisor import Supervisor


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    supervisor = Supervisor(dsn=dsn, redis_url=redis_url)
    asyncio.run(supervisor.run())


if __name__ == "__main__":
    main()
