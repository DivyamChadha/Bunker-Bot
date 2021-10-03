from __future__ import annotations
import asyncpg
import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands, tasks
from typing import Callable, Dict, List, Union
from utils.constants import TABLE_LB_CONFIG, TABLE_LEADERBOARD, TICKET, NO_XP_CHANNELS, COINS
from utils.levels import LeaderboardPlayer
from utils.views import EmbedViewPagination


DEFAULT_XP = 0.01
XP_COOLDOWN = commands.CooldownMapping.from_cooldown(1.0, 60.0, commands.BucketType.user)


class LevelConfigPages(EmbedViewPagination):
    def __init__(self, user_id: int, data: List[asyncpg.Record]):
        super().__init__(data, per_page=10)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user_id == interaction.user.id # type: ignore

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        description = '\n'.join(f'Level: **{row["level"]}**\nXP: **{row["required_xp"]}**, Prize: **{row["prize"]}**' for row in data)
        return discord.Embed(title='Levels', description=description)


class LeaderboardPages(EmbedViewPagination):
    def __init__(self, user_id: int, data: List[asyncpg.Record], *, bot: BunkerBot):
        super().__init__(data, per_page=10)
        self.user_id = user_id
        self.get_user: Callable[[int], Union[discord.User, int]] = lambda user_id: bot.get_user(user_id) or user_id

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        start = (self.current_page-1) * self.per_page
        description = '\n'.join(f'{start+i+1}) {self.get_user(user_id)}: {xp}' for i, (user_id, xp) in enumerate(data))
        return discord.Embed(title='Leaderboard', description=description).set_footer(text=f'Page {self.current_page}/{self.max_pages}')


class leaderboard(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.xp_channel_mapping : Dict[int, int] = {}

        self.xp_task.start()

    def cog_unload(self):
        self.xp_task.cancel()

    @commands.Cog.listener(name='on_message')
    async def add_message(self, message: discord.Message) -> None:
        """
        Increments the xp for a player in the xp cache

        Parameters
        -----------
        message: discord.Message
            message received by the listener
        """
        if message.author.bot or message.channel.id in NO_XP_CHANNELS:
            return

        bucket = XP_COOLDOWN.get_bucket(message)
        if bucket.update_rate_limit():
            return

        try:
            self.bot.xp_cache[message.author.id] += self.xp_channel_mapping.get(message.channel.id, DEFAULT_XP)
        except KeyError:
            self.bot.xp_cache[message.author.id] = self.xp_channel_mapping.get(message.channel.id, DEFAULT_XP)

    @tasks.loop(minutes=10)
    async def xp_task(self) -> None:
        """
        Task that updates the xp from memory to db every 10 minutes
        """
        await self.bot.update_xp()

    @commands.group()
    async def level(self, ctx: BBContext):
        pass

    @level.group(invoke_without_subcommand=True)
    @commands.has_guild_permissions(administrator=True)
    async def config(self, ctx: BBContext):
        con = await ctx.get_connection()
        query = f'SELECT level, required_xp, prize FROM {TABLE_LB_CONFIG}'

        rows = await con.fetch(query)
        view = LevelConfigPages(ctx.author.id, rows)
        await view.start(ctx.channel)

    @commands.command(name='leaderboard', aliases=['lb'])
    @commands.cooldown(1, 60.0, commands.BucketType.member)
    async def show_leaderboard(self, ctx: BBContext):
        con = await ctx.get_connection()
        query = f'SELECT user_id, xp FROM {TABLE_LEADERBOARD} ORDER BY xp DESC LIMIT 100'
        rows = await con.fetch(query)
        view = LeaderboardPages(ctx.author.id, rows, bot=self.bot)
        await view.start(ctx.channel)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(leaderboard(bot))
