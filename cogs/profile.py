import asyncpg
import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import Optional
from utils.checks import spam_channel_only
from utils.constants import COINS, DOGTAGS, TICKET
from utils.levels import LeaderboardPlayer


class ProfileView(discord.ui.View):
    def __init__(self, user: discord.Member, clan_data: asyncpg.Record, player: LeaderboardPlayer):
        super().__init__(timeout=60*5)
        self.user = user
        self.clan_data = clan_data
        self.player = player

    def format_user_info(self) -> discord.Embed:
        embed = discord.Embed(title=self.user)
        embed.add_field(name='Account Created', value=self.user.created_at.strftime('%m/%d/%Y, %H:%M:%S'))
        
        if self.user.joined_at:
            embed.add_field(name='Joined on', value=self.user.joined_at.strftime('%m/%d/%Y, %H:%M:%S'))
        
        embed.add_field(name='Roles', value=', '.join([role.mention for role in self.user.roles]), inline=False)

        if self.user.avatar:
            embed.set_thumbnail(url=self.user.avatar.url)
        
        return embed
    
    @discord.ui.button(emoji='\N{HAPPY PERSON RAISING ONE HAND}', style=discord.ButtonStyle.gray, disabled=True)
    async def user_info(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        self.user_info.disabled = True
        self.leaderboard.disabled = False
        self.clan.disabled = False

        await interaction.response.edit_message(embed=self.format_user_info(), view=self)


    @discord.ui.button(emoji=COINS, style=discord.ButtonStyle.gray)
    async def leaderboard(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        self.user_info.disabled = False
        self.leaderboard.disabled = True
        self.clan.disabled = False

        embed = discord.Embed(title=f'{self.user}\'s Event Profile')
        embed.add_field(name='Level', value=self.player.level)
        embed.add_field(name='XP', value=self.player.xp)
        embed.add_field(name='Coins', value=f'{self.player.coins} {COINS}')
        embed.add_field(name='Tickets', value=f'{self.player.tickets} {TICKET}')
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji=DOGTAGS, style=discord.ButtonStyle.gray)
    async def clan(self, button: discord.ui.Button, interaction: discord.Interaction) -> None:
        self.user_info.disabled = False
        self.leaderboard.disabled = False
        self.clan.disabled = True

        if self.clan_data:
            clan_tag = f' ({self.clan_data[5]})' if self.clan_data[5] else ''
            embed = discord.Embed(title=f'{self.user}\'s Clan Profile', description = self.clan_data[0] + clan_tag)
            
            embed.set_image(url=self.clan_data[2])

            if self.clan_data[1]:
                embed.description += f'\n{self.clan_data[1]}'

            embed.add_field(name='Clan Position', value=self.clan_data[3], inline=True)
            embed.add_field(name='Clan Language', value=self.clan_data[4] or 'Not Set', inline=True)
        
        else:
            embed = discord.Embed(title=f'{self.user}\'s Clan Profile', description='Not found')
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user.id == interaction.user.id # type: ignore


class profile(commands.Cog):

    def __init__(self, bot: BunkerBot):
        self.bot = bot

    @commands.command(name='profile')
    @commands.cooldown(1, 60.0, commands.BucketType.member)
    @spam_channel_only()
    async def _profile(self, ctx: BBContext):
        """
        A command to view your LDoE server profile. Your profile includes general, events and clan info.
        """
        
        con = await ctx.get_connection()

        # Clan Data
        query = '''SELECT clan_name, description, banner_url, clan_role, clan_language, clan_tag FROM clans.clan_members  
                   INNER JOIN clans.clan ON clan.clan_id = clan_members.clan_id WHERE member_id = $1'''
        clan_data: Optional[asyncpg.Record] = await con.fetchrow(query, ctx.author.id)

        # Events Data
        player = await LeaderboardPlayer.fetch(con, ctx.author)

        view = ProfileView(ctx.author, clan_data, player) # type: ignore (Dm messages intents is disabled, author will be a member)
        await ctx.send(embed=view.format_user_info(), view=view)


def setup(bot):
    bot.add_cog(profile(bot))
