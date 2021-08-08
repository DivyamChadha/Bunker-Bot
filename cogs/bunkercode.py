import asyncpg
import discord
import re

from bot import BunkerBot
from context import BBContext
from datetime import datetime, timezone
from discord.ext import commands
from typing import Any, List, NamedTuple, Optional
from utils.constants import BUNKER_CODE_DENIED
from utils.views import EmbedViewPagination


code_regex = re.compile(r'(([bvgc][liouy]+[wnm]+\w+er|al(ph|f)a) (?=code))|(^(what|know|may|plase|does|anyone)\s.*code'
                        r'.*\??$)(?!^code)|((today).*code.*([bvgc][liouy]+[wnm]+\w+er|al(ph|f)a)?\??)|(code (?=([bvgc]'
                        r'[liouy]+[wnm]+\w+er|al(ph|f)a)))|(^![bvgc][liouy]+[wnm]+\w+er\s?[cv]o[df]e)', re.IGNORECASE)


CHANNEL_COOLDOWN = commands.CooldownMapping.from_cooldown(1.0, 300.0, commands.BucketType.user)
USER_COOLDOWN = commands.CooldownMapping.from_cooldown(1.0, 300.0, commands.BucketType.user)
TABLE_ARTS = 'extras.arts'


class Art(NamedTuple):
    """
    Representation of a row as stored in arts table
    """
    url: str
    artist_id: Optional[int] = None
    artist_name: Optional[str] = None


class BunkerCodeView(discord.ui.View):
    """
    The discord.ui.View that is sent with every bunker code auto response

    Parameters
    -----------
    code: str
        The current bunker code
    url: str
        Url to the asset to be displayed when user interacts
    artist_name: Optional[str]
        User name of artist
    """
    def __init__(self, code: str, url: str, artist: Optional[str] = None) -> None:
        super().__init__()
        self.code = code
        self.url = url
        self.artist = artist

    @discord.ui.button(emoji='\N{THUMBS UP SIGN}')
    async def send_ldoe_art(self, _, interaction: discord.Interaction):
        if interaction.message:
            embed = interaction.message.embeds[0]
            footer = self.artist or 'developers'

            embed.set_image(url=self.url)
            embed.set_footer(text=f'Art by {footer}')
            await interaction.response.edit_message(embed=embed, view=None)

        self.stop()

    @discord.ui.button(emoji='\N{WASTEBASKET}')
    async def shorten_code_message(self, _, interaction: discord.Interaction):
        await interaction.response.edit_message(view=None)
        self.stop()


class ArtsPagination(EmbedViewPagination):
    def __init__(self, data: List[Any], user: discord.Member):
        super().__init__(data, per_page=1)
        self.user = user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id # type: ignore

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        return discord.Embed(description=f'Art by {data[0][1]}' if data[0][1] else 'Art by Devs').set_image(url=data[0][0])


class bunkercode(commands.Cog):
    """
    Bunker Bot module to provide the bunker code functionality
    """
    _codes: List[str]
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        self.code_enabled: bool = True
        self.arts_cache: List[Art] = []

        self._set_codes()

    def _set_codes(self) -> None:
        """
        Reads the code from the txt file and sets them in self._codes
        """
        with open("codes", "r") as file:
            x = file.readline()
            self._codes = x.split()

    def _update_codes(self, codes: str) -> None:
        """
        Updates the txt file with the provided codes. Also sets them in self_codes afterwards

        Parameters
        -----------
        codes: str
            The entire months code as a string separated by spaces
        """
        with open("codes", 'w') as file:
            file.writelines(codes)
        self._codes = codes.split()

    @property
    def code(self) -> str:
        """
        Returns today's bunker code
        """
        day = discord.utils.utcnow().day
        return self._codes[int(day)]
    
    async def _get_art(self) -> Art:
        """
        Returns an Art to be used inside code message
        """
        if not self.arts_cache:
            async with self.bot.pool.acquire() as con:
                query = f'SELECT url, artist_id, artist_name FROM {TABLE_ARTS} ORDER BY random() LIMIT 20'
                rows: List[asyncpg.Record] = await con.fetch(query)
                self.arts_cache = [Art(url, artist_id, artist_name) for (url, artist_id, artist_name) in rows]
        
        return self.arts_cache.pop()

    @commands.Cog.listener(name='on_message')
    async def on_code_message(self, message: discord.Message) -> None:
        """
        A listener that is triggered for every message. Uses regex to check if the message's author is trying to
        trigger the bunker code auto response

        Parameters
        -----------
        message: discord.Message

        :return: None
        """
        if message.author.bot or message.channel.id in BUNKER_CODE_DENIED or not self.code_enabled:
            return

        # if message.channel.id != 411523566761148426:
        #     return  # TODO remove, only for testing

        if code_regex.search(message.content):
            self.bot.times_code_is_asked += 1

            # check cooldowns
            user_bucket = USER_COOLDOWN.get_bucket(message)
            channel_bucket = CHANNEL_COOLDOWN.get_bucket(message)
            retry_after1 = user_bucket.update_rate_limit()
            retry_after2 = channel_bucket.update_rate_limit()

            if retry_after1:
                await message.channel.send(content=f'Hey, {message.author.mention}! You just used that command, please wait {int(retry_after1)} seconds... The code is **{self.code}**', delete_after=10)
            elif retry_after2:
                await message.channel.send(content=f'Hey, {message.author.mention}! That command was just used in this channel, please wait {int(retry_after2)} seconds... The code is **{self.code}**.', delete_after=10)
            else:
                embed = discord.Embed(title=f'Bunker Code: {self.code}')
                art = await self._get_art()
                await message.reply(embed=embed, view=BunkerCodeView(self.code, art.url, art.artist_name))

    @commands.group()
    @commands.has_guild_permissions(administrator=True)
    async def settings(self, ctx: BBContext):
        """Base command for all settings related to bunker code module. This does nothing on its own"""
        pass

    @settings.command()
    async def update(self, ctx: BBContext, *, codes: str):
        """Update the codes for the entire month. Codes must be separated by space and be in order of day"""
        self._update_codes(codes)
        await ctx.tick(True)

    @settings.command(name='specific-update', aliases=['su'])
    async def specific_update(self, ctx: BBContext, day: int, code: str):
        """Update the code for a specific day"""
        self._codes[int(day) - 1] = code
        self._update_codes(' '.join(self._codes))
        await ctx.tick(True)

    @settings.command(name='early-update', aliases=['eu', 'earlyupdate'])
    async def early_update(self, ctx: BBContext, *, codes: str):
        """Schedule an update which occurs exactly at 12:00am gmt0. Codes must be separated by space and be in order
        of day"""
        await ctx.release_connection()

        current_date = discord.utils.utcnow()
        month = current_date.month
        year = current_date.year

        if month == 12:
            new_month = 1
            year += 1
        else:
            new_month = month + 1

        new_date = datetime(year, new_month, 1, 0, 0, 0, 0, timezone.utc)
        in_time = new_date - current_date

        await ctx.send(f"Codes will be updated in **{in_time}**")
        await discord.utils.sleep_until(new_date)

        self._update_codes(codes)
        await ctx.send("Codes have been updated")

    @settings.command()
    async def toggle(self, ctx: BBContext):
        """Toggles if the bunker code auto response has been enabled"""
        self.code_enabled = not self.code_enabled
        await ctx.send(f"Bunker code auto reaction has been set to: **{self.code_enabled}**")

    @settings.command(name='add-image', aliases=['ai'])
    async def add_img(self, ctx: BBContext, url: str, artist: Optional[discord.User] = None):
        """Adds an image to the bunker bot code images"""
        art = Art(url, artist.id, artist.name) if artist else Art(url)
        con = await ctx.get_connection()
        query = f'INSERT INTO {TABLE_ARTS}(url, artist_id, artist_name) VALUES($1, $2, $3)'

        await con.execute(query, art.url, art.artist_id, art.artist_name)
        await ctx.tick(True)

    @settings.command(name='remove-image', aliases=['ri'])
    async def remove_img(self, ctx: BBContext, url: str):
        """Removes an image from the bunker bot code images"""
        con = await ctx.get_connection()
        query = f'DELETE FROM {TABLE_ARTS} WHERE url = $1'

        await con.execute(query, url)
        await ctx.tick(True)

    @settings.command(name='batch-add', aliases=['ba']) # TODO
    async def batch_add(self, ctx: BBContext):
        ...

    @commands.command(disabled=True) # TODO
    async def artists(self, ctx: BBContext):
        ...

    @commands.command(disabled=True) # TODO
    async def arts(self, ctx: BBContext, artist: Optional[discord.Member] = None):
        if artist:
            query = f'SELECT url, artist_name FROM {TABLE_ARTS} WHERE artist_id = $1 LIMIT 20'
            args = [query, artist.id]
        else:
            query = f'SELECT url, artist_name FROM {TABLE_ARTS} ORDER BY random() LIMIT 20'
            args = [query]

        con = await ctx.get_connection()
        data: List[asyncpg.Record] = await con.fetch(*args)

        view = ArtsPagination(data, ctx.author)
        await view.start(ctx.channel)

def setup(bot: BunkerBot):
    bot.add_cog(bunkercode(bot))
