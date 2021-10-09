import asyncpg
import discord
import logging

from context import BBContext
from discord.ext import commands
from typing import Callable, Dict, List, Optional, Set, Union


async def release_connection(ctx: BBContext) -> None:
    await ctx.release_connection()


class BunkerBot(commands.Bot):
    pool: asyncpg.Pool
    logger: logging.Logger
    
    def __init__(self):

        allowed_mentions = discord.AllowedMentions(everyone=True, users=True, roles=True, replied_user=True)
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
            chunk_guilds_at_startup = True,
            command_prefix = command_prefix,
            intents=intents,
            member_cache_flags = member_cache_flags,
            owner_id=owner_id
        )

        self._after_invoke = release_connection
        self.beta_testers: Set[int] = set()
        self.blacklist: Set[int] = set()
        self.tags: Set[str] = set()
        self.times_code_is_asked: int = 0
        self.on_time = discord.utils.utcnow()
        self.xp_cache: Dict[int, float] = {}

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        async with self.pool.acquire() as con:
            blacklist = await con.fetchval('SELECT array_agg(user_id) FROM extras.blacklist')
            if blacklist:
                self.blacklist = set(blacklist)

            tags = await con.fetchval('SELECT array_agg(name) FROM tags.names')
            if tags:
                self.tags = set(tags)

            testers = await con.fetchval('SELECT array_agg(user_id) FROM extras.beta_testers')
            if testers:
                self.beta_testers = set(testers)

        return await super().start(token, reconnect=reconnect)

    async def close(self):
        try:
            await self.update_xp()
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

    async def update_xp(self) -> None:
        async with self.pool.acquire() as con:
            _data = self.xp_cache.copy()
            self.xp_cache = {}
            query = 'INSERT INTO events.leaderboard(user_id, xp) \
                     VALUES($1, $2) \
                     ON CONFLICT(user_id) \
                     DO UPDATE SET xp = events.leaderboard.xp + $2'
            await con.executemany(query, _data.items())

    async def getch_member(self, guild: discord.Guild, user_id: int) -> Union[discord.Member, int]:
        member = guild.get_member(user_id)
        if member:
            return member

        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            return user_id
        else:
            return member

    async def getch_user(self, user_id: int) -> Optional[discord.User]:
        user = self.get_user(user_id)
        if user:
            return user
        
        try:
            user = await self.fetch_user(user_id)
        except discord.HTTPException:
            return
        else:
            return user
