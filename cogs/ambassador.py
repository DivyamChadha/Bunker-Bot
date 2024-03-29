from __future__ import annotations
import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from random import choice
from typing import Callable, List, Optional
from utils.checks import is_staff_or_support
from utils.constants import staff_lounge, ambassadors_lounge, training_room
from utils.views import EmbedViewPagination


EMOJI_LOUDSPEAKER = ':loudspeaker: '
FLARE_INFO_CHANNELS = [ambassadors_lounge, training_room]


class Flare:
    __slots__ = ('user', 'channel', 'reason', 'link', 'urgent', 'message')

    message: discord.Message
    def __init__(self, user: discord.Member, channel: discord.abc.MessageableChannel, reason: str, link: str, *, urgent: bool = False) -> None:
        self.user = user
        self.channel = channel
        self.reason = reason
        self.link = link
        self.urgent = urgent

    @property
    def staff(self) -> discord.Embed:
        resolve_mention = self.channel.mention if isinstance(self.channel, (discord.TextChannel, discord.Thread)) else self.channel
        if self.urgent:
            description = f'Hi Staff! {EMOJI_LOUDSPEAKER*3}\n{self.user.mention} needs URGENT help in {resolve_mention} with: __**{self.reason}**__'
        else:
            description = f'Hi Staff! {EMOJI_LOUDSPEAKER}\n{self.user.mention} needs help in {resolve_mention} with: __**{self.reason}**__'

        embed = discord.Embed(description=description)
        embed.add_field(name='Quick Portal', value=f'[Click Here]({self.link})')
        return embed

    @property
    def ambass(self) -> discord.Embed:
        resolve_mention = self.channel.mention if isinstance(self.channel, (discord.TextChannel, discord.Thread)) else self.channel
        if self.urgent:
            description = f'Hi everyone! {EMOJI_LOUDSPEAKER*3}\n{self.user.mention} has requested URGENT staff help in {resolve_mention} with: __**{self.reason}**__'
        else:
            description = f'Hi everyone! {EMOJI_LOUDSPEAKER}\n{self.user.mention} has requested staff help in {resolve_mention} with: __**{self.reason}**__'

        embed = discord.Embed(description=description)
        embed.add_field(name='Quick Portal', value=f'[Click Here]({self.link})')
        return embed

    async def respond(self, staff: discord.Member) -> None:
        await self.message.reply(f'{staff.name} are on their way!')


class FlareView(discord.ui.View):
    def __init__(self, flares: List[Flare]) -> None:
        super().__init__(timeout=60*120)
        self.flares = flares
    
    @discord.ui.button(label='Respond', style=discord.ButtonStyle.red)
    async def respond(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        button.label = f'Responded by {interaction.user.name}' # type: ignore
        button.disabled = True
        await interaction.response.edit_message(view=self)

        for flare in self.flares:
            await flare.respond(interaction.user) # type: ignore

        self.stop()


class InRolePagination(EmbedViewPagination):
    def __init__(self, person: discord.Member, data: List[discord.Member]):
        super().__init__(data, timeout=180.0, per_page=20)
        self.person = person

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.person.id # type: ignore

    async def format_page(self, data: List[discord.Member]) -> discord.Embed:
        start = (self.current_page-1) * self.per_page
        embed = discord.Embed(description='\n'.join(f'{start+i+1}) {member.name}' for i, member in enumerate(data)))
        return embed


class ambassador(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.command(name='staff', aliases=['flare'])
    @is_staff_or_support()
    async def flare(self, ctx: BBContext, *, reason: str = 'Reason not provided') -> None:
        """
        A simple and quick way to get a staff member’s attention when it’s needed. Rather than trying to find one who is actually available, 
        this posts a sos message in staff chat allowing a staff member who is free to claim the issue and help you out.
        """
        
        staff = self.bot.get_channel(staff_lounge)
        flares: List[Flare] = []

        emoji = choice(ctx.guild.emojis) # type: ignore (Direct messages intent is not being used so guild will not be none)
        emoji_message = await ctx.send(str(emoji))

        for channel_id in FLARE_INFO_CHANNELS:
            channel = self.bot.get_channel(channel_id)
            flare = Flare(ctx.author, ctx.channel, reason, emoji_message.jump_url) # type: ignore (Direct messages intent is not being used so author will be a member)
            flare.message = await channel.send(embed=flare.ambass) # type: ignore
            flares.append(flare)

        await staff.send(embed=flare.staff, view=FlareView(flares)) # type: ignore

    @commands.command(name='redalert', aliases=['red-alert'])
    @is_staff_or_support()
    async def red_alert(self, ctx: BBContext, *, reason: str = 'Reason not provided') -> None:
        """
        An elevated flare command that pings all online staff member (@here). For emergencies only.
        """

        staff = self.bot.get_channel(staff_lounge)
        flares: List[Flare] = []

        emoji = choice(ctx.guild.emojis) # type: ignore (Direct messages intent is not being used so guild will not be none)
        emoji_message = await ctx.send(str(emoji))

        for channel_id in FLARE_INFO_CHANNELS:
            channel = self.bot.get_channel(channel_id)
            flare = Flare(ctx.author, ctx.channel, reason, emoji_message.jump_url, urgent=True) # type: ignore (Direct messages intent is not being used so author will be a member)
            flare.message = await channel.send(embed=flare.ambass) # type: ignore
            flares.append(flare)

        await staff.send('@here', embed=flare.staff, view=FlareView(flares)) # type: ignore

    @commands.command(aliases=['whois'])
    @is_staff_or_support()
    async def userinfo(self, ctx: BBContext, *, person: Optional[discord.Member] = None) -> None:
        """
        A command to get useful information about an user or yourself.
        """
        
        if not person:
            person = ctx.author # type: ignore (Direct messages intent is not being used so author will not be a member)

        if not person:
            return

        roles = [role.mention for role in person.roles]
        permissions = [perm[0] if perm[1] else '' for perm in person.guild_permissions]
        join_position = sorted(ctx.guild.members, key=lambda m: m.joined_at).index(person) + 1 # type: ignore (Direct messages intent is not being used so guild will not be none)
        created_on = person.created_at.strftime('%m/%d/%Y, %H:%M:%S')
        joined_on = person.joined_at.strftime('%m/%d/%Y, %H:%M:%S') # type: ignore

        embed = discord.Embed(title=f'{person.name}#{person.discriminator}', description=f'Nickname: {person.nick}\nUser ID: {person.id}')
        embed.add_field(name='Account', value=f'Created on: {created_on}\nJoined on: {joined_on}\nJoin positon: {join_position}')
        embed.add_field(name='Roles', value=', '.join(roles), inline=False)
        embed.add_field(name='Permissions', value=', '.join(permissions), inline=False)
        embed.set_thumbnail(url=person.display_avatar.url) # type: ignore

        await ctx.send(embed=embed)

    @commands.command(aliases=['members'])
    @is_staff_or_support()
    async def inrole(self, ctx: BBContext, *, role: discord.Role) -> None:
        """
        A command to find all the members having a certain role.
        """

        predicate: Callable[[discord.Member], bool] = lambda member: role in member.roles
        members: List[Optional[discord.Member]] = [member for member in ctx.guild.members if predicate(member)] # type: ignore (Direct messages intent is not being used so guild will not be none)

        if members:
            view = InRolePagination(ctx.author, members) # type: ignore
            await view.start(ctx.channel)
        else:
            await ctx.send('No members found.')


def setup(bot: BunkerBot) -> None:
    bot.add_cog(ambassador(bot))
