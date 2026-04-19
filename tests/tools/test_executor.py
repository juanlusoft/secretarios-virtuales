import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shared.tools.executor import ToolExecutor


@pytest.fixture
def mock_ssh_store():
    store = AsyncMock()
    store.list_all.return_value = [{"name": "srv", "host": "1.2.3.4", "port": 22, "user": "admin"}]
    store.save = AsyncMock()
    return store


@pytest.fixture
def executor(mock_ssh_store):
    return ToolExecutor(ssh_store=mock_ssh_store)


async def test_bash_echo(executor):
    result = await executor.run("bash", {"command": "echo hello"})
    assert "hello" in result


async def test_list_dir(executor, tmp_path):
    (tmp_path / "file.txt").write_text("x")
    result = await executor.run("list_dir", {"path": str(tmp_path)})
    assert "file.txt" in result


async def test_write_and_read_file(executor, tmp_path):
    path = str(tmp_path / "test.txt")
    await executor.run("write_file", {"path": path, "content": "hola"})
    result = await executor.run("read_file", {"path": path})
    assert "hola" in result


async def test_ssh_list(executor, mock_ssh_store):
    result = await executor.run("ssh_list", {})
    assert "srv" in result
    assert "1.2.3.4" in result


async def test_ssh_save(executor, mock_ssh_store):
    await executor.run("ssh_save", {"name": "nuevo", "host": "5.6.7.8", "user": "root", "password": "pw"})
    mock_ssh_store.save.assert_called_once_with(
        name="nuevo", host="5.6.7.8", user="root", password="pw", ssh_key=None, port=22
    )


async def test_unknown_tool(executor):
    result = await executor.run("nonexistent", {})
    assert "desconocida" in result.lower()
