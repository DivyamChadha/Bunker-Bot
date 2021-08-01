from __future__ import annotations
import discord

from typing import Any, List, Optional


class EmbedViewPagination(discord.ui.View):

    message: discord.Message
    def __init__(self, data: List[Any], *, timeout: Optional[float] = 180.0, per_page: int = 1):
        super().__init__(timeout=timeout)

        self._data = [data[i*per_page:(i+1)*per_page] for i in range((len(data)+per_page-1)//per_page)]
        self._current_page = 0
    
    @property
    def max_pages(self) -> int:
        return len(self._data)
    
    @property
    def current_page(self) -> int:
        return self._current_page + 1

    async def _go_to(self, page: int) -> discord.Embed:
        self._current_page = page

        if page == 0:
            self.first_page.disabled = True
            self.previous_page.disabled = True
            self.next_page.disabled = False
            self.last_page.disabled = False

        elif page == self.max_pages - 1:
            self.first_page.disabled = False
            self.previous_page.disabled = False
            self.next_page.disabled = True
            self.last_page.disabled = True

        else:
            self.first_page.disabled = False
            self.previous_page.disabled = False
            self.next_page.disabled = False
            self.last_page.disabled = False

        return await self.format_page(self._data[page])

    async def format_page(self, data: Any) -> discord.Embed:
        raise NotImplemented

    @discord.ui.button(label='<<', style=discord.ButtonStyle.gray)
    async def first_page(self, _, interaction: discord.Interaction) -> None:
        embed = await self._go_to(0)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label='<', style=discord.ButtonStyle.gray)
    async def previous_page(self, _, interaction: discord.Interaction) -> None:
        embed = await self._go_to(self._current_page-1)
        await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label='▢', style=discord.ButtonStyle.red)
    async def _stop(self, _, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label='>', style=discord.ButtonStyle.gray)
    async def next_page(self, _, interaction: discord.Interaction) -> None:
        embed = await self._go_to(self._current_page+1)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='>>', style=discord.ButtonStyle.gray)
    async def last_page(self, _, interaction: discord.Interaction) -> None:
        embed = await self._go_to(self.max_pages - 1)
        await interaction.response.edit_message(embed=embed, view=self)

    async def start(self, channel: discord.abc.Messageable) -> discord.Message:
        if self.max_pages == 1:
            self.message = await channel.send(embed=await self.format_page(self._data[0]))
            self.stop()
        else:
            self.message = await channel.send(embed=await self._go_to(0), view=self)
            
        return self.message