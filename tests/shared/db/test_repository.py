import pytest
from uuid import uuid4
from shared.db.pool import DatabasePool
from shared.db.repository import Repository

pytestmark = pytest.mark.asyncio

TEST_DSN = "postgresql://svuser:svpassword@localhost:5432/secretarios"


@pytest.fixture
async def pool_and_employee():
    conn = await __import__("asyncpg").connect(TEST_DSN)
    employee_id = uuid4()
    await conn.execute(
        "INSERT INTO employees (id, name) VALUES ($1, $2)",
        employee_id, f"test-{employee_id}"
    )
    await conn.close()

    pool = DatabasePool(TEST_DSN, employee_id)
    await pool.connect()
    yield pool, employee_id

    await pool.close()
    conn = await __import__("asyncpg").connect(TEST_DSN)
    await conn.execute("DELETE FROM employees WHERE id = $1", employee_id)
    await conn.close()


async def test_save_and_retrieve_conversation(pool_and_employee):
    pool, employee_id = pool_and_employee
    async with pool.acquire() as conn:
        repo = Repository(conn, employee_id)
        await repo.save_conversation("user", "hola mundo")
        convs = await repo.get_recent_conversations(limit=5)

    assert len(convs) == 1
    assert convs[0].content == "hola mundo"
    assert convs[0].role == "user"
    assert convs[0].employee_id == employee_id


async def test_isolation_between_employees(pool_and_employee):
    pool_a, id_a = pool_and_employee

    conn_raw = await __import__("asyncpg").connect(TEST_DSN)
    id_b = uuid4()
    await conn_raw.execute(
        "INSERT INTO employees (id, name) VALUES ($1, $2)", id_b, f"test-{id_b}"
    )
    await conn_raw.close()

    pool_b = DatabasePool(TEST_DSN, id_b)
    await pool_b.connect()

    try:
        async with pool_a.acquire() as conn:
            await Repository(conn, id_a).save_conversation("user", "secreto de A")

        async with pool_b.acquire() as conn:
            convs = await Repository(conn, id_b).get_recent_conversations()

        assert len(convs) == 0
    finally:
        await pool_b.close()
        conn_raw = await __import__("asyncpg").connect(TEST_DSN)
        await conn_raw.execute("DELETE FROM employees WHERE id = $1", id_b)
        await conn_raw.close()


async def test_save_and_search_document(pool_and_employee):
    pool, employee_id = pool_and_employee
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / str(employee_id)
    tmp.mkdir(parents=True, exist_ok=True)
    filepath = str(tmp / "test.txt")
    pathlib.Path(filepath).write_text("contenido de prueba")

    embedding = [0.1] * 1024

    async with pool.acquire() as conn:
        repo = Repository(conn, employee_id)
        await repo.save_document(
            filename="test.txt",
            filepath=filepath,
            content_text="contenido de prueba",
            embedding=embedding,
            mime_type="text/plain",
        )
        results = await repo.search_documents(embedding=embedding, limit=3)

    assert len(results) == 1
    assert results[0].filename == "test.txt"
