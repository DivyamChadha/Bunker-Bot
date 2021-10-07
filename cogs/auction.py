from __future__ import annotations
import asyncpg
import discord

from bot import BunkerBot
from context import BBContext
from datetime import datetime, timedelta
from discord.ext import commands
from typing import List, Optional
from utils.constants import COINS
from utils.converters import TimeConverter
from utils.levels import LeaderboardPlayer
from utils.views import EmbedViewPagination


TABLE_AUCTION = 'events.auctions'
TABLE_AUCTION_LOG = 'events.auctions_log'


class AuctionItem:
    __slots__ = ('id', 'name', '_current_bet', 'minimum_increment', 'active_till', 'current_holder')

    def __init__(self, *, id: int, name: str, minimum_increment: int, active_till: datetime, current_bet: Optional[int], current_holder: Optional[int] = None) -> None:
        self.id = id
        self.name = name
        self._current_bet = current_bet
        self.minimum_increment = minimum_increment
        self.active_till = active_till
        self.current_holder = current_holder

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)

    @classmethod
    async def fetch(cls, item_name: str, con: asyncpg.Connection) -> Optional[AuctionItem]:
        query = f'SELECT id, name, current_bet, minimum_increment, active_till, current_holder FROM {TABLE_AUCTION} where name = $1'
        row = await con.fetchrow(query, item_name)
        if not row:
            return None

        return cls(**dict(row))

    @property
    def current_bet(self) -> int:
        return self._current_bet or 0

    @property
    def next_bet(self) -> int:
        return self.current_bet + self.minimum_increment

    @property
    def expires_in(self) -> str:
        return discord.utils.format_dt(self.active_till)


class AuctionPages(EmbedViewPagination):
    def __init__(self, user_id: int, data: List[asyncpg.Record], *, bot: BunkerBot, guild: discord.Guild):
        super().__init__(data, per_page=5)
        self.user_id = user_id
        self.bot = bot
        self.guild = guild

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id # type: ignore

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        embed = discord.Embed(title='Goodies for auction').set_footer(text=f'{self.current_page}/{self.max_pages}')
        for row in data:
            item = AuctionItem.from_dict(dict(row))

            if item.current_holder:
                user = await self.bot.getch_member(self.guild, item.current_holder)
                current_holder = user.name if isinstance(user, discord.Member) else user
            else:
                current_holder = 'No bet yet'                  

            embed.add_field(name=f'**{item.name}**', value=f'\nMinimum next bet: {item.next_bet} {COINS}\nEnds on {item.expires_in}\n({current_holder}: {item.current_bet} {COINS})')
        return embed


class AuctionAddFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    name: str = commands.flag(aliases=['n'])
    increment: int = commands.flag(aliases=['i'])
    time: TimeConverter = commands.flag(aliases=['t'])


class AuctionUpdateFlags(AuctionAddFlags):
    increment: Optional[int] = commands.flag(aliases=['i'])
    time: Optional[TimeConverter] = commands.flag(aliases=['t'])


class auction(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.enabled: bool = False

    @commands.command()
    @commands.cooldown(1, 60.0, commands.BucketType.member)
    async def goodies(self, ctx: BBContext):
        """
        A command used to view all available items in the ongoing auction.
        """

        if not self.enabled:
            return await ctx.send('There is no auction being conducted right now.')

        con = await ctx.get_connection()
        query = f'SELECT id, name, current_bet, minimum_increment, active_till, current_holder FROM {TABLE_AUCTION} WHERE active_till > $1'
        rows = await con.fetch(query, discord.utils.utcnow())

        if rows:    
            view = AuctionPages(ctx.author.id, rows, bot=self.bot, guild=ctx.guild) # type: ignore (Direct messages intent is not being used so guild will not be none)
            await view.start(ctx.channel)
        else:
            await ctx.send('No goodies available right now.')
    
    @commands.command()
    @commands.cooldown(1, 60.0, commands.BucketType.member)
    async def bet(self, ctx: BBContext, bet_amount: int, *, item_name: str):
        """
        A command to bet event coins on an auction item.
        """

        if not self.enabled:
            return await ctx.send('There is no auction being conducted right now.')
            
        con = await ctx.get_connection()
        item = await AuctionItem.fetch(item_name, con)

        if not item:
            return await ctx.send(f'No item with name: **{item_name}** exists.')

        if item.active_till < discord.utils.utcnow():
            return await ctx.send(f'**{item_name}** is no longer accepting bets.')

        if item.current_holder == ctx.author.id:
            return await ctx.send('You already are the highest bidder.')

        if bet_amount < item.next_bet:
            return await ctx.send(f'You can not bet **{bet_amount}**. You need to bet at least **{item.next_bet}**.')

        player = await LeaderboardPlayer.fetch(con, ctx.author)

        if player.coins < bet_amount:
            return await ctx.send(f'You only have **{player.coins}** {COINS} lol.')

        query = f'INSERT INTO {TABLE_AUCTION_LOG}(user_id, item_id, bet_amount, time, item_name, old_bet, old_user_id) VALUES($1, $2, $3, $4, $5, $6, $7)'
        await con.execute(query, ctx.author.id, item.id, bet_amount, discord.utils.utcnow(), item.name, item.current_bet, item.current_holder)
        await ctx.tick()

    @commands.group(name='auction')
    @commands.has_guild_permissions(administrator=True)
    async def _auction(self, ctx: BBContext):
        """
        The base command for auction management commands.
        """
        pass

    @_auction.command()
    async def add(self, ctx: BBContext, *, flags: AuctionAddFlags):
        """
        A command to add an item to the auction. 
        
        Available flags are:
        -name : The name of the item
        -increment: The minimum increment for each bet
        -time: The time in which this item will expire
        """

        con = await ctx.get_connection()
        query = f'INSERT INTO {TABLE_AUCTION}(name, minimum_increment, active_till) VALUES($1, $2, $3)'

        try:
            await con.execute(query, flags.name, flags.increment, discord.utils.utcnow()  + timedelta(seconds=flags.time)) # type: ignore
        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send(f'Auction item with name **{flags.name}** already exists')
        else:
            await ctx.tick()

    @_auction.command()
    async def remove(self, ctx: BBContext, *, item_name: str):
        """
        A command to remove an item from the auction.
        """

        con = await ctx.get_connection()
        query = f'DELETE FROM {TABLE_AUCTION} WHERE name = $1 RETURNING *'
        row = await con.fetchrow(query, item_name)

        if not row:
            return await ctx.send(f'Auction item with name **{item_name}** does not exist.')

        item = AuctionItem.from_dict(dict(row))

        if item.current_holder:
            user = await self.bot.getch_member(ctx.guild, item.current_holder) # type: ignore (Direct messages intent is not being used so guild will not be none)
            current_holder = user.name if isinstance(user, discord.Member) else user
        else:
            current_holder = 'No bet yet'   

        description = f'\nMinimum next bet: {item.next_bet} {COINS}\nEnds on {item.expires_in}\n({current_holder}: {item.current_bet} {COINS})'
        embed = discord.Embed(title=f'Deleted: {row["name"]}', description=description)
        await ctx.send(embed=embed)

    @_auction.command()
    async def update(self, ctx: BBContext, *, flags: AuctionUpdateFlags):
        """
        A command to update an item in the auction. 
        
        Available flags are:
        -increment: The minimum increment for each bet
        -time: The time in which this item will expire
        """

        if not (flags.increment or flags.time):
            return await ctx.send(f'You must either provide `-increment` or `-time`.')

        columns = []
        args = []

        if flags.increment:
            columns.append('minimum_increment')
            args.append(flags.increment)

        if flags.time:
            columns.append('active_till')
            args.append(discord.utils.utcnow()  + timedelta(seconds=flags.time)) # type: ignore (linter doesnt understand TimeConverter)

        con = await ctx.get_connection()
        cols = ', '.join(f'{col}=${i+2}' for i, col in enumerate(columns))
        query = f'UPDATE {TABLE_AUCTION} SET {cols} WHERE name = $1'
        args.insert(0, flags.name)
        args.insert(0, query)
        
        val = await con.execute(*args)
        if val == 'UPDATE 0':
             await ctx.send(f'No auction item found with name: **{flags.name}**')
        else:
            await ctx.tick()

    @_auction.command()
    async def toggle(self, ctx: BBContext):
        """
        A command to enabled or disable auctions.
        """

        self.enabled = not self.enabled
        e = 'enabled.' if self.enabled else 'disabled.'
        await ctx.send(f'Auctions are now {e}')



def setup(bot: BunkerBot) -> None:
    bot.add_cog(auction(bot))