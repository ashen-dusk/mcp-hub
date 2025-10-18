from django.apps import AppConfig
import asyncio
import logging
import sys

def run_async_from_sync(coro):
    """Helper to run an async coroutine from a sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        logging.info("Scheduling async task in existing event loop.")
        return asyncio.ensure_future(coro)
    else:
        logging.info("Creating new event loop to run async task.")
        return asyncio.run(coro)


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        """Called when Django starts."""
        # Do not run startup logic for management commands that shouldn't touch the DB yet
        is_management_command = any(
            cmd in sys.argv for cmd in ['makemigrations', 'migrate', 'collectstatic', 'check']
        )
        if is_management_command:
            logging.info("Skipping MCP initialization for management command.")
            return

        # Import MCP manager to ensure it's initialized
        # Note: Redis TTL handles automatic cleanup of expired connections,
        # so no manual reset is needed on startup
        from .mcp.manager import mcp
        logging.info("MCP manager initialized. Redis TTL handles connection cleanup automatically.")
