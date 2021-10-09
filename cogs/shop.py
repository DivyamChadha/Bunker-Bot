from __future__ import annotations
import asyncpg
import discord

from bot import BunkerBot
from context import BBContext
from datetime import timedelta
from discord.ext import commands
from typing import Dict, List, Optional, Union
from utils.checks import spam_channel_only, is_event_coord, is_beta_tester
from utils.constants import COINS, TICKET
from utils.converters import TimeConverter
from utils.levels import LeaderboardPlayer
from utils.views import Confirm, EmbedViewPagination


TABLE_CURRENCY = 'events.currency'
TABLE_SHOP = 'events.shop'
TABLE_SHOP_LOG = 'events.shop_log'
CURRENCY_EMOJI = {
    'tickets': TICKET,
    'event coins': COINS
}


class ShopItem:
    __slots__ = ('id', 'name', 'price', 'currency', 'stock', 'minimum_level', 'description', 'cooldown', 'emoji', 'amount',)

    def __init__(self, *, id: int, name: str, price: int, currency: str, stock: Optional[int], minimum_level: int, description: Optional[str], cooldown: Optional[int], emoji: Optional[str], amount: int) -> None:
        self.id = id
        self.name = name
        self.price = price
        self.currency = currency
        self.stock = stock
        self.minimum_level = minimum_level
        self.description = description
        self.cooldown = cooldown
        self.emoji = emoji
        self.amount = amount


class ShopSelect(discord.ui.Select):
    view: Shop
    def __init__(self, *, options: List[discord.SelectOption]) -> None:
        super().__init__(
            placeholder='Select an Item to buy', 
            options=options
            )
    
    async def callback(self, interaction: discord.Interaction):
        item_id = int(self.values[0])
        item: ShopItem = self.view.shop_items[item_id]

        if item.minimum_level > self.view.player.level:
            return await interaction.response.send_message(f'You must be at least level **{item.minimum_level}** to buy this item, however you are only level **{self.view.player.level}**.')

        if item.stock:
            if item.stock <= 0:
                return await interaction.response.send_message('This item is out of stock. You can not buy it right now', ephemeral=True)


        if item.currency == 'tickets':
            if item.price > self.view.player.tickets:
                return await interaction.response.send_message(f'You do not have enough tickets to buy **{item.name}**', ephemeral=True)
        elif item.currency == 'event coins':
            if item.price > self.view.player.coins:
                return await interaction.response.send_message(f'You do not have enough event coins to buy **{item.name}**', ephemeral=True)
        else:
            raise ValueError(f'Invalid currency: {item.currency} for item: {item.name} with ID: {item.id}')


        async with self.view.bot.pool.acquire() as con:
            con: asyncpg.Connection

            async with con.transaction():

                if item.cooldown:
                    last_bought_item = discord.utils.utcnow() + timedelta(seconds=item.cooldown)
                    query = f'SELECT EXISTS (SELECT FROM {TABLE_SHOP_LOG} WHERE user_id = $1 and item_id = $2 and time < $3)'
                    if await con.fetchval(query, self.view.player.user.id, item.id, last_bought_item):
                        return await interaction.response.send_message(f'You can not buy this item again so soon.')

                query = f'INSERT INTO {TABLE_SHOP_LOG}(user_id, item_id, price, time, item_name, item_amount, currency_used) VALUES($1, $2, $3, $4, $5, $6, $7)'
                await con.execute(query, self.view.player.user.id, item.id, item.price, discord.utils.utcnow(), item.name, item.amount, item.currency) 
                # tickets and coins are subtracted automatically and stock is updated via triggers
                # Event Coins are also transffered via the same if bought

                await interaction.response.send_message(f'You just bought **{item.amount} {item.name}**! If this is an in-game item a staff member will contact you soon!')


class Shop(EmbedViewPagination):
    def __init__(self, player: LeaderboardPlayer, bot: BunkerBot, items: List[ShopItem]) -> None:
        super().__init__(items, per_page=5)
        self.bot = bot
        self.player = player
        
        options = [discord.SelectOption(label=f'{item.amount} {item.name}', value=str(item.id), emoji=item.emoji, description=f'Cost: {item.price} {item.currency}') for item in items]
        self.add_item(ShopSelect(options=options[:24])) # currently only supporting one select i.e. 25 items in shop
        self.shop_items: Dict[int, ShopItem] = dict([(item.id, item) for item in items])
            
    @classmethod
    async def fetch_with_items(cls, user: Union[discord.Member, discord.User], bot: BunkerBot) -> Shop:
        async with bot.pool.acquire() as con:
            player = await LeaderboardPlayer.fetch(con, user)
            query = f'SELECT id, name, description, emoji, price, currency, stock, minimum_level, cooldown, amount FROM {TABLE_SHOP} ORDER BY price'

            rows = await con.fetch(query)
            items = [ShopItem(**dict(row)) for row in rows]

        return cls(player, bot, items)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.user.id: # type: ignore
            await interaction.response.send_message('You can not interact with this shop. Get your own shop using `b!shop` command.', ephemeral=True)
            return False
        else:
            return True

    async def format_page(self, data: List[ShopItem]) -> discord.Embed:
        embed = discord.Embed(title='Shop').set_footer(text=f'{self.current_page}/{self.max_pages}')
        for item in data:
            embed.add_field(name=f'{item.amount} {item.name} ({item.price} {CURRENCY_EMOJI[item.currency]})', value=f'**Description:** {item.description}\n**Level required**: {item.minimum_level}\n**Stock:** {item.stock or "∞"}')
        return embed

    async def start(self, channel: discord.abc.Messageable) -> discord.Message:
        if self.max_pages == 1:
            self.first_page.disabled = True
            self.previous_page.disabled = True
            self.next_page.disabled = True
            self.last_page.disabled = True

        self.message = await channel.send(embed=await self.format_page(self._data[0]), view=self)
        return self.message


class ShopListPages(EmbedViewPagination):
    def __init__(self, user_id: int, data: List[asyncpg.Record]):
        super().__init__(data, per_page=10)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id # type: ignore

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        description = '\n'.join(f'ID: {item[0]}\nName: {item[1]}\n Amount: {item[2]}\n' for item in data)
        embed = discord.Embed(title='Shop Items', description=description)
        embed.set_footer(text=f'{self.current_page}/{self.max_pages}')
        return embed


class ShopItemCreateFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    name: str = commands.flag(aliases=['n'])
    description: Optional[str] = commands.flag(aliases=['d'])
    emoji: Optional[discord.Emoji] = commands.flag(aliases=['e'])
    price: int = commands.flag(aliases=['p'])
    stock: Optional[int] = commands.flag(aliases=['s'])
    minimum_level: int = commands.flag(aliases=['ml'])
    cooldown: Optional[TimeConverter] = commands.flag(aliases=['c'])
    amount: int = commands.flag(aliases=['a'])


class ShopItemUpdateFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    id: int
    name: Optional[str] = commands.flag(aliases=['n'])
    description: Optional[str] = commands.flag(aliases=['d'])
    emoji: Optional[discord.Emoji] = commands.flag(aliases=['e'])
    price: Optional[int] = commands.flag(aliases=['p'])
    stock: Optional[int] = commands.flag(aliases=['s'])
    minimum_level: Optional[int] = commands.flag(aliases=['ml'])
    cooldown: Optional[TimeConverter] = commands.flag(aliases=['c'])
    amount: Optional[int] = commands.flag(aliases=['a'])


class shop(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.group(invoke_without_command=True)
    @spam_channel_only()
    @is_beta_tester()
    async def shop(self, ctx: BBContext):
        """
        A command to display the LDoE Shop.
        """
        
        shop = await Shop.fetch_with_items(ctx.author, self.bot)
        await shop.start(ctx.channel)

    @shop.command()
    @commands.has_guild_permissions(administrator=True)
    async def list(self, ctx: BBContext):
        """
        A command to display list of all items in shop and their ids.
        """
        
        con = await ctx.get_connection()
        query = f'SELECT id, name, amount FROM {TABLE_SHOP}'
        rows = await con.fetch(query)
        view = ShopListPages(ctx.author.id, rows)
        await view.start(ctx.channel)

    @shop.group()
    @commands.has_guild_permissions(administrator=True)
    async def add(self, ctx: BBContext, *, flags: ShopItemCreateFlags):
        """
        A command to add an item to the shop.

        The available flags are:
            -[name|n]
            -[description|d] (optional)
            -[emoji|e] (optional)
            -[price|p]
            -[stock|s] (optonal)
            -[minimum_level|ml]
            -[cooldown|c] (optional)
            -[amount|a]
        """
        
        con = await ctx.get_connection()
        query = f'INSERT INTO {TABLE_SHOP}(name, description, emoji, price, currency, stock, minimum_level, cooldown, amount) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9)'
        await con.execute(query, flags.name, flags.description, flags.emoji, flags.price, 'event coins', flags.stock, flags.minimum_level, flags.cooldown, flags.amount)
        await ctx.tick()

    @shop.group()
    @commands.has_guild_permissions(administrator=True)
    async def delete(self, ctx: BBContext, item_id: int):
        """
        A command to delete an item from the shop.
        """
        
        confirm = Confirm(ctx.author.id)
        await ctx.send(f'Are you sure you want to delete shop item with ID: {item_id}', view=confirm)

        await confirm.wait()
        if confirm.result:
            con = await ctx.get_connection()
            query = f'DELETE FROM {TABLE_SHOP} WHERE id = $1'
            await con.execute(query, item_id)

    @shop.group()
    @commands.has_guild_permissions(administrator=True)
    async def update(self, ctx: BBContext, *, flags: ShopItemUpdateFlags):
        """
        A command to update a shop item.

        The available flags are:
            -[id]
            -[name|n] (optional)
            -[description|d] (optional)
            -[emoji|e] (optional)
            -[price|p] (optional)
            -[stock|s] (optonal)
            -[minimum_level|ml] (optional)
            -[cooldown|c] (optional)
            -[amount|a] (optional)
        """
        
        columns = []
        args = []
        
        if flags.name:
            columns.append('name')
            args.append(flags.name)

        if flags.description:
            columns.append('description')
            args.append(flags.description)

        if flags.emoji:
            columns.append('emoji')
            args.append(flags.emoji)

        if flags.price:
            columns.append('price')
            args.append(flags.price)

        if flags.stock == -1:
            columns.append('stock')
            args.append(None)
        elif flags.stock:
            columns.append('stock')
            args.append(flags.stock)

        if flags.minimum_level:
            columns.append('minimum_level')
            args.append(flags.minimum_level)

        if flags.cooldown:
            columns.append('cooldown')
            args.append(flags.cooldown)

        if flags.amount:
            columns.append('amount')
            args.append(flags.amount)

        if not args:
            return await ctx.send('You must provide at least one field to update')

        con = await ctx.get_connection()
        cols = ', '.join(f'{col}=${i+2}' for i, col in enumerate(columns))
        query = f'UPDATE {TABLE_SHOP} SET {cols} WHERE id = $1'
        args.insert(0, flags.id)
        args.insert(0, query)
        
        val = await con.execute(*args)
        if val == 'UPDATE 0':
             await ctx.send(f'No shop item found with ID: **{flags.id}**')
        else:
            await ctx.tick()


def setup(bot: BunkerBot) -> None:
    bot.add_cog(shop(bot))