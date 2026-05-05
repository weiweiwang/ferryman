from app.core.task_manager import TaskManager
from app.models.database import Task
from app.models.schemas import TaskStatus


def test_task_manager_persists_and_updates_task(session):
    manager = TaskManager()

    task = manager.persist_task(session_id="s1", title="Build SEO matrix")
    manager.persist_task_update(
        task.id,
        status=TaskStatus.SUCCESS,
        metadata={"pages": 12},
    )

    db_task = session.get(Task, task.id)
    assert db_task is not None
    assert db_task.status == TaskStatus.SUCCESS
    assert db_task.finished_at is not None
    assert db_task.finished_at.tzinfo is not None
    assert db_task.metadata_["pages"] == 12


def test_task_manager_reuses_similar_active_task(session):
    manager = TaskManager()

    first = manager.persist_task(session_id="s1", title="Build SEO Matrix")
    second = manager.persist_task(session_id="s1", title="SEO Matrix Build")

    assert second.id == first.id
