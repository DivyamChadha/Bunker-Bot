import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import List, Optional
from utils.constants import events_lounge, events_answers, events_participants, server_logs
from utils.levels import LeaderboardPlayer


WORD_SEARCH_REACTIONS = {
    '1\N{variation selector-16}\N{combining enclosing keycap}': 'Hey {}, you have **one** word wrong.',
    '2\N{variation selector-16}\N{combining enclosing keycap}': 'Hey {}, you have **two** words wrong.',
    '\N{BLACK UP-POINTING DOUBLE TRIANGLE}': 'Hey {}, you have **three or more** words wrong.',
    '\N{FIRST PLACE MEDAL}': 'Hey {}, you have got the **21** words!',
    '\N{SECOND PLACE MEDAL}': 'Hey {}, you have got the **15** words!',
    '\N{THIRD PLACE MEDAL}': 'Hey {}, you have got the **10** words!',
}


class events(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.listen_ws: bool = True # word search # TODO FALSE
        self.listen_hman: bool = False # hangman
        self.hangman_players: List[discord.Member] = []

    @commands.command()
    async def ea(self, ctx: BBContext, *, words: Optional[str] ='None'):
        eventslounge = ctx.guild.get_channel(events_lounge) # type: ignore (Direct messages intent is not being used so guild will not be none)

        if ctx.channel == eventslounge:
            channel: discord.TextChannel = ctx.guild.get_channel(events_answers) # type: ignore (Direct messages intent is not being used so guild will not be none)
            await channel.send(f'``` ```\n**Event Submission**\nUser: {ctx.author.mention} ({ctx.author.display_name})'
                               f' \nUser ID: {ctx.author.id} \nSubmisson:\n{words}', allowed_mentions=discord.AllowedMentions.none())
            await ctx.message.delete() # type: ignore
        else:
            await ctx.send(f'This command is only usable in {eventslounge.mention}', allowed_mentions=discord.AllowedMentions.none()) # type: ignore (We can guarantee here that events lounge will not be none)

    @commands.command()
    async def eventspart(self, ctx: BBContext, members: commands.Greedy[discord.Member]):
        log_channel = ctx.guild.get_channel(server_logs) # type: ignore (Direct messages intent is not being used so guild will not be none)

        text = ''
        for member in members:
            await member.add_roles(discord.Object(events_participants))
            text += f'\n{member.mention} ({member.id})'

        embed = discord.Embed(title = 'Events Participants role added to:', description=text)

        if ctx.author.avatar:
            embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url)
        else:
            embed.set_author(name=ctx.author.name)

        await log_channel.send(embed=embed) # type: ignore (We can guarantee here that channel exists and is TextChannel)
        await ctx.tick()

    @commands.command()
    async def eventsunpart(self, ctx: BBContext, members: commands.Greedy[discord.Member]):
        log_channel = ctx.guild.get_channel(server_logs) # type: ignore (Direct messages intent is not being used so guild will not be none)

        text = ''
        for member in members:
            await member.remove_roles(discord.Object(events_participants))
            text += f'\n{member.mention} ({member.id})'

        embed = discord.Embed(title = 'Events Participants role removed from::', description=text)

        if ctx.author.avatar:
            embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url)
        else:
            embed.set_author(name=ctx.author.name)

        await log_channel.send(embed=embed) # type: ignore (We can guarantee here that channel exists and is TextChannel)
        await ctx.tick()

    @commands.Cog.listener(name='on_reaction_add')
    async def listener_wordsearch(self, reaction: discord.Reaction, user: discord.User):
        if not self.listen_ws:
            return
        if not reaction.message.channel.id == events_answers:
            return
        if not str(reaction.emoji) in WORD_SEARCH_REACTIONS:
            return

        content = reaction.message.content.split()

        # content[5] is the user mention for the user who used the ea command. The mentions property of Reaction.message is not used because we do not want this to fail if the user mentions someone inside ea command.
        if not content[5].startswith(('<@!', '<@')):
            return

        eventslounge = self.bot.get_channel(events_lounge)
        await eventslounge.send(WORD_SEARCH_REACTIONS[str(reaction.emoji)].format(content[5])) # type: ignore

    @commands.Cog.listener(name='on_reaction_add')
    async def listener_hangman(self, reaction: discord.Reaction, user: discord.User):
        if not self.listen_hman:
            return
        if not reaction.message.channel.id == events_answers:
            return
        if not str(reaction.emoji) == f'<:check:461172408909430814>':
            return

        content = reaction.message.content.split()

        # content[5] is the user mention for the user who used the ea command. The mentions property of Reaction.message is not used because we do not want this to fail if the user mentions someone inside ea command.
        if content[5].startswith(('<@!')):
            user_id = int(content[5][3:-1])
        elif content[5].startswith('<@'):
            user_id = int(content[5][2:-1])
        else:
            return

        guild = reaction.message.guild
        member = await self.bot.getch_member(guild, user_id) # type: ignore

        if isinstance(member, int):
            return
        if member in self.hangman_players:
            return
        
        eventslounge = self.bot.get_channel(events_lounge)
        self.hangman_players.append(member)
        eventsparts = guild.get_role(events_participants) # type: ignore

        await member.add_roles(eventsparts) # type: ignore
        await eventslounge.send(f'You are in {member.mention}.') # type: ignore

        if len(self.hangman_players) >= 16:
            masabot_commands = '\n'.join(f'm)any {self.hangman_players[i].mention} {self.hangman_players[i+1].mention} {eventslounge.mention} <word here>' for i in range(0, len(self.hangman_players), 2)) # type: ignore
            await reaction.message.channel.send(f'{user.mention}, we have reached 16 members\n\n```{masabot_commands}```')
            self.hangman_players = []

    @commands.group(case_insensitive=True)
    async def listen(self, ctx: BBContext):
        pass

    @listen.command(name='hangman')
    async def listen_hangman(self, ctx: BBContext):
        self.listen_hman = True
        await ctx.send(f'Listening to <:check:461172408909430814>')
    
    @listen.command(name='wordsearch')
    async def listen_wordsearch(self, ctx: BBContext):
        self.listen_ws = True
        reacts = ', '.join(WORD_SEARCH_REACTIONS.keys())
        await ctx.send(f'Listening to {reacts}')

    @commands.group(case_insensitive=True)
    async def unlisten(self, ctx: BBContext):
        pass

    @unlisten.command(name='hangman')
    async def unlisten_hangman(self, ctx: BBContext):
        self.listen_hman = False
        self.hangman_players = []
        await ctx.send(f'Not listening to <:check:461172408909430814>')
    
    @unlisten.command(name='wordsearch')
    async def unlisten_wordsearch(self, ctx: BBContext):
        self.listen_ws = False
        reacts = ', '.join(WORD_SEARCH_REACTIONS.keys())
        await ctx.send(f'Not listening to {reacts}')

    @commands.group()
    async def events(self, ctx: BBContext):
        pass

    @events.group()
    async def coins(self, ctx: BBContext):
        pass

    @coins.command()
    async def add(self, ctx: BBContext, coins: int, member: discord.Member):
        con = await ctx.get_connection()
        player = await LeaderboardPlayer.fetch(con, member)

        if player.level < 1:
            return await ctx.send('Coins can not be added to anyone below level 1')

        await player.update(con, coins=coins)
        await ctx.tick()

def setup(bot: BunkerBot) -> None:
    bot.add_cog(events(bot))