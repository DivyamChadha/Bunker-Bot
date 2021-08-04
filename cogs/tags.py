from __future__ import annotations
import asyncpg
import discord
import json

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import Dict, List, Optional, Tuple, Union


TABLE_CONTENT = 'tags.content'
TABLE_NAMES = 'tags.names'
TABLE_COMPONENTS = 'tags.components'


def dict_to_message(data) -> Optional[Tuple[str, discord.Embed]]:
    data = json.loads(data)
    content = data.get('content')
    embed = data.get('embed')

    if content is None and embed is None:
        return None

    if embed:
        embed = discord.Embed.from_dict(embed)
    else:
        embed = discord.utils.MISSING

    return (content, embed)


class TagButton(discord.ui.Button):
    view: TagContainer
    def __init__(self, tag_id: int, **kwargs):
        super().__init__(style=discord.ButtonStyle.gray, **kwargs)
        self.tag_id = tag_id

    @classmethod
    def from_dict(cls, data: dict) -> TagButton:
        return cls(
            data.get('tag_id'), # type: ignore
            label=data.get('label'),
            url=data.get('url'),
            emoji=data.get('emoji'),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        tag = self.view.tags.get(self.tag_id)
        if not tag:
            async with self.view.bot.pool.acquire() as con:
                query = f'SELECT content FROM {TABLE_CONTENT} WHERE id = $1'
                tag = await con.fetchval(query, self.tag_id)
                
            if not tag:
                self.view.tags[self.tag_id] = tag = {'content': f'Data for Tag ID: {self.tag_id} not found. Please contact a staff member'}
                return await interaction.response.send_message(tag['content'], ephemeral=True)
            else:
                data = dict_to_message(tag)
                if not data:
                    self.view.tags[self.tag_id] = tag = {'content': f'Data for Tag ID: {self.tag_id} is invalid. Please contact a staff member'}
                else:
                    self.view.tags[self.tag_id] = tag = {'content': data[0], 'embed': data[1]}
            
        await interaction.response.send_message(tag['content'], embed=tag['embed'], ephemeral=True) # type: ignore


class TagSelect(discord.ui.Select):
    view: TagContainer
    def __init__(self, options: List[Tuple[int, str]], **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = [discord.SelectOption(label=option[1], value=str(option[0])) for option in options]

    @classmethod
    def from_dict(cls, data: dict) -> TagSelect:
        return cls(
            data.get('options'), # type: ignore
            placeholder=data.get('placeholder')
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        tag_id = int(self.values[0])
        tag = self.view.tags.get(tag_id)
        if not tag:
            async with self.view.bot.pool.acquire() as con:
                query = f'SELECT content FROM {TABLE_CONTENT} WHERE id = $1'
                tag = await con.fetchval(query, tag_id)
                
            if not tag:
                self.view.tags[tag_id] = tag = {'content': f'Data for Tag ID: {tag_id} not found. Please contact a staff member'}
                return await interaction.response.send_message(tag['content'], ephemeral=True)
            else:
                data = dict_to_message(tag)
                if not data:
                    self.view.tags[tag_id] = tag = {'content': f'Data for Tag ID: {tag_id} is invalid. Please contact a staff member'}
                else:
                    self.view.tags[tag_id] = tag = {'content': data[0], 'embed': data[1]}
            
        await interaction.response.send_message(tag['content'], embed=tag['embed'], ephemeral=True) # type: ignore


def create_component(data: List) -> Union[TagButton, TagSelect]:
    if data[0] == 'button':
        return TagButton.from_dict(json.loads(data[1]))
    elif data[0] == 'select':
        return TagSelect.from_dict(json.loads(data[1]))
    else:
        raise ValueError(f'{data[0]} is an invalid component type for tags.')


class TagContainer(discord.ui.View):
    def __init__(self, components: List[Union[TagButton, TagSelect]], *, bot: BunkerBot):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.tags: Dict[int, dict] = {}

        for component in components:
            self.add_item(component)


class tags(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.command()
    async def tag(self, ctx: BBContext, *, name: str):
        query = f'SELECT cont.content, (comp.type, comp.data) AS component FROM {TABLE_CONTENT} cont \
                  INNER JOIN {TABLE_NAMES} n ON n.id = cont.id \
                  INNER JOIN {TABLE_COMPONENTS} comp ON comp.id = ANY(cont.component_ids) \
                  WHERE n.name = $1'
        con = await ctx.get_connection()
        rows: Optional[List[asyncpg.Record]] = await con.fetch(query, name)

        if not rows:
            return await ctx.send(f'No tag named **{name}** found.')

        data = dict_to_message(rows[0][0])
        if not data:
            return await ctx.send(f'Tag: **{name}** has invalid data')

        components = sorted([create_component(row['component']) for row in rows], key=lambda component: component.__class__.__name__)
        if components:
            view = TagContainer(components, bot=self.bot)
            return await ctx.send(data[0], embed=data[1], view=view)
        
        await ctx.send(data[0], embed=data[1])


def setup(bot: BunkerBot) -> None:
    bot.add_cog(tags(bot))
