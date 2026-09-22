from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, Milestone, Task
from app.schemas import GoalOut, MilestoneOut


async def progress(session: AsyncSession, goal: Goal) -> int:
    """Manual override wins; else milestone completion; else linked-task completion."""
    if goal.manual_progress is not None:
        return goal.manual_progress
    if goal.milestones:
        return round(100 * sum(m.done for m in goal.milestones) / len(goal.milestones))
    total = (await session.execute(select(func.count()).select_from(Task).where(Task.goal_id == goal.id, Task.deleted_at.is_(None)))).scalar_one()
    if not total:
        return 100 if goal.status == "done" else 0
    done = (await session.execute(select(func.count()).select_from(Task).where(
        Task.goal_id == goal.id, Task.status == "done", Task.deleted_at.is_(None)))).scalar_one()
    return round(100 * done / total)


async def to_out(session: AsyncSession, goal: Goal) -> GoalOut:
    return GoalOut(
        id=goal.id, title=goal.title, description=goal.description, target_date=goal.target_date, status=goal.status,
        progress=await progress(session, goal), updated_at=goal.updated_at,
        milestones=[MilestoneOut.model_validate(m) for m in goal.milestones],
    )


async def create_goal(session: AsyncSession, user_id: str, title: str, *, description: str = "", target_date=None,
                      milestones: list[str] | None = None) -> Goal:
    goal = Goal(user_id=user_id, title=title.strip(), description=description, target_date=target_date)
    goal.milestones = [Milestone(title=m) for m in (milestones or [])]
    session.add(goal)
    await session.flush()
    return goal


async def active_goals(session: AsyncSession, user_id: str) -> list[Goal]:
    q = select(Goal).where(Goal.user_id == user_id, Goal.status == "active", Goal.deleted_at.is_(None)).order_by(Goal.created_at)
    return list((await session.execute(q)).scalars())
