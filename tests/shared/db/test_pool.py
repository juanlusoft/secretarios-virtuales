import pytest
import asyncpg
from uuid import uuid4
from shared.db.pool import DatabasePool

pytestmark = pytest.mark.asyncio

TEST_DSN = "postgresql://svuser:svpassword@localhost:5432/secretarios"

async def test_pool_sets_employee_context():
    employee_id = uuid4()
    pool = DatabasePool(TEST_DSN, employee_id)
    await pool.connect()

    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT current_setting('app.current_employee_id', true)"
        )
        assert result == str(employee_id)

    await pool.close()

async def test_different_pools_have_different_contexts():
    id_a, id_b = uuid4(), uuid4()
    pool_a = DatabasePool(TEST_DSN, id_a)
    pool_b = DatabasePool(TEST_DSN, id_b)
    await pool_a.connect()
    await pool_b.connect()

    async with pool_a.acquire() as conn_a:
        async with pool_b.acquire() as conn_b:
            val_a = await conn_a.fetchval(
                "SELECT current_setting('app.current_employee_id', true)"
            )
            val_b = await conn_b.fetchval(
                "SELECT current_setting('app.current_employee_id', true)"
            )
            assert val_a == str(id_a)
            assert val_b == str(id_b)

    await pool_a.close()
    await pool_b.close()
