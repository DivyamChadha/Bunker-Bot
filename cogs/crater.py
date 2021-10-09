import discord
import asyncpg
import re

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import Optional
from utils.checks import is_clan_coord, is_clan_leader, spam_channel_only


CLAN_ROLES_REGEX = re.compile(r'\b(members|right hand|officer|recruit)\b', re.IGNORECASE)

class crater(commands.Cog):

    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.command()
    async def pvp(self, ctx: BBContext):
        """
        A convinience command to display when pvp is available to play again in LDoE.
        """

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

    async def check_error(self, result: str, error_message: str, ctx: BBContext) -> None:
        if result == 'UPDATE 0' or result == 'DELETE 0':
            await ctx.send(error_message)
        else:
            await ctx.tick(True)

    @commands.group()
    async def clan(self, ctx: BBContext):
        """
        The base command for clan commands
        """
        pass

    @clan.command(name='register')
    @is_clan_coord()
    async def register_clan(self, ctx: BBContext, name: str, leader: discord.User):
        """
        A command to register a clan. Once a clan is registred the clan leader will be able to set 
        the description, tag, banner etc which will be then displayed in all the clan member's profiles.
        """

        # insert the new clan and get the clan_id to also insert the leader as a clan_member
        con = await ctx.get_connection()
        query = '''WITH new_clan AS (INSERT INTO clans.clan (clan_name, leader_id) VALUES ($1, $2) RETURNING clan_id)
                   INSERT INTO clans.clan_members (member_id, clan_id, clan_role)
                   VALUES ($2, (SELECT clan_id FROM new_clan), $3)'''

        try:
            await con.execute(query, name, leader.id, 'Leader')
            await ctx.tick(True)
            self.bot.logger.info('Clan %s with leader %s has been registered by %s', name, str(leader), str(ctx.author))
        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send('You have already registered a clan!')


    @clan.command(name='set-description',aliases=['setdescription'])
    @is_clan_leader()
    @spam_channel_only()
    async def set_description(self, ctx: BBContext, *, description: str):
        """
        A command to set the description of the clan. This can only be set by the clan leader.
        """
        con = await ctx.get_connection()
        query = 'UPDATE clans.clan SET description = $1 WHERE leader_id = $2'
        result = await con.execute(query, description, ctx.author.id)
        await self.check_error(result, 'You are not a leader of a clan', ctx)


    @clan.command(name='set-banner', aliases=['setbanner'])
    @is_clan_leader()
    @spam_channel_only()
    async def set_banner(self, ctx: BBContext, url: str):
        """
        A command to set the clan banner. This can only be set by the clan leader.
        """

        con = await ctx.get_connection()
        query = 'UPDATE clans.clan SET banner_url = $1 WHERE leader_id = $2'

        result = await con.execute(query, url, ctx.author.id)
        await self.check_error(result, 'You are not a leader of a clan', ctx)

    @clan.command(name='add-member', aliases=['addmember'])
    @is_clan_leader()
    @spam_channel_only()
    async def add_member(self, ctx: BBContext, member: discord.Member, *, role: Optional[str]):
        """
        A command to add a user to the clan. This can only be used by the clan leader.
        """

        role = 'Member' if role is None else role
        # if no role is specified or they misspelled the role, their default role is member
        if CLAN_ROLES_REGEX.search(role.lower()):
            role = role.capitalize()
        else:
            role = 'Member'

        con = await ctx.get_connection()
        query = '''INSERT INTO clans.clan_members(member_id, clan_id, clan_role) VALUES ($1,
                (SELECT clan_id FROM clans.clan WHERE leader_id = $2), $3)'''

        # error handling
        try:
            await con.execute(query, member.id, ctx.author.id, role)
            await ctx.tick(True)

        except asyncpg.exceptions.NotNullViolationError:
            await ctx.send('You are not a leader of a clan!')

        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send('Member is already in a clan!')

    @clan.command(name='remove-member', aliases=['removemmember'])
    @is_clan_leader()
    @spam_channel_only()
    async def remove_member(self, ctx: BBContext, member: discord.Member):
        """
        A command to remove a user from the clan. This can only be used by the clan leader.
        """

        con = await ctx.get_connection()
        query = '''DELETE FROM clans.clan_members WHERE 
                   clan_id = (SELECT clan_id FROM clans.clan WHERE leader_id = $2)
                   AND member_id = $1'''

        result = await con.execute(query, member.id, ctx.author.id)
        await self.check_error(result, 'Member is not in a clan, not in your clan, or you are not leader of a clan', ctx)

    @clan.command(name='set-language', aliases=['sl', 'setlanguage'])
    @is_clan_leader()
    @spam_channel_only()
    async def set_language(self, ctx: BBContext, language: str):
        """
        A command to set the language for the clan. This can only be set by the clan leader.
        """

        con = await ctx.get_connection()
        query = 'UPDATE clans.clan SET clan_language = $1 WHERE leader_id = $2'

        result = await con.execute(query, language, ctx.author.id)
        await self.check_error(result, 'You are not a leader of a clan', ctx)

    @clan.command(name='set-tag', aliases=['settag'])
    @is_clan_leader()
    @spam_channel_only()
    async def set_clan_tag(self, ctx: BBContext, tag: str):
        """
        A command to set the clan tag. This can only be set by the clan leader.
        """

        tag = tag.upper()

        con = await ctx.get_connection()
        query = 'UPDATE clans.clan SET clan_tag = $1 WHERE leader_id = $2'

        result = await con.execute(query, tag, ctx.author.id)
        await self.check_error(result, 'You are not a leader of a clan', ctx)

    @clan.command(aliases=['l', 'leaveclan'])
    @spam_channel_only()
    async def leave(self, ctx: BBContext):
        """
        A command to leave a clan you were added to.
        """

        con = await ctx.get_connection()

        query = '''WITH existing_clan as (SELECT * FROM clans.clan WHERE leader_id = $1)
                   DELETE FROM clans.clan_members WHERE member_id = $1
                   AND (SELECT leader_id FROM existing_clan) IS NULL'''

        result = await con.execute(query, ctx.author.id)
        await self.check_error(result, 'You cannot leave if you are not in a clan or are a clan leader.', ctx)


    @clan.command(name='swap-leader', aliases=['swapleader'])
    @is_clan_coord()
    async def swap_leader(self, ctx:BBContext, old_leader: discord.Member, new_leader: discord.Member):
        """
        A command to change the leader of a clan.
        """

        con = await ctx.get_connection()

        # 1. updates leader_id in the clan table first
        # 2. updates the role of the demoted leader
        # 3. updates the role of the new leader in clan_members

        query = '''WITH new_leader AS (UPDATE clans.clan SET leader_id = $2 WHERE leader_id = $1 RETURNING *),
                    updated_member AS (UPDATE clans.clan_members SET clan_role = 'Right Hand' WHERE member_id = $1 AND (SELECT clan_id FROM new_leader) IS NOT NULL RETURNING *)
                    UPDATE clans.clan_members SET clan_role = 'Leader' WHERE member_id = $2 
                    AND (SELECT clan_id FROM new_leader) IS NOT NULL 
                    '''

        result = await con.execute(query, old_leader.id, new_leader.id)
        await self.check_error(result, 'The member specified is not a leader in a clan.', ctx)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(crater(bot))
