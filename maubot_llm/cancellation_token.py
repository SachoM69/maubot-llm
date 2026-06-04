from asyncio import Task
from types import CoroutineType
import asyncio

class LlmCancellationToken():
    def __init__(self):
        self.cancellation_requested = False
        self.dependent_tasks = []

    cancellation_requested: bool
    dependent_tasks: list[Task]

    def add_task(self, task : Task):
        self.dependent_tasks.append(task)

    def remove_task(self, task: Task):
        self.dependent_tasks.remove(task)

    async def run_cancellable_coro(self, coro: CoroutineType):
        task = asyncio.create_task(coro)
        if self.cancellation_requested:
            task.cancel()
            return
        self.add_task(task)
        response = await task
        self.remove_task(task)
        return response

    def cancel(self):
        for task in self.dependent_tasks:
            task.cancel()
        self.cancellation_requested = True

    def is_cancellation_requested(self):
        return self.cancellation_requested