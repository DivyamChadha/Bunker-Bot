import logging
import re
from typing import Callable, List, Set

import asyncpg
import discord

from context import BBContext
from discord.ext import commands


async def release_connection(ctx: BBContext) -> None:
    await ctx.release_connection()


class BunkerBot(commands.Bot):
    # db: database.DatabaseManager # TODO remove?
    pool: asyncpg.Pool
    logger: logging.Logger
    
    def __init__(self):

        allowed_mentions = discord.AllowedMentions(everyone=False, users=True, roles=True, replied_user=True)
        intents = discord.Intents(
            bans=True,
            emojis=True,
            guilds=True,
            members=True,
            guild_messages=True,
            guild_reactions=True, 
        )
        member_cache_flags = discord.MemberCacheFlags.from_intents(intents)
        owner_id = 378957690073907201
        command_prefix: Callable[[BunkerBot, discord.Message], List[str]] = lambda bot, message: [f'<@!{bot.user.id}> ', f'<@{bot.user.id}> ', 'b!', 'B!', 'bb ', 'Bb ', 'BB '] # type: ignore

        super().__init__(
            allowed_mentions = allowed_mentions,
            case_insensitive=True,
            chunk_guilds_at_startup = False,
            command_prefix = command_prefix,
            intents=intents,
            member_cache_flags = member_cache_flags,
            owner_id=owner_id
        )

        self._after_invoke = release_connection
        self.blacklist: Set[int] = set()
        self.times_code_is_asked: int = 0

    async def close(self):
        try:
            await self.pool.close()
        except:
            pass
        finally:
            await super().close()
            self.logger.info('Bot shutting down')

    async def get_context(self, message: discord.Message, *, cls=BBContext):
        return await super().get_context(message, cls=cls)
    
    async def on_message(self, message: discord.Message):
        if message.author.id in self.blacklist:
            return
        return await super().on_message(message)

