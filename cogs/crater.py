import discord
import asyncpg

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import Optional, List


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
            f'Next PVP is on {discord.utils.format_dt(next_pvp_time, "t")}, which is in {formatted_time[0]}h {formatted_time[1]}mins {formatted_time[2]}sec')

    @commands.group()
    @commands.has_guild_permissions(administrator=True)
    #base class for clan commands
    async def clan(self, ctx: BBContext):
        pass

    @clan.command()
    async def clanprofile(self, ctx: BBContext):

        con = await ctx.get_connection()
        query = """SELECT clan_name, description, banner_url, clan_role FROM clans.clan_members  
                   INNER JOIN clans.clan ON clan.clan_id = clan_members.clan_id WHERE member_id = $1"""
        args = [query, ctx.author.id]

        data: List[asyncpg.Record] = await con.fetch(*args)

        if len(data) <= 0:
            embed = discord.Embed(title= "No Clan")

        else:
            embed = discord.Embed(title=f'Clan Name: {data[0][0]}', description=f'**Clan Description:** {data[0][1]}')
            embed.set_image(url=data[0][2])
            embed.add_field(name="Name", value=ctx.author.name, inline=False)
            embed.add_field(name="Position", value=data[0][3], inline=False)

        await ctx.send(embed=embed)


    @clan.command()
    async def registerclan(self, ctx: BBContext, name: str, leader: Optional[discord.User]):

        leader_id = ctx.author.id if leader is None else leader.id

        con = await ctx.get_connection()
        query = """WITH new_clan AS (INSERT INTO clans.clan (clan_name, leader_id) VALUES ($1, $2) RETURNING clan_id)
                   INSERT INTO clans.clan_members (member_id, clan_id, clan_role)
                   VALUES ($2, (SELECT clan_id FROM new_clan), $3)"""

        await con.execute(query, name, leader_id, 'Leader')
        await ctx.tick(True)

    @clan.command()
    async def description(self, ctx: BBContext, description: str):
        con = await ctx.get_connection()
        query = "UPDATE clans.clan SET description = $1 WHERE leader_id = $2"

        await con.execute(query, description, ctx.author.id)
        await ctx.tick(True)

    @clan.command()
    async def banner(self, ctx: BBContext, url: str):
        con = await ctx.get_connection()
        query = "UPDATE clans.clan SET banner_url = $1 WHERE leader_id = $2"

        await con.execute(query, url, ctx.author.id)
        await ctx.tick(True)

    @clan.command()
    async def addmember(self, ctx: BBContext, member: discord.Member, role: Optional[str]):
        # if no role is specified, their role is member
        role = "Member" if role is None else role

        con = await ctx.get_connection()
        query = """INSERT INTO clans.clan_members(member_id, clan_id, clan_role) VALUES ($1,
                (SELECT clan_id FROM clans.clan WHERE leader_id = $2), $3)"""

        await con.execute(query, member.id, ctx.author.id, role)
        await ctx.tick(True)



def setup(bot: BunkerBot) -> None:
    bot.add_cog(crater(bot))
