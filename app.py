from logging import getLogger, FileHandler, StreamHandler, INFO, basicConfig
from asyncio import get_event_loop, create_task, gather
from traceback import format_exc
from pyrogram import idle, Client
from web import serve
from utils import cache_manager
from state import work_loads, multi_clients
from config import CLIENTS_CONFIG  # Changed import to new config structure
from importlib import import_module
import signal
from utils.telegram_logger import send_info, send_error
from utils.db_utils.mongo_client import close_connections


async def shutdowndb():
    close_connections()


basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

loop = get_event_loop()
LOGGER = getLogger(__name__)
LOGGER.setLevel(INFO)


class TokenParser:

    @staticmethod
    def parse_from_config():
        """Parse multi-client tokens from config.py"""
        from config import MULTI_TOKENS

        if not hasattr(import_module('config'), 'MULTI_TOKENS'):
            return {}
        
        tokens = {client_id: token for client_id, token in MULTI_TOKENS.items()}
        return tokens


plugins = {"root": "plugins"}

# Create the main bot client using the config for client_id 0
bot_conf = CLIENTS_CONFIG.get(0)
if not bot_conf:
    raise RuntimeError("CLIENTS_CONFIG must contain a configuration for client_id 0")

bot = Client(
    name="bot",
    api_id=bot_conf["API_ID"],
    api_hash=bot_conf["API_HASH"],
    bot_token=bot_conf["BOT_TOKEN"],
    plugins=plugins,
    sleep_threshold=100,
    workers=80,
    max_concurrent_transmissions=1000,
)


async def start_client(client_id, client_conf):
    """Start a client given client_id and its config dict including API_ID, API_HASH, BOT_TOKEN"""
    try:
        LOGGER.info(f"Starting - Bot Client {client_id}")
        client = await Client(
            name=str(client_id),
            api_id=client_conf["API_ID"],
            api_hash=client_conf["API_HASH"],
            bot_token=client_conf["BOT_TOKEN"],
            sleep_threshold=100,
            no_updates=True,
            in_memory=True,
        ).start()
        work_loads[client_id] = 0
        return client_id, client
    except Exception as e:
        LOGGER.error(f"Failed to start Client - {client_id} Error: {e}", exc_info=True)
        return None


async def initialize_clients():
    try:
        multi_clients[0] = bot
        work_loads[0] = 0
        LOGGER.info("Default client initialized successfully")
    except Exception as e:
        LOGGER.error(f"Failed to initialize default client: {str(e)}")
        multi_clients[0] = bot
        work_loads[0] = 0

    # Prepare additional clients excluding client_id 0
    additional_clients_conf = {cid: conf for cid, conf in CLIENTS_CONFIG.items() if cid != 0}
    if not additional_clients_conf:
        LOGGER.info("No additional Bot Clients found, Using default client")
        return

    n = [create_task(start_client(i, conf)) for i, conf in additional_clients_conf.items()]
    clients = await gather(*n)
    # Filter out None results (failed starts)
    clients = {client_id: client for client_id, client in clients if client}
    multi_clients.update(clients)

    if len(multi_clients) > 1:
        LOGGER.info(f"Multi-Client Mode Enabled with {len(multi_clients)} clients")
    else:
        LOGGER.info("No additional clients were initialized, using default client")


async def init():
    await bot.start()
    LOGGER.info(f"Bot Started Successfully!")

    await initialize_clients()

    LOGGER.info("Starting cache manager...")

    cache_task = create_task(cache_manager.start_cache_updater())

    cache_task.add_done_callback(
        lambda t: (
            handle_cache_crash(t)
            if t.exception()
            else None
        )
    )

    LOGGER.info("Initializing Web Server...")

    loop.create_task(serve())
    LOGGER.info("Backend Started Successfully!")
    await send_info(bot, "🚀 Bot Started Successfully!")
    await idle()


async def handle_cache_crash(task):
    exception = task.exception()
    error_message = f"Cache manager crashed: {exception}"
    LOGGER.error(error_message)
    await send_error(bot, "❌ Cache manager crashed", exception)


async def stop_clients():
    LOGGER.info("Stopping all clients ...")
    await send_info(bot, "Stopping all clients ...")
    await shutdowndb()
    await bot.stop()
    for client_id, client in multi_clients.items():
        if client_id != 0:
            try:
                await client.stop()
                LOGGER.info(f"Client {client_id} stopped successfully")
            except Exception as e:
                LOGGER.error(f"Error stopping client {client_id}: {str(e)}")
                await send_error(bot, f"Error stopping client {client_id}", e)


def signal_handler(sig):
    LOGGER.info(f"Signal {sig} received, initiating shutdown...")

    async def shutdown():
        await send_info(bot, f"⚠️ Signal {sig} received, initiating shutdown...")
        await stop_clients()
        loop.stop()

    loop.create_task(shutdown())


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        loop.run_until_complete(init())
    except KeyboardInterrupt:
        LOGGER.info("keyboard interrupt received, stopping...")
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_clients())
        loop.stop()
