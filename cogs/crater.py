import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands


class crater(commands.Cog):

    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.command()
    async def pvp(self, ctx: BBContext):
        current_date = discord.utils.utcnow()

        # check whether or not pvp starts in more than an hour or less than an hour
        hour = 0
        if current_date.hour % 2 == 0:
            hour = current_date.hour + 2
        else:
            hour = current_date.hour + 1

        # next pvp time is the current time in their local timezone, plus 1 or 2 hours
        next_pvp_time = current_date.replace(hour=hour, minute=0, second=0)

        # time left till the next pvp starts
        formatted_time = str(next_pvp_time - current_date).split(':')

        await ctx.send(
            f'Next PVP is on {discord.utils.format_dt(next_pvp_time, "t")}, which is in{formatted_time[0]}h {formatted_time[1]}mins {formatted_time[2]}sec')


def setup(bot: BunkerBot) -> None:
    bot.add_cog(crater(bot))
