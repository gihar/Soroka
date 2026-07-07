"""Характеризация QueueRepository: очередь обработки (#32).

Эталон поведения — методы монолита Database (save_queue_task,
update_queue_task_status, update_queue_task_message_id,
get_pending_queue_tasks, cleanup_completed_queue_tasks).
"""
import pytest


@pytest.fixture
async def queue_repo(test_db):
    from src.database.queue_repo import QueueRepository
    return QueueRepository(test_db)


def _task(task_id: str, **overrides) -> dict:
    base = {
        "task_id": task_id,
        "user_id": 1,
        "chat_id": 100,
        "file_name": "встреча.mp3",
        "template_id": 1,
        "llm_provider": "openai",
        "status": "queued",
        "created_at": "2026-07-07 10:00:00",
    }
    base.update(overrides)
    return base


async def test_saved_task_round_trip_with_defaults(queue_repo):
    assert await queue_repo.save_queue_task(_task("t-1")) is True

    [task] = await queue_repo.get_pending_queue_tasks()
    assert task["task_id"] == "t-1"
    assert task["language"] == "ru"          # дефолт
    assert task["is_external_file"] == 0     # дефолт
    assert task["priority"] == 1             # дефолт
    assert task["message_id"] is None
    assert task["started_at"] is None
    assert task["error_message"] is None


async def test_duplicate_task_id_is_swallowed_as_false(queue_repo):
    """PK-конфликт не поднимает исключение — контракт: False."""
    assert await queue_repo.save_queue_task(_task("t-dup")) is True
    assert await queue_repo.save_queue_task(_task("t-dup")) is False


async def test_pending_tasks_ordered_by_priority_then_age(queue_repo):
    await queue_repo.save_queue_task(_task("old-low", priority=1, created_at="2026-07-07 09:00:00"))
    await queue_repo.save_queue_task(_task("new-low", priority=1, created_at="2026-07-07 11:00:00"))
    await queue_repo.save_queue_task(_task("high", priority=5, created_at="2026-07-07 12:00:00"))
    await queue_repo.save_queue_task(_task("done", status="completed"))

    pending = [t["task_id"] for t in await queue_repo.get_pending_queue_tasks()]

    assert pending == ["high", "old-low", "new-low"]  # только queued


async def test_status_update_with_and_without_started_at(queue_repo, test_db):
    await queue_repo.save_queue_task(_task("t-2"))

    assert await queue_repo.update_queue_task_status(
        "t-2", "processing", started_at="2026-07-07 10:01:00") is True
    async with test_db.connect() as conn:
        row = await (await conn.execute(
            "SELECT status, started_at, error_message FROM queue_tasks WHERE task_id = 't-2'"
        )).fetchone()
    assert (row["status"], row["started_at"]) == ("processing", "2026-07-07 10:01:00")

    # без started_at — прежний started_at сохраняется, статус и ошибка обновляются
    assert await queue_repo.update_queue_task_status("t-2", "failed", error_message="LLM 402") is True
    async with test_db.connect() as conn:
        row = await (await conn.execute(
            "SELECT status, started_at, error_message FROM queue_tasks WHERE task_id = 't-2'"
        )).fetchone()
    assert row["status"] == "failed"
    assert row["started_at"] == "2026-07-07 10:01:00"
    assert row["error_message"] == "LLM 402"


async def test_message_id_update(queue_repo, test_db):
    await queue_repo.save_queue_task(_task("t-3"))

    assert await queue_repo.update_queue_task_message_id("t-3", 424242) is True

    async with test_db.connect() as conn:
        row = await (await conn.execute(
            "SELECT message_id FROM queue_tasks WHERE task_id = 't-3'"
        )).fetchone()
    assert row["message_id"] == 424242


async def test_cleanup_removes_only_old_finished_tasks(queue_repo, test_db):
    await queue_repo.save_queue_task(_task("old-done", status="completed"))
    await queue_repo.save_queue_task(_task("old-failed", status="failed"))
    await queue_repo.save_queue_task(_task("old-queued", status="queued"))
    await queue_repo.save_queue_task(_task("fresh-done", status="completed"))
    async with test_db.connect() as conn:
        await conn.execute(
            "UPDATE queue_tasks SET created_at = DATETIME('now', '-48 hours') "
            "WHERE task_id IN ('old-done', 'old-failed', 'old-queued')"
        )
        await conn.execute(
            "UPDATE queue_tasks SET created_at = DATETIME('now') WHERE task_id = 'fresh-done'"
        )
        await conn.commit()

    removed = await queue_repo.cleanup_completed_queue_tasks(hours=24)

    assert removed == 2  # старые completed/failed; queued не трогаем, свежие тоже
    async with test_db.connect() as conn:
        rows = await (await conn.execute("SELECT task_id FROM queue_tasks")).fetchall()
    assert sorted(r["task_id"] for r in rows) == ["fresh-done", "old-queued"]
