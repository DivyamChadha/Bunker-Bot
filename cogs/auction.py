import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands


class auction(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot


def setup(bot: BunkerBot) -> None:
    bot.add_cog(auction(bot))