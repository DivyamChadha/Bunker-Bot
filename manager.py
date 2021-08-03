import asyncpg
import discord
import os
import psutil

from bot import BunkerBot
from context import BBContext
from discord.ext import commands


TABLE_BLACKLIST = 'extras.blacklist'


class manager(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.process = psutil.Process(os.getpid())

        for filename in os.listdir('cogs'):  # loads all the cogs in cogs folder
            if not filename.startswith('_') and filename.endswith('.py'):
                self.bot.load_extension(f"cogs.{filename[:-3]}")

    def cog_unload(self) -> None:
        for filename in os.listdir('cogs'):  # unloads all the cogs in cogs folder
            if not filename.startswith('_') and filename.endswith('.py'):
                self.bot.unload_extension(f"cogs.{filename[:-3]}")

    @commands.command()
    @commands.has_guild_permissions(administrator=True)
    async def usage(self, ctx: BBContext) -> None:

        uptime = discord.utils.utcnow() - self.bot.on_time
        days = uptime.days
        hours, rem = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(rem, 60)

        usage = self.process.memory_full_info()
        rss = usage.rss / 1024**2
        vms = usage.vms / 1024**2
        uss = usage.uss / 1024**2
        cpu = self.process.cpu_percent() / psutil.cpu_count()

        embed = discord.Embed(title='Usage')
        embed.add_field(name='Bot', value=f'Bunker code asked: {self.bot.times_code_is_asked}\nUptime: {days} days {hours} hours {minutes} minutes')
        embed.add_field(name='Discord', value=f'ws latency: {self.bot.latency:.2f}')
        embed.add_field(name='Process', value=f'{cpu:.2f}% CPU\n{uss:.2f} mb (uss)\n{rss:.2f} mb(rss)\n{vms:.2f} mb (vms)')

        await ctx.send(embed=embed)
     
    @commands.command()
    @commands.has_guild_permissions(administrator=True)
    async def blacklist(self, ctx: BBContext, person: discord.Member, *, reason: str) -> None:
        query = f'INSERT INTO {TABLE_BLACKLIST}(user_id, reason, date) VALUES($1, $2, $3)'
        con = await ctx.get_connection()
        
        try:
            await con.execute(query, person.id, reason, discord.utils.utcnow())
        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send(f'{person.name} is already blacklisted.')
            return
        else:
            self.bot.blacklist.add(person.id)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(manager(bot))
