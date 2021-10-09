import asyncio
import asyncpg
import logging

from bot import BunkerBot
from configparser import ConfigParser
from utils import logs

try:
    import uvloop
except ImportError:
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def run_bot():
    config = ConfigParser()
    config.read('confidential.ini')

    logger = logs.create_logger('bunkerbot', level=logging.DEBUG)
    logger.addHandler(logs.create_handler('bunkerbot'))

    dpy_logger = logs.create_logger('discord', level=logging.DEBUG)
    dpy_logger.addHandler(logs.create_handler('discord'))

    loop = asyncio.get_event_loop()

    psql = config['postgreSQL']
    pool = loop.run_until_complete(asyncpg.create_pool(database=psql['name'], user=psql['user'], password=psql['password']))

    if not pool:
        raise RuntimeError('Connection pool not acquired. Terminating connection...')

    bot = BunkerBot()
    bot.pool = pool
    bot.logger = logger

    bot.load_extension('jishaku')
    bot.load_extension('manager')
    bot.run(config['discord']['token'])

    for handler in dpy_logger.handlers:
        handler.close()

    for handler in logger.handlers:
        handler.close()

run_bot()
