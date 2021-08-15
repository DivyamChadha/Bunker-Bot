from __future__ import annotations
import asyncpg
import difflib
import discord
import json

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import Dict, List, Optional, Union
from utils.views import Confirm, EmbedViewPagination


TABLE_CONTENT = 'tags.content'
TABLE_NAMES = 'tags.names'
TABLE_COMPONENTS = 'tags.components'


def dict_to_embed(data: Optional[str]) -> Optional[discord.Embed]:
    """
    Takes embed as stored in database (jsonb) and returns it as a discord.Embed object

    Parameters
    -----------
    data: Optional[str]
        embed stored as jsonb in postgreSQL db
    """
    if data is None:
        return None

    data = json.loads(data)
    embed = discord.Embed.from_dict(data) # type: ignore
    if not (embed.title or embed.description or embed.footer or embed.image): # Embeds need atleast one of the specified fields
        embed.description = 'The embed needs atleast one field: `title`, `description`, `footer` or `image`'

    return embed


class TagButton(discord.ui.Button):
    """
    A Button that is attached to a tag

    Parameters
    -----------
    tag_id: int
        The id for tag which the button press will send
    """
    view: TagContainer
    def __init__(self, tag_id: int, **kwargs):
        super().__init__(**kwargs)
        self.tag_id = tag_id

    @classmethod
    def from_dict(cls, data: dict) -> TagButton:
        style = discord.ButtonStyle.gray if not data.get('url') else discord.ButtonStyle.link
        return cls(
            data.get('tag_id'), # type: ignore
            label=data.get('label'),
            url=data.get('url'),
            emoji=data.get('emoji'),
            style=style
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        tag = self.view.tags.get(self.tag_id)
        embed = None
        if not tag:
            async with self.view.bot.pool.acquire() as con:
                query = f'SELECT content, embed FROM {TABLE_CONTENT} WHERE id = $1'
                tag = await con.fetchrow(query, self.tag_id)
                
            if not tag:
                self.view.tags[self.tag_id] = tag = {'content': f'Data for Tag ID: {self.tag_id} not found. Please contact a staff member', 'embed': None}
                return await interaction.response.send_message(tag['content'], ephemeral=True)
            else:
                embed = dict_to_embed(tag['embed'])
                if not (embed or tag['content']):
                    self.view.tags[self.tag_id] = tag = {'content': f'Data for Tag ID: {self.tag_id} is invalid. Please contact a staff member', 'embed': None}
                else:
                    self.view.tags[self.tag_id] = tag = {'content': tag['content'], 'embed': embed}
            
        if embed:
            await interaction.response.send_message(tag['content'], embed=tag['embed'], ephemeral=True)
        else:
            await interaction.response.send_message(tag['content'], ephemeral=True)


class TagSelect(discord.ui.Select):
    """
    A Select Menu attached to a tag. The tag select menu does not allow any customisation

    Parameters
    -----------
    options: List[discord.SelectOption]
        Select Options that the select menu will contain. The value of each option is the tag id for the tag which would be sent on selecting that option 
    """
    view: TagContainer
    def __init__(self, *, options: List[discord.SelectOption]) -> None:
        super().__init__(options=options)

    @classmethod
    def from_dict(cls, data: dict) -> TagSelect:
        return cls(
            data.get('options'), # type: ignore
            placeholder=data.get('placeholder')
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        tag_id = int(self.values[0])
        embed = None
        tag = self.view.tags.get(tag_id)
        if not tag:
            async with self.view.bot.pool.acquire() as con:
                query = f'SELECT content, embed FROM {TABLE_CONTENT} WHERE id = $1'
                tag = await con.fetchrow(query, tag_id)
                
            if not tag:
                self.view.tags[tag_id] = tag = {'content': f'Data for Tag ID: {tag_id} not found. Please contact a staff member', 'embed': None}
                return await interaction.response.send_message(tag['content'], ephemeral=True)
            else:
                embed = dict_to_embed(tag['embed'])
                if not (embed or tag['content']):
                    self.view.tags[tag_id] = tag = {'content': f'Data for Tag ID: {tag_id} is invalid. Please contact a staff member', 'embed': None}
                else:
                    self.view.tags[tag_id] = tag = {'content': tag['content'], 'embed': embed}
        
        if embed:
            await interaction.response.send_message(tag['content'], embed=tag['embed'], ephemeral=True)
        else:
            await interaction.response.send_message(tag['content'], ephemeral=True)


def create_components(data: List[str]) -> List[Union[TagButton, TagSelect]]:
    """
    Helper function to convert a list of components stored as jsonb in database into usable component objects

    Parameters
    -----------
    data: List[str]
        list of jsonb objects
    """
    components: List[Union[TagButton, TagSelect]] = []
    select_options = []

    for component in data:
        component = json.loads(component)
        if component['type'] == 'button':
            components.append(TagButton.from_dict(component))

        elif component['type'] == 'selectoption':
            select_options.append(discord.SelectOption(
                label=component.get('label'),
                value=str(component.get('tag_id')),
                description=component.get('description'),
                emoji=component.get('emoji')
                ))
    
    if select_options:
        components.append(TagSelect(options=select_options[:24])) # only supporting one select per tag right now
    
    return components


class TagContainer(discord.ui.View):
    """
    The view which is sent along with the tag if the tag has any components attached to it

    Parameters
    -----------
    components: List[Union[TagButton, TagSelect]]
        List of components attached to this view
    bot: BunkerBot
        Instance of bot object
    """
    def __init__(self, components: List[Union[TagButton, TagSelect]], *, bot: BunkerBot):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.tags: Dict[int, dict] = {}

        for component in components:
            self.add_item(component)


class TagEmbedFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    """
    Flag converter used in update embed command
    """
    tagid: int
    title: str = commands.flag(aliases=['t'], default=None)
    description: str = commands.flag(aliases=['d'], default=None)
    color: discord.Color = commands.flag(aliases=['c'], default=None)
    footer: str = commands.flag(aliases=['f'], default=None)
    image: str = commands.flag(aliases=['i'], default=None)


class TagButtonFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    """
    Flag converter used in create button command
    """
    tagid: int = commands.flag(aliases=['tid'])
    label: str = commands.flag(aliases=['l'], default=None)
    emoji: str = commands.flag(aliases=['e'], default=None)
    url: str = commands.flag(aliases=['u'], default=None)


class TagButtonFlagsUpdate(TagButtonFlags):
    """
    Flag converter used in update button command
    """
    tagid: int = commands.flag(aliases=['tid'], default=None)
    componentid: int = commands.flag(aliases=['cid'])


class TagSelectOptionFlags(commands.FlagConverter, delimiter=' ', prefix='-'):
    """
    Flag converter used in create selectoption command
    """
    tagid: int = commands.flag(aliases=['tid'])
    label: str = commands.flag(aliases=['l'])
    emoji: str = commands.flag(aliases=['e'], default=None)
    description: str = commands.flag(aliases=['d'], default=None)


class TagSelectOptionFlagsUpdate(TagSelectOptionFlags):
    """
    Flag converter used in update select option command
    """
    tagid: int = commands.flag(aliases=['tid'], default=None)
    componentid: int = commands.flag(aliases=['cid'])
    label: str = commands.flag(aliases=['l'], default=None)


class TagsListPages(EmbedViewPagination):
    """
    Button paginator used to display all tags in the database
    """
    def __init__(self, data: List[asyncpg.Record], user_id: int):
        super().__init__(data, per_page=10)
        self.user_id = user_id

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        embed = discord.Embed(title='Tags', description='\n'.join(f'{i+1}) **{record["name"]}** (ID: {record["id"]})' for i, record in enumerate(data)))
        embed.set_footer(text=f'{self.current_page}/{self.max_pages}')
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user_id == interaction.user.id # type: ignore


class ComponentListPages(EmbedViewPagination):
    """
    Button paginator used to display all components in the database
    """
    def __init__(self, data: List[asyncpg.Record], user_id: int):
        super().__init__(data, per_page=10)
        self.user_id = user_id

    async def format_page(self, data: List[asyncpg.Record]) -> discord.Embed:
        embed = discord.Embed(title='Components', description='\n'.join(f'{i+1}) {record["type"]} (ID: **{record["id"]}**) (References tag: **{record["tag_id"]}**)' for i, record in enumerate(data)))
        embed.set_footer(text=f'{self.current_page}/{self.max_pages}')
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user_id == interaction.user.id # type: ignore


class tags(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

    @commands.group(invoke_without_command=True, aliases=['tags', 't'])
    async def tag(self, ctx: BBContext, *, name: str):
        if name not in self.bot.tags:
            matches = difflib.get_close_matches(name, self.bot.tags, n=5)

            if matches:
                t = '\n'.join(matches)
                embed = discord.Embed(title=f'Could not find the tag {name}', description=f'Did you mean:\n{t}')
                await ctx.send(embed=embed)
            else:
                await ctx.send(f'Could not find the tag {name}')

        query = f'SELECT tags.get_tag($1)'
        con = await ctx.get_connection()

        row = await con.fetchrow(query, name)
        if not row:
            return await ctx.send(f'No tag named **{name}** found.')

        row = row[0]
        embed = dict_to_embed(row['embed'])
        if not (embed or row['content']):
            return await ctx.send(f'Tag: **{name}** has invalid data.')

        components = create_components(row['components'])
        if components:
            view = TagContainer(components, bot=self.bot)
            if embed:
                return await ctx.send(row['content'], embed=embed, view=view)
            else:
                return await ctx.send(row['content'], view=view)

        if embed:
            await ctx.send(row['content'], embed=embed)
        else:
            await ctx.send(row['content'])

    @tag.group(invoke_without_command=True)
    async def create(self, ctx: BBContext, name: str, *, content: str):
        con = await ctx.get_connection()
        query = f'WITH content AS (INSERT INTO {TABLE_CONTENT}(content) VALUES($2) RETURNING id ) \
                  INSERT INTO {TABLE_NAMES}(name, id) SELECT $1, id FROM content RETURNING id'

        try:
            tag_id = await con.fetchval(query, name, content)
            await ctx.send(f'Tag with Name: **{name}** and ID: **{tag_id}** has been created.')
            self.bot.tags.add(name)
        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send(f'Tag with name: **{name}** already exists')

    @create.command(name='button')
    async def create_button(self, ctx: BBContext, *, flags: TagButtonFlags):
        if not (bool(flags.label) or bool(flags.emoji)):
            return await ctx.send('You must provided atleast one of the following: `-label`, `-emoji`')

        query = f'SELECT EXISTS (SELECT FROM {TABLE_CONTENT} WHERE id = $1)'
        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval(query, flags.tagid):
                return await ctx.send(f'Tag with ID: **{flags.tagid}** does not exist')

            button = {}
            query = f'INSERT INTO {TABLE_COMPONENTS}(type, data, tag_id) VALUES($1, $2::jsonb, $3) RETURNING id'
    
            if flags.label:
                button['label'] = flags.label

            if flags.emoji:
                button['emoji'] = flags.emoji

            if flags.url:
                button['url'] = flags.url

            component_id = await con.fetchval(query, 'button', json.dumps(button), flags.tagid)
            await ctx.send(f'Button with ID: {component_id} has been created. You can now use this ID in `b!tag add-component` command to add to it a tag.')

    @create.command(name='selectoption', aliases=['select-option'])
    async def create_select(self, ctx: BBContext, *, flags: TagSelectOptionFlags):
        query = f'SELECT EXISTS (SELECT FROM {TABLE_CONTENT} WHERE id = $1)'
        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval(query, flags.tagid):
                return await ctx.send(f'Tag with ID: **{flags.tagid}** does not exist')

            selectoption = {'label': flags.label}
            query = f'INSERT INTO {TABLE_COMPONENTS}(type, data, tag_id) VALUES($1, $2::jsonb, $3) RETURNING id'
    
            if flags.emoji:
                selectoption['emoji'] = flags.emoji

            if flags.description:
                selectoption['description'] = flags.description

            component_id = await con.fetchval(query, 'selectoption', json.dumps(selectoption), flags.tagid)
            await ctx.send(f'Select Option with ID: {component_id} has been created. You can now use this ID in `b!tag add-component` command to add to it a tag.')

    @tag.group()
    async def update(self, ctx: BBContext) -> None:
        pass

    @update.command(name='embed')
    async def update_embed(self, ctx: BBContext, *, flags: TagEmbedFlags):      
        if not (bool(flags.title) or bool(flags.footer) or bool(flags.description) or bool(flags.image) or bool(flags.color)):
            return await ctx.send('You must fill atleast one field: `-title`, `-description`, `-footer`, `-image`, `-color`')

        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval('SELECT EXISTS (SELECT FROM tags.content WHERE id = $1)', flags.tagid):
                return await ctx.send(f'Tag with ID: **{flags.tagid}** does not exist.')
    
            if flags.title:
                await con.execute("UPDATE tags.content SET embed = jsonb_set(COALESCE(embed, '{}'::jsonb), '{title}', $1::jsonb) WHERE id = $2", json.dumps(flags.title), flags.tagid)

            if flags.description:
                await con.execute("UPDATE tags.content SET embed = jsonb_set(COALESCE(embed, '{}'::jsonb), '{description}', $1::jsonb) WHERE id = $2", json.dumps(flags.description), flags.tagid)

            if flags.color:
                await con.execute("UPDATE tags.content SET embed = jsonb_set(COALESCE(embed, '{}'::jsonb), '{color}', $1::jsonb) WHERE id = $2", json.dumps(str(flags.color)), flags.tagid)

            if flags.footer:
                await con.execute("UPDATE tags.content SET embed = jsonb_set(COALESCE(embed, '{}'::jsonb), '{footer}', $1::jsonb) WHERE id = $2", json.dumps({'text': flags.footer}), flags.tagid)

            if flags.image:
                await con.execute("UPDATE tags.content SET embed = jsonb_set(COALESCE(embed, '{}'::jsonb), '{image}', $1::jsonb) WHERE id = $2", json.dumps({'url': flags.image}), flags.tagid)

        return await ctx.tick()

    @update.command(name='button')
    async def update_button(self, ctx: BBContext, *, flags: TagButtonFlagsUpdate):
        query = f'SELECT EXISTS (SELECT FROM {TABLE_COMPONENTS} WHERE id = $1)'
        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval(query, flags.componentid):
                return await ctx.send(f'Button with ID: **{flags.tagid}** does not exist')
    
            if flags.tagid:
                if not await con.fetchval(f'SELECT EXISTS (SELECT FROM {TABLE_CONTENT} WHERE id = $1)', flags.tagid):
                    return await ctx.send(f'Tag with ID: **{flags.tagid}** does not exist.')

                await con.execute(f'UPDATE {TABLE_COMPONENTS} SET tag_id = $1 WHERE id = $2', flags.tagid, flags.componentid)

            if flags.label:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{label}', $1::jsonb) WHERE id = $2", json.dumps(flags.label), flags.componentid)
  
            if flags.emoji:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{emoji}', $1::jsonb) WHERE id = $2", json.dumps(flags.emoji), flags.componentid)

            if flags.url:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{url}', $1::jsonb) WHERE id = $2", json.dumps(flags.url), flags.componentid)

            await ctx.tick()

    @update.command(name='selectoption', aliases=['select-option'])
    async def update_selectoption(self, ctx: BBContext, *, flags: TagSelectOptionFlagsUpdate):
        query = f'SELECT EXISTS (SELECT FROM {TABLE_COMPONENTS} WHERE id = $1)'
        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval(query, flags.componentid):
                return await ctx.send(f'Select Option with ID: **{flags.tagid}** does not exist')

            if flags.tagid:
                if not await con.fetchval(f'SELECT EXISTS (SELECT FROM {TABLE_CONTENT} WHERE id = $1)', flags.tagid):
                    return await ctx.send(f'Tag with ID: **{flags.tagid}** does not exist.')

                await con.execute(f'UPDATE {TABLE_COMPONENTS} SET tag_id = $1 WHERE id = $2', flags.tagid, flags.componentid)

            if flags.label:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{label}', $1::jsonb) WHERE id = $2", json.dumps(flags.label), flags.componentid)
  
            if flags.emoji:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{emoji}', $1::jsonb) WHERE id = $2", json.dumps(flags.emoji), flags.componentid)

            if flags.description:
                await con.execute("UPDATE tags.components SET data = jsonb_set(COALESCE(data, '{}'::jsonb), '{description}', $1::jsonb) WHERE id = $2", json.dumps(flags.description), flags.componentid)

            await ctx.tick()

    @tag.command(name='add-component', aliases=['addcomponent', 'ac'])
    async def add_component(self, ctx: BBContext, tag_id: int, component_id: int):
        con = await ctx.get_connection()

        async with con.transaction():
            if not await con.fetchval(f'SELECT EXISTS (SELECT FROM {TABLE_COMPONENTS} WHERE id = $1)', component_id):
                return await ctx.send(f'Component with ID: **{component_id}** does not exist.')

            val = await con.execute("UPDATE tags.content SET component_ids = tags.remove_duplicates(array_append(COALESCE(component_ids, '{}'::int[]), $1)) WHERE id = $2", component_id, tag_id)
            if val == 'UPDATE 1':
                return await ctx.tick()

            await ctx.send(f'Tag with ID: **{tag_id}** does not exist')
    
    @tag.command(name='remove-component', aliases=['removecomponent', 'rc'])
    async def remove_component(self, ctx: BBContext, tag_id: int, component_id: int):
        con = await ctx.get_connection()
        query = "UPDATE tags.content SET component_ids = array_remove(COALESCE(component_ids, '{}'::int[]), $1) WHERE id = $2"

        val  = await con.execute(query, component_id, tag_id)
        if val == 'UPDATE 1':
            return await ctx.tick()

        await ctx.send(f'Tag with ID: **{tag_id}** does not exist')

    @tag.group(invoke_without_command=True)
    async def delete(self, ctx: BBContext, tag_id: int): # must remove any component pointing to it as well
        confirm = Confirm(ctx.author.id)
        await ctx.send(f'Are you sure you want to delete Tag with ID: **{tag_id}**.', view=confirm)
        await confirm.wait()
        if not confirm.result:
            return

        con = await ctx.get_connection()
        query = f'WITH row AS (DELETE FROM {TABLE_NAMES} WHERE id = $1 RETURNING name), \
                  _ AS (DELETE FROM {TABLE_CONTENT} WHERE id = $1) \
                  SELECT array_agg(name) FROM row'
        
        try:
            val = await con.fetchval(query, tag_id)
        except asyncpg.exceptions.ForeignKeyViolationError:
            await ctx.send(f'There are components still refering to this tag. Please first delete any component with tag_id: **{tag_id}**')
        else:

            if val:
                names = ', '.join(val)
                self.bot.tags -= set(val)
                await ctx.send(f'Tag with Tag ID **({tag_id})** has been deleted. The following can not be used anymore: **{names}**')
            else:
                await ctx.send(f'Tag with ID: **{tag_id}** does not exist.')

    @delete.command(name='embed')
    async def delete_embed(self, ctx: BBContext, tag_id: int):
        confirm = Confirm(ctx.author.id)
        await ctx.send(f'Are you sure you want to delete embed in Tag with ID: **{tag_id}**.\nNote: The tag will not be deleted and the embed can be added again using `b!tag update embed` command.', view=confirm)
        await confirm.wait()
        if not confirm.result:
            return

        con = await ctx.get_connection()
        query = f'UPDATE {TABLE_CONTENT} SET embed = NULL WHERE id = $1'
        val = await con.execute(query, tag_id)

        if val == 'UPDATE 1':
            await ctx.tick()
        else:
            await ctx.send(f'Tag with ID: **{tag_id}** does not exist.')

    @delete.command(name='component')
    async def delete_component(self, ctx: BBContext, component_id: int): # must remove from each array where present
        confirm = Confirm(ctx.author.id)
        await ctx.send(f'Are you sure you want to delete the component with ID: **{component_id}**.', view=confirm)
        await confirm.wait()
        if not confirm.result:
            return

        con = await ctx.get_connection()
        query = f'DELETE FROM {TABLE_COMPONENTS} WHERE id = $1'
        val = await con.execute(query, component_id)
        
        if val == 'UPDATE 1':
            await ctx.tick()
        else:
            await ctx.send(f'Component with ID: **{component_id}** does not exist.')

    @tag.command(name='list', aliases=['show'])
    async def show(self, ctx: BBContext):
        con = await ctx.get_connection()
        query = f'SELECT name, id FROM {TABLE_NAMES} ORDER BY name'
        rows = await con.fetch(query)
        view = TagsListPages(rows, ctx.author.id)
        await view.start(ctx.channel)

    @tag.command()
    async def search(self, ctx: BBContext, *, name: str):
        matches = difflib.get_close_matches(name, self.bot.tags, n=5)

        if matches:
            t = '\n'.join(matches)
            embed = discord.Embed(title=f'Tag search: {name}', description=f'Found:\n{t}')
            await ctx.send(embed=embed)
        else:
            await ctx.send(f'Could not find the tag **{name}**')

    @create.command(name='alias')
    async def create_alias(self, ctx: BBContext, tag_id: int, *, alias_name: str):
        con = await ctx.get_connection()
        query = f'INSERT INTO {TABLE_NAMES}(name, id) VALUES($1, $2)'

        try:
            await con.execute(query, tag_id, alias_name)
        except asyncpg.exceptions.ForeignKeyViolationError:
            await ctx.send(f'Tag with ID: **{tag_id}** does not exist.')
        except asyncpg.exceptions.UniqueViolationError:
            await ctx.send(f'Can not create alias with name **{alias_name}**. Tag with such name already exists.')
        else:
            await ctx.tick()

    @delete.command(name='alias')
    async def delete_alias(self, ctx: BBContext, tag_id: int, *, alias_name: str):
        con = await ctx.get_connection()
        async with con.transaction():
            query = 'SELECT COUNT(id) WHERE id = $1'
            l = await con.fetchval(query, tag_id)

            if not l:
                return await ctx.send(f'Tag with ID: **{tag_id}** does not exist.')

            if l < 2:
                return await ctx.send(f'Can not delete the only available name for tag with ID: **{tag_id}**. Create more aliases to do so.')

            query = f'DELETE FROM {TABLE_NAMES} WHERE id = $1 and name = $2'
            val = await con.execute(query, tag_id, alias_name)

            if val == 'DELETE 0':
                await ctx.send(f'Tag with ID: **{tag_id}** does not have an alias called **{alias_name}**')
            else:
                await ctx.tick()

    @tag.command(aliases=['component'])
    @commands.has_guild_permissions(administrator=True)
    async def components(self, ctx: BBContext):
        con = await ctx.get_connection()
        query = f'SELECT id, type, tag_id FROM {TABLE_COMPONENTS} ORDER BY id'
        rows = await con.fetch(query)
        view = ComponentListPages(rows, ctx.author.id)
        await view.start(ctx.channel)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(tags(bot))
