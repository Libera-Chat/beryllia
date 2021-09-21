import asyncio
from datetime  import datetime, timedelta
from typing    import cast

from ircrobots import Bot as BaseBot

from .         import Server

MINUTE = timedelta(minutes=1)

async def cron(bot: BaseBot):
    while True:
        utcnow = datetime.utcnow()
        # wait until the next minute
        await asyncio.sleep(60-utcnow.second)
        # make our timestamp perfectly on-the-minute
        utcnow = (utcnow + MINUTE).replace(second=0, microsecond=0)

        servers = list(bot.servers.values())
        if servers:
            server = cast(Server, servers[0])
            await server.minutely(utcnow)
