"""
Gestão de tasks em background com rastreamento para graceful shutdown.
"""

import asyncio

# Set global de tasks — o lifespan do main.py aguarda estas no shutdown
background_tasks: set[asyncio.Task] = set()


def create_tracked_task(coro) -> asyncio.Task:
    """Cria task rastreada — permite aguardar no shutdown em vez de perder."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task
