import discord
import os

from bot import BunkerBot
from discord.ext import commands


class manager(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

        for filename in os.listdir('cogs'):  # loads all the cogs in cogs folder
            if not filename.startswith('_') and filename.endswith('.py'):
                self.bot.load_extension(f"cogs.{filename[:-3]}")


def setup(bot: BunkerBot):
    bot.add_cog(manager(bot))
