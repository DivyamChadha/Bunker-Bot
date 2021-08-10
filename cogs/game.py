from __future__ import annotations
import re

import asyncpg
import discord
import json

from bot import BunkerBot
from context import BBContext
from utils.constants import MR_K, SIGNAL, TICKET
from discord.ext import commands
from random import randint, choices
from typing import List, Tuple, Dict
from utils.levels import LeaderboardPlayer


TABLE_CURRENCY = 'events.currency'


class Situation:
    """
    Represents a Situation that player faces during the game

    Parameters
    -----------
    description: str
        Description of the situation
    options: Dict[str, Dict[str, bool]]
        A dictionary with key-value pairs as {'description': {'outcome_response': 'outcome_bool'}} where outcome_response is 
        the response given if that outcome is selected and outcome_bool represents if the outcome was profitable for the survivor
    """

    __slots__ = ('desciption', 'options')

    def __init__(self, description: str, options: Dict[str, Dict[str, bool]]) -> None:
        self.desciption = description
        self.options = [(k, list(v.items())) for k, v in options.items()]


class GameButton(discord.ui.Button):
    """
    A discord button that represents an option the player can choose during a game situation

    Parameters
    -----------
    option: Tuple[str, List[Tuple[str, bool]]]
        A tuple of possible outcomes as (outcome_description, [(outcome_response, outcome_bool)])
    """

    view: GameView
    def __init__(self, option: Tuple[str, List[Tuple[str, bool]]]):
        self.option = option

        super().__init__(
            style=discord.ButtonStyle.gray, 
            label=option[0]
        )
    
    async def callback(self, interaction: discord.Interaction):
        outcome = self.view.determine_situation_successs
        diff = self.view.difficulty
        profit = randint(4*diff, 8*diff) if outcome else -randint(2*diff, 5*diff)
        self.view.player_score += profit
        self.view.clear_items()

        outcome_response = ''
        for outcome_response, outcome_bool in self.option[1]:
            if outcome_bool == outcome:
                break

        if self.view.situations:
            self.view.add_item(SegwayButton(self.view.situations.pop()))
            embed = discord.Embed(description=f'{outcome_response}. You earned {profit} {TICKET}' if profit > 0 else f'You lost {-profit} {TICKET}').set_image(url=SIGNAL)
            await interaction.response.edit_message(embed=embed, view=self.view)
        
        else:
            if self.view.player_score > 0:
                self.view.add_item(PayoutButton(f'{self.view.player_score} (Collect)'))
                await interaction.response.edit_message(view=self.view)
            else:
                embed= discord.Embed(description='You are lucky I am not making you pay for my losses.').set_image(url=MR_K)
                await interaction.response.edit_message(embed=embed, view=None)
                self.view.stop()
        

class SegwayButton(discord.ui.Button):
    """
    A discord button that is sent between game situations

    Parameters
    -----------
    next_situation: Situation
        The next situation the survivor has to face during the event
    """

    view: GameView
    def __init__(self, next_situation: Situation):
        self.next_situation = next_situation

        super().__init__(
            style=discord.ButtonStyle.gray, 
            label='Next'
        )
    
    async def callback(self, interaction: discord.Interaction):
        self.view.clear_items()

        for option in self.next_situation.options:
            self.view.add_item(GameButton(option))
        
        embed = discord.Embed(description=self.next_situation.desciption).set_image(url=SIGNAL)
        await interaction.response.edit_message(embed=embed, view=self.view)


class PayoutButton(discord.ui.Button):
    """
    A discord button that is sent at the end of the game when all situations are delt with. This is only sent if the survivor
    profited
    """

    view: GameView
    def __init__(self, label: str):

        super().__init__(
            style=discord.ButtonStyle.gray, 
            label=label,
            emoji=TICKET
        )
    
    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(description='Well done survivor. Come back tomorrow for another task.').set_image(url=MR_K)
        
        async with self.view.bot.pool.acquire() as con:
            await self.view.player.update(con, tickets=self.view.player_score)
        
        await interaction.response.edit_message(embed=embed, view=None)
        self.view.stop()


class GameView(discord.ui.View):
    """
    The discord.ui.View that handles the game

    Parameters
    -----------
    player: LeaderboardPlayer
        The user playing the game
    game_names: List[Tuple[str, int]]
        A list of (game_name, game_id) tuples

    Attributes
    ------------
    bot: BunkerBot
        The instance of BunkerBot on which the game is running
    situations: List[Situation]
        A list of situations the player will have to deal with during the game
    """

    bot: BunkerBot
    situations: List[Situation]
    def __init__(self, player: LeaderboardPlayer, game_names: List[Tuple[str, int]]):
        super().__init__()
        self.player = player
        self.player_score: int = 0
        self.difficulty: int = 2

        self.choose_difficulty.options = [
            discord.SelectOption(label='Easy', value='2', default=True),
            discord.SelectOption(label='Medium', value='3'),
            discord.SelectOption(label='Hard', value='4')
        ]

        self.choose_event.options = [discord.SelectOption(label=game_name, value=str(game_id)) for (game_name, game_id) in game_names]

    @property
    def determine_situation_successs(self) -> bool:
        return True if randint(1, 100) % self.difficulty == 0 else False

    @discord.ui.select(placeholder='Select Difficulty')
    async def choose_difficulty(self, select: discord.ui.Select, interaction: discord.Interaction) -> None:
        select.disabled = True
        self.difficulty = int(select.values[0])
        await interaction.response.edit_message(view=self)

    @discord.ui.select(placeholder='Select Task')
    async def choose_event(self, select: discord.ui.Select, interaction: discord.Interaction) -> None:
        event_id = int(select.values[0])
        query = 'SELECT description, outcomes FROM events.situations WHERE game_id = $1 ORDER BY random() LIMIT 3'
        self.clear_items()

        async with self.bot.pool.acquire() as con:
            rows: List[asyncpg.Record] = await con.fetch(query, event_id)
            self.situations = [Situation(description, json.loads(options)) for (description, options) in rows]

        next_situation = self.situations.pop()
        for option in next_situation.options:
            self.add_item(GameButton(option))
        
        embed = discord.Embed(description=next_situation.desciption).set_image(url=SIGNAL)
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.player.user.id == interaction.user.id # type: ignore



class game(commands.Cog):

    games: List[Tuple[str, int]]
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        bot.loop.create_task(self.get_games())

    async def get_games(self) -> None:
        query = 'SELECT game_id, name FROM events.games ORDER BY random()'

        async with self.bot.pool.acquire() as con:
            rows = await con.fetch(query)
            self.games = [(game_name, game_id) for (game_id, game_name) in rows]
    

    @commands.command() # TODO name?
    async def test(self, ctx: BBContext):
        player = await LeaderboardPlayer.fetch(await ctx.get_connection(), ctx.author)

        if player.level < 1:
            return await ctx.send('You must be at least level 1 to play the game :(')

        embed = discord.Embed(description="Hey survivor!\nCan you do me favor? Don't worry you succeed and you get payed well").set_image(url=MR_K)
        game = GameView(player, choices(self.games, k=1)) # TODO add more events and change k to 3
        game.bot = self.bot
        await ctx.send(embed=embed, view=game)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(game(bot))