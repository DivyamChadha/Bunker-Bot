from __future__ import annotations

import asyncio
import asyncpg
import discord
import logging

from bot import BunkerBot
from context import BBContext
from datetime import datetime, time, timedelta
from discord.ext import commands, tasks
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from utils.checks import is_staff, is_staff_or_guide, has_kick_permissions
from utils.constants import mute_warn_proof, muted, react_banned, LDOE
from utils.converters import TimeConverter
from utils.logs import create_logger, create_handler
from utils.views import EmbedViewPagination


mute_warn_proof = 772491742641520657
muted = 772491741793091597
react_banned = 772491741412589580
LDOE = 772491741412589579

UNMUTE_LOOP_TIME = 60*10


class LogView(discord.ui.View):
    message: discord.Message
    children: List[discord.ui.Button]

    def __init__(
        self, 
        mod: moderation,
        staff:  Union[discord.Member, discord.User], 
        user: Union[discord.Member, discord.User, int],
        *,
        reason: Optional[str] = None,
        ):

        super().__init__(timeout=60*15)
        self.mod = mod
        self.staff = staff
        self.user = user
        self.reason = reason

    @discord.ui.button(label='Ban Request', style=discord.ButtonStyle.red)
    async def ban_req(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:

        try:
            await self.mod._ban_request(
                self.staff,
                self.user,
                self.message.jump_url,
                self.message.id,
                reason = self.reason,
            )
        except asyncpg.exceptions.UniqueViolationError:
            await interaction.response.send_message(f'{self.staff.mention} ban request for this user already exists')
        else:
            button.label = 'Ban Requested'
            button.disabled = True
            await interaction.response.edit_message(view=self)
        finally:
            self.stop()
    
    async def on_timeout(self) -> None:
        for b in self.children:
            b.disabled = True
        
        await self.message.edit(view=self)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.staff.id # type: ignore


class ModLogs(EmbedViewPagination):
    def __init__(self, data: List[asyncpg.Record], mwf: discord.TextChannel):
        super().__init__(data, timeout=60*5, per_page=5)
        self.mwf = mwf
    
    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        embed = discord.Embed(title='ModLogs').set_footer(text=f'Page {self.current_page}/{self.max_pages}')

        start = (self.current_page-1) * self.per_page
        for i, (case_id, message_id, type) in enumerate(data):

            try:
                message = await self.mwf.fetch_message(message_id)
                url = message.jump_url
            except (discord.NotFound, discord.HTTPException):
                url = None

            embed.add_field(name=f'{start+i+1}) ID: {case_id}', value=f'[{type}]({url})' if url else 'MWF message not found', inline=False)
        
        return embed
            

class BanRequests(EmbedViewPagination):
    children: List[discord.ui.Button]

    def __init__(self, user: Union[discord.Member, discord.User], guild: discord.Guild,bot: BunkerBot, logger: logging.Logger, data: List[asyncpg.Record]):
        super().__init__(data, timeout=60*15, per_page=5)
        self.user = user
        self.guild = guild
        self.logger = logger
        self.bot = bot

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        embed = discord.Embed(title='Ban Requests').set_thumbnail(url='https://media.tenor.com/images/6e8b88fc05f270d51d18d3a77b100e68/tenor.gif')

        for record in data:
            embed.add_field(name='Tag', value=record[0])
            embed.add_field(name='Reason', value=f'[{record[1]}]({record[2]})')
            embed.add_field(name='Requested By', value=record[3])

        return embed        
    
    @discord.ui.button(label='BAN ALL', style=discord.ButtonStyle.red)
    async def ban_all(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        async with self.bot.pool.acquire() as con:
            ban_requests = await con.fetch("select user_id, user_tag FROM moderation.banrequests")
            self.logger.info('Ban requests accepted by %s (%s)', str(self.user), self.user.id)

            for i, req in enumerate(ban_requests):
                try:
                    self.logger.info('Processing ban request %s: %s (%s)', i, req[1], req[0])
                    await self.guild.ban(discord.Object(req[0]), delete_message_days=0)

                except discord.HTTPException:
                    pass

            ids: List[int] = [req[0] for req in ban_requests]
            await con.execute('DELETE FROM moderation.banrequests WHERE user_id = ANY($1::numeric[])', ids)

            embed = discord.Embed(title=f'Banned {len(ids)} members', color=discord.Color.red())
            await interaction.response.edit_message(content=None, embed=embed, view=None)
            self.stop()


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user.id == interaction.user.id # type: ignore
    
    async def start(self, channel: discord.abc.Messageable) -> discord.Message:
        embed=await self._go_to(0)

        if self.max_pages == 1:
            self.next_page.disabled = True
            self.last_page.disabled = True

        return await channel.send(embed=embed, view=self)


class moderation(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.unmute_tasks: Dict[int, asyncio.Task] = {}

        self.logger = create_logger('moderation', level=logging.DEBUG)
        self.logger.addHandler(create_handler('moderation'))

        self.unmute_task.start()
    
    def cog_unload(self) -> None:
        for task in self.unmute_tasks.values():
            task.cancel()
        
        for handler in self.logger.handlers:
            handler.close()

    def resolve_user(self, message: discord.Message, user: Optional[Union[discord.Member, discord.User, Any]] = None) -> Optional[Union[discord.Member, discord.User]]:
        if isinstance(user, (discord.Member, discord.User)):
            return user
        
        reference = message.reference
        if reference and isinstance(reference.resolved, discord.Message):
            return  reference.resolved.author
        else:
            return None
    
    async def db_log(
        self,
        staff_id: int,
        log_message_id: int,
        type: str,
        user_id: int,
        *,
        completed: Optional[bool] = False,
        time_remove: Optional[datetime] = None,
    ) -> None:

        async with self.bot.pool.acquire() as con:
            await con.execute(
                'INSERT INTO moderation.moderation(staff_id, message_id, type, user_id, completed, time_remove) VALUES($1, $2, $3, $4, $5, $6)',
                staff_id,
                log_message_id,
                type,
                user_id,
                completed,
                time_remove,
                )

    async def db_ban_req(
        self,
        user_id: int,
        user_tag: str,
        staff_tag: str,
        message_link: str,
        log_message_id: int,
        *,
        attachment_link: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:

        async with self.bot.pool.acquire() as con:
            await con.execute(
                'INSERT INTO moderation.banrequests(user_id, user_tag, reason, message_link, staff_tag, attachment_link, log_message_id) VALUES($1, $2, $3, $4, $5, $6, $7)',
                user_id,
                user_tag,
                reason or 'Not Provided',
                message_link,
                staff_tag,
                attachment_link,
                log_message_id,
                )

    async def db_check_mute(
        self,
        user_id: int,
    ) -> None:

        async with self.bot.pool.acquire() as con:
            return await con.fetchval(
                'SELECT EXISTS (SELECT FROM moderation.moderation WHERE completed=$1 and (type=$2 or type=$3) and time_remove > $4 and user_id=$5)',
                False,
                'Mute',
                'Mute + Ban Request',
                discord.utils.utcnow(),
                user_id
                )

    async def db_check_br(
        self,
        user_id: int,
    ) -> None:

        async with self.bot.pool.acquire() as con:
            return await con.fetchval(
                'SELECT EXISTS (SELECT FROM moderation.banrequests WHERE user_id=$1)',
                user_id
                )

    async def log(
        self,
        action: Literal['Mute', 'Warn', 'Mute + Ban Request', 'Reaction Ban', 'Purge', 'Kick', 'Verbal Warn', 'Ban', 'Ban Request', 'Unmute'],
        staff: Union[discord.Member, discord.User],
        offender: Optional[Union[discord.Member, discord.User, int]],
        channel_used: Optional[discord.abc.MessageableChannel],
        *,
        amount: Optional[int] = None,
        length: Optional[int] = None,
        unmute_on: Optional[datetime] = None,
        reason: Optional[str] = None,
        quick_ban_request: bool = True,
        ) -> Optional[discord.Message]:
        
        mwf = self.bot.get_channel(mute_warn_proof)
        if mwf is None or not isinstance(mwf, discord.TextChannel):
            return None

        content = f'``` ```**Action**: {action.upper()}\n**Staff**: {staff.mention} ({staff.display_name})\n'

        if offender:
            if isinstance(offender, (discord.Member, discord.User)):
                content += f'**Offender:** {offender.mention} ({offender.display_name})\n**Offender ID**: {offender.id}\n'
            else:
                content+= f'**Offender:** Not Found\n**Offender ID**: {offender}\n' 
        
        if amount:
            content += f'**Amount:** {amount}\n'

        if length:
            content += f'**{action} Length:** {length}\n'

        if unmute_on:
            content += f'**Unmute Time:** {discord.utils.format_dt(unmute_on)} ({discord.utils.format_dt(unmute_on, "R")})\n'
        
        if channel_used:
            content += f'**Channel**: {channel_used.mention if isinstance(channel_used, (discord.TextChannel, discord.Thread)) else channel_used}\n'

        if not reason:
            reason = 'Not provided'
        content += f'**Reason**: {reason}'

        if quick_ban_request and offender:

            view = LogView(
                self,
                staff,
                offender,
                reason=reason
            )

            view.message = await mwf.send(content, view=view)
            return view.message
        else:
            return await mwf.send(content)


    async def _mute(self, user: Union[discord.Member, discord.User]) -> Tuple[bool, str]:
        ldoe = self.bot.get_guild(LDOE)

        if not ldoe:
            return False, 'Guild not found.'

        muted_role = ldoe.get_role(muted)
        if not muted_role:
            return False, 'Role not found'

        if isinstance(user, discord.Member):
            await user.add_roles(muted_role)
            self.logger.info('Muted role added to %s (%s)', user, user.id)

            return True, f'{user.name} muted'
        
        return False, f'{user.name} is not in server anymore'
    
    async def _unmute(
        self, 
        user_id: int, 
        time: int, 
        *, 
        reason: Optional[str] = None,
        update_db: bool = True,
        ) -> None:

        await asyncio.sleep(time)
        ldoe = self.bot.get_guild(LDOE)

        if not ldoe:
            self.logger.debug('Unmute failed for %s. Guild not found', user_id)
            return

        member = await self.bot.getch_member(ldoe, user_id)
        if not isinstance(member, discord.Member):
            self.logger.debug('Unmute failed for %s. Member not found', user_id)
            return

        if reason:
            self.logger.info('%s unmuted. Reason: %s', str(member), reason)

        if update_db:
            async with self.bot.pool.acquire() as con:
                await con.execute('UPDATE moderation.moderation set completed = $1 where user_id = $2 and completed = $3',
                                True, 
                                user_id, 
                                False
                                )
        
        await member.remove_roles(discord.Object(muted))

        if user_id in self.unmute_tasks:
            del self.unmute_tasks[user_id]
    
    async def _ban_request(
        self, 
        staff:  Union[discord.Member, discord.User], 
        user: Union[discord.Member, discord.User, int],
        message_link: str,
        log_message_id: int,
        *,
        attachment_link: Optional[str] = None,
        reason: Optional[str] = None,
        ) -> None:

        if isinstance(user, int):
            if offender := await self.bot.getch_user(user):
                await self.db_ban_req(offender.id, str(offender), str(staff), message_link, log_message_id, attachment_link=attachment_link, reason=reason)
                await self._mute(offender)
                await self.log('Ban Request', staff, offender, None, reason=reason, quick_ban_request=False)

            else:
                await self.db_ban_req(user, f'<@{user}>', str(staff), message_link, log_message_id, attachment_link=attachment_link, reason=reason)
                await self.log('Ban Request', staff, user, None, reason=reason, quick_ban_request=False)

        else:
            await self.db_ban_req(user.id, str(user), str(staff), message_link, log_message_id, attachment_link=attachment_link, reason=reason)
            await self._mute(user)
            await self.log('Ban Request', staff, user, None, reason=reason, quick_ban_request=False)
        
    async def _remove_ban_req(
        self,
        user_id: int,
        *,
        unmute: bool = True,
        unmute_reason: Optional[str] = None,
    ) -> None:

        async with self.bot.pool.acquire() as con:
            await con.execute('DELETE FROM moderation.banrequests WHERE user_id = $1', user_id)

        if unmute:
            await self._unmute(user_id, 0, reason=unmute_reason, update_db=False)

    @commands.command(aliases=['m'])
    @is_staff()
    async def mute(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User]], time: TimeConverter, *, reason: str = None):
        """
        A command to mute a member. Minimum time is 5 minutes and maximum time is 1 week.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is muted.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None:
            return await ctx.send('No person found to mute.', delete_after=10)

        if time is None:
            return await ctx.send('Invalid time.', delete_after=10)
        
        if 7*24*60*60 < time < UNMUTE_LOOP_TIME: # type: ignore (linter can not understand the TimeConverter)
            return await ctx.send(f'Invalid time, min is {UNMUTE_LOOP_TIME/60}min, max is 1 week.', delete_after=10)

        unmute = discord.utils.utcnow() + timedelta(seconds=time) # type: ignore 

        log_message = await self.log('Mute', ctx.author, offender, ctx.channel, length=time, unmute_on=unmute, reason=reason) # type: ignore
        if not log_message:
            return await ctx.channel.send('Log Channel not found')
        
        success, error_message = await self._mute(offender)

        await self.db_log(ctx.author.id, log_message.id, 'Mute', offender.id, time_remove=unmute)
        if not success:
            mwf = self.bot.get_channel(mute_warn_proof)
            if isinstance(mwf, discord.TextChannel):
                await mwf.send(f'Mute for {offender} failed. {error_message}')
        
        self.logger.info('%s muted %s (%s) for %s', str(ctx.author), str(offender), offender.id, reason)
                
    @commands.command()
    @is_staff()
    async def rban(self, ctx: BBContext, user: Optional[discord.Member], *, reason=None):
        """
        A command to give reaction ban role tp a member.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is reaction banned.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None or isinstance(offender, discord.User):
            return await ctx.send('No person found to react ban.', delete_after=10)

        ldoe = self.bot.get_guild(LDOE)
        if not ldoe:
            return await ctx.send('Error: Guild not found')

        rban_role = ldoe.get_role(react_banned)
        if not rban_role:
            return await ctx.send('Error: Role not found')

        await offender.add_roles(rban_role)
        await self.log('Reaction Ban', ctx.author, offender, ctx.channel, reason=reason, quick_ban_request=False)
        self.logger.info('%s reaction banned %s (%s) for %s', str(ctx.author), str(offender), offender.id, reason)
        

    @commands.command(name='ban-request', aliases=['br'])
    @is_staff()
    async def ban_req(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User, int]], *, reason=None):
        """
        A command to submit a ban request for a user. The user is permanently muted.

        Instead of providing the user in the command this can be used with a reply. If done so ban is requested
        for the author of the message replied to.
        """

        if isinstance(user, int):
            offender = user
        else:
            offender = self.resolve_user(ctx.message, user)
            if offender is None:
                return await ctx.send('No person found to request ban for.', delete_after=10)

        async with self.bot.pool.acquire() as con:
            if isinstance(offender, int):
                k = offender
            else:
                k = offender.id

            if await self.db_check_br(k):
                return await ctx.send(f'{ctx.author.mention} ban request for this user already exists')

        log_message = await self.log('Mute', ctx.author, offender, ctx.channel, reason=reason, quick_ban_request=False)
        if log_message:
            attachment = log_message.attachments[0].url if log_message.attachments else None
            await self._ban_request(ctx.author, offender, log_message.jump_url, log_message.id, attachment_link=attachment, reason=reason)
            self.logger.info('%s requested ban for %s for %s', str(ctx.author), str(offender), reason)
        else:
            await ctx.send('Ban request failed: Log channel not found')
        await ctx.message.delete()

    @commands.command(aliases=['prune'])
    @is_staff()
    async def purge(self, ctx: BBContext, amount: int):
        """
        A command to delete a large amount of messages with ease.
        """

        if isinstance(ctx.channel, (discord.DMChannel, discord.PartialMessageable, discord.GroupChannel)):
            return await ctx.send('This command is not available in this channel')

        await ctx.channel.purge(limit=amount + 1)
        await self.log('Purge', ctx.author, None, ctx.channel, amount=amount)
            

    @commands.command(aliases=['k'])
    @has_kick_permissions()
    async def kick(self, ctx: BBContext, user: Optional[discord.Member], *, reason=None):
        """
        A command to kick a member from the server.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is kicked.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None or isinstance(offender, discord.User):
            return await ctx.send('No person found to kick.', delete_after=10)

        await offender.kick(reason=reason)
        log_message = await self.log('Kick', ctx.author, offender, ctx.channel, reason=reason)
        if log_message:
            await self.db_log(ctx.author.id, log_message.id, 'Kick', offender.id, completed=True)
        await ctx.message.delete()

    @commands.command(aliases=['w'])
    @is_staff()
    async def warn(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User]], *, reason=None):
        """
        A command to warn a member.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is warned.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None:
            return await ctx.send('No person found to warn.', delete_after=10)

        log_message = await self.log('Warn', ctx.author, offender, ctx.channel, reason=reason)
        if log_message:
            await self.db_log(ctx.author.id, log_message.id, 'Warn', offender.id, completed=True)
        await ctx.message.delete()

    @commands.command(name='verbalwarn', aliases=['vw'])
    @is_staff()
    async def verbal_warn(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User]], *, reason=None):
        """
        A command to verbal warn a member. Verbal warnings are not displayed in mod logs and are only logged in
        mute warn proof.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is verbal warned.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None:
            return await ctx.send('No person found to verbal warn.', delete_after=10)

        await self.log('Verbal Warn', ctx.author, offender, ctx.channel, reason=reason, quick_ban_request=False)

    @commands.command()
    @commands.has_guild_permissions(administrator=True)
    async def ban(self, ctx: BBContext, user: Optional[discord.Object], *, reason=None):
        """
        A command to ban a member from the server.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is banned.
        """

        if user:
            ldoe = self.bot.get_guild(LDOE)
            if not ldoe:
                return await ctx.send('Ban failed. Guild not found')

            await ldoe.ban(user, delete_message_days=0)
            await self.log('Ban', ctx.author, user.id, ctx.channel, reason=reason, quick_ban_request=False)

        else:
            offender = self.resolve_user(ctx.message, user)
            if offender and isinstance(offender, discord.Member):
                await offender.ban(reason=reason, delete_message_days=0)
                await self.log('Ban', ctx.author, offender, ctx.channel, reason=reason, quick_ban_request=False)

            else:
                return await ctx.send('Ban failed. Could not resolve the member')
        
        await ctx.message.delete()

    @commands.command()
    @is_staff_or_guide()
    async def m5(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User]], *, reason=None):
        """
        A command to mute a member for 5 minutes.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is muted.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None:
            return await ctx.send('No person found to mute.', delete_after=10)

        unmute = discord.utils.utcnow() + timedelta(minutes=5)

        log_message = await self.log('Mute', ctx.author, offender, ctx.channel, length=300, unmute_on=unmute, reason=reason)
        if not log_message:
            return await ctx.channel.send('Log Channel not found')
        
        success, error_message = await self._mute(offender)

        if not success:
            mwf = self.bot.get_channel(mute_warn_proof)
            if isinstance(mwf, discord.TextChannel):
                await mwf.send(f'Mute for {offender} failed. {error_message}')
        
        self.logger.info('%s muted %s (%s) for %s', str(ctx.author), str(offender), offender.id, reason)
        await ctx.message.delete()
        await self._unmute(offender.id, 300, reason='Mute Expired', update_db=False)

    @commands.command(name='modlogs', aliases=['mod-logs', 'punishments'])
    @is_staff()
    async def mod_logs(self, ctx: BBContext, user: discord.User):
        """
        A command to display infractions for a member.
        """

        async with self.bot.pool.acquire() as con:
            data = await con.fetch('SELECT case_id, message_id, type FROM moderation.moderation WHERE user_id= $1', user.id)
            mwf = self.bot.get_channel(mute_warn_proof)
            view = ModLogs(data, mwf) # type: ignore
            await view.start(ctx.channel)

    @commands.command()
    @is_staff()
    async def unmute(self, ctx: BBContext, user: Optional[Union[discord.Member, discord.User]], *, reason=None):
        """
        A command to unmute a member.

        Instead of providing the user in the command this can be used with a reply. If done so the author of the 
        message replied to is unmuted.
        """

        offender = self.resolve_user(ctx.message, user)
        if offender is None:
            return await ctx.send('No person found to unmute.', delete_after=10)

        log_message = await self.log('Unmute', ctx.author, offender, ctx.channel, reason=reason, quick_ban_request=False)
        if not log_message:
            return await ctx.channel.send('Log Channel not found')
        
        self.logger.info('%s unmuted %s (%s) for %s', str(ctx.author), str(offender), offender.id, reason)
        await ctx.message.delete()
        await self._unmute(offender.id, 0, reason=reason or 'Not Provided')

    @commands.command()
    @commands.has_guild_permissions(administrator=True)
    async def removereq(self, ctx: BBContext, ids: commands.Greedy[int]):
        """
        A command to remove ban request from multiple users. This only works with user ids. Any invalid id 
        is ignored and all valid users are unmuted and ban request is removed.
        """

        async with self.bot.pool.acquire() as con:

            for id in ids:
                if await self.db_check_br(id):
                    await self._unmute(id, 0, reason='Ban Request cancelled' ,update_db=False)
            
            await con.execute('DELETE FROM moderation.banrequests WHERE user_id = ANY($1::numeric[])', ids)

        await ctx.send('Ban request has been removed for the given IDs')

    @commands.command(name="allreqs")
    @commands.has_guild_permissions(administrator=True)
    async def all_requests(self, ctx: BBContext):
        """
        A command to view all ban requests and quick ban these users.
        """

        async with self.bot.pool.acquire() as con:
            ban_requests = await con.fetch("select user_tag, reason, message_link, staff_tag FROM moderation.banrequests")
            if ban_requests:
                view = BanRequests(ctx.author, ctx.guild, self.bot, self.logger, ban_requests) # type: ignore
                await view.start(ctx.channel)
            else:
                await ctx.send('No ban requests found')

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """
        Listener to check if a member for whom ban was requested for is banned. If so the request is removed
        from the database.
        """

        if guild.id != LDOE:
            return
        
        if await self.db_check_br(user.id):
            await self._remove_ban_req(user.id, unmute=False)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Listener to check if a member who just joined has an active mute or ban request. If so the user is muted.
        """

        if member.guild.id != LDOE:
            return
        
        if await self.db_check_mute(member.id) or await self.db_check_br(member.id):
            await self._mute(member)

    @tasks.loop(seconds=UNMUTE_LOOP_TIME)
    async def unmute_task(self) -> None:
        """
        A task loop to periodically fetch and remove mutes.
        """

        async with self.bot.pool.acquire() as con:
            rows: Optional[List[asyncpg.Record]] = await con.fetch(
                'SELECT user_id, time_remove FROM moderation.moderation WHERE completed=$1 and type=$2 and (time_remove - $3) < $4',
                False,
                'Mute',
                discord.utils.utcnow(),
                timedelta(seconds=UNMUTE_LOOP_TIME)
                )

        if rows:
            for row in rows:
                delta: timedelta = row[1] - discord.utils.utcnow()
                task = self.bot.loop.create_task(self._unmute(row[0], delta.seconds, reason='Mute Expired'))
                self.unmute_tasks[row[0]] = task


def setup(bot: BunkerBot) -> None:
    bot.add_cog(moderation(bot))
