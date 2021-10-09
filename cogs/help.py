import discord

from bot import BunkerBot
from context import BBContext
from discord.ext import commands
from typing import List, Mapping, Optional, Union
from utils.views import EmbedViewPagination


class HelpView(EmbedViewPagination):
    _data: List[List[discord.Embed]]

    def __init__(self, user: Union[discord.Member, discord.User], data: List[discord.Embed]):
        super().__init__(data, timeout=60*5, per_page=1)
        self.user = user

        options: List[discord.SelectOption] = []
        for i, embed in enumerate(self._data):
            options.append(discord.SelectOption(label=embed[0].title, value=str(i)))
        self.select_cog.options = options

    @discord.ui.select(placeholder='Choose a module')
    async def select_cog(self, select: discord.ui.Select, interaction: discord.Interaction) -> None:
        val = int(select.values[0])
        await interaction.response.edit_message(embed=await self._go_to(val))

    async def format_page(self, data: List[discord.Embed]) -> discord.Embed:
        return data[0]
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.user.id == interaction.user.id # type: ignore


class BBHelp(commands.HelpCommand):
    context: BBContext

    def __init__(self):
        super().__init__(
            command_attrs = {
                'hidden': True,
                'aliases': ['h'],
                }
        )

    def _format_command(self, command: commands.Command) -> discord.Embed:
        embed = discord.Embed(title=self.get_command_signature(command), description=command.help)
        if command.aliases:
            embed.add_field(name="Aliases:", value="| ".join(command.aliases), inline=False)

        return embed

    async def _format_group(self, group: commands.Group) -> discord.Embed:
        embed = discord.Embed(title=self.get_command_signature(group), description=group.help)
        if group.aliases:
            embed.add_field(name="Aliases:", value="| ".join(group.aliases), inline=False)

        filtered_commands = await self.filter_commands(group.walk_commands(), sort=True)
        if filtered_commands:

            subcmds = []
            for cmd in filtered_commands:

                subcmds.append('`f{cmd.name}`\n{cmd.short_doc}')
            
            embed.add_field(name='Sub-Commands', value='\n'.join(subcmds), inline=False)

        return embed

    async def send_bot_help(self, mapping: Mapping[Optional[commands.Cog], List[commands.Command]]):

        items: List[discord.Embed] = []

        embed = discord.Embed(
            title='Bunker Bot', 
            description='A bot made by [Indian Rock](<discord://-/users/378957690073907201>) for Offical Last Day on Earth \
                         discord server. The bot is [open source](https://github.com/rockboy987/Bunker-Bot) if you \
                         wish to contribute.'
            )

        embed.add_field(
            name='How do I get bunker code?',
            value='To get bunker code simply type "Bunker Code" anywhere in the server.', 
            inline=False
            )
        
        embed.add_field(
            name='Can I invite bunker bot to my own server?',
            value='No. It is hosted locally by [Sgt Shankers](<discord://-/users/416035290201849858>) for LDoE Server only.',
            inline=False
        )

        items.append(embed)

        for cog, commands in mapping.items():
           filtered_commands = await self.filter_commands(commands, sort=True)

           if filtered_commands:
                embed = discord.Embed(title=cog.qualified_name if cog else 'default', description='')
                for cmd in filtered_commands:
                    embed.description += f'`{cmd.name}`\n{cmd.short_doc}\n\n'
                   
                items.append(embed)

        view = HelpView(self.context.author, items)
        await view.start(self.get_destination())

    async def send_cog_help(self, cog: commands.Cog):
        items: List[discord.Embed] = []
        base = discord.Embed(title=f'{cog.qualified_name}', description = f'{cog.description}\n\n')
        items.append(base)

        filtered_commands = await self.filter_commands(cog.walk_commands(), sort=True)
        if filtered_commands:
            for cmd in filtered_commands:

                if cmd.parent is None:
                    base.description += f'`{self.get_command_signature(cmd)}`\n{cmd.short_doc}\n\n'

                if isinstance(cmd, commands.Command):
                    items.append(self._format_command(cmd))
                else:
                    items.append(await self._format_group(cmd))

        view = HelpView(self.context.author, items)
        await view.start(self.get_destination())    

    async def send_group_help(self, group: commands.Group):
        items: List[discord.Embed] = []
        base = discord.Embed(title=self.get_command_signature(group), description=f'{group.help}\n\n')
        items.append(base)

        filtered_commands = await self.filter_commands(group.walk_commands(), sort=True)
        if filtered_commands:
            for cmd in filtered_commands:
                if cmd.parent is None:
                    base.description += f'{cmd.name}: `{cmd.short_doc}`\n\n'

                if isinstance(cmd, commands.Command):
                    items.append(self._format_command(cmd))
                else:
                    items.append(await self._format_group(cmd))

        view = HelpView(self.context.author, items)
        await view.start(self.get_destination())    
       
    async def send_command_help(self, command: commands.Command):
        dest = self.get_destination()
        await dest.send(embed=self._format_command(command))

class Help(commands.Cog):
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot

        help_command = BBHelp()
        help_command.cog = self
        bot.help_command = help_command

    def cog_unload(self) -> None:
        self.bot.help_command = commands.DefaultHelpCommand()
        
def setup(bot: BunkerBot) -> None:
    bot.add_cog(Help(bot))
