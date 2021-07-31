from __future__ import annotations

import asyncpg
import discord

from discord.ext import commands
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bot import BunkerBot


class BBContext(commands.Context):
    bot: BunkerBot
    con: Optional[asyncpg.Connection] = None
    
    async def get_connection(self) -> asyncpg.Connection:
        if not self.con or self.con.is_closed: # TODO check if released con evals to be true
            self.con = await self.bot.pool.acquire()
        
        return self.con # type: ignore
    
    async def release_connection(self) -> None:
        if self.con:
            await self.bot.pool.release(self.con)

    async def tick(self, value: bool = True) -> None:
        reaction = '\N{WHITE HEAVY CHECK MARK}' if value else '\N{CROSS MARK}'
        await self.react(reaction)

    async def react(self, reaction: str):
        try:
            if isinstance(self.message, discord.Message):
                await self.message.add_reaction(reaction)
        except discord.HTTPException:
            pass