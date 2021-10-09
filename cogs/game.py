from __future__ import annotations

import asyncio
import asyncpg
import discord
import json

from bot import BunkerBot
from context import BBContext
from utils.constants import MR_K, SIGNAL, TICKET
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from random import randint, choices
from typing import List, Optional, Tuple, Dict
from utils.checks import spam_channel_only, is_beta_tester
from utils.levels import LeaderboardPlayer


TABLE_CURRENCY = 'events.currency'
TABLE_GAME_TTL = 'events.game_ttl'
AWARDS = { # difficulty_level: (min reward, max reward)
    75: (10, 20), # easy
    45: (30, 50), # medium
    25: (80, 100) # hard
}


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
        outcome, profit = self.view.determine_situation_successs
        self.view.player_score += profit
        self.view.clear_items()

        outcome_response = ''
        for outcome_response, outcome_bool in self.option[1]:
            if outcome_bool == outcome:
                break


        self.view.add_item(SegwayButton())
        embed = discord.Embed(description=f'Total: {self.view.player_score} {TICKET}\n{outcome_response}. You earned {profit} {TICKET}' if profit > 0 else f'You lost {-profit} {TICKET}').set_image(url=SIGNAL)
        await interaction.response.edit_message(embed=embed, view=self.view)
        

class SegwayButton(discord.ui.Button):
    """
    A discord button that is sent between game situations
    """

    view: GameView
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.gray, 
            label='Next'
        )
    
    async def callback(self, interaction: discord.Interaction):
        self.view.clear_items()
        if self.view.situations:
            next_situation = self.view.situations.pop()

            for option in next_situation.options:
                self.view.add_item(GameButton(option))
        
            embed = discord.Embed(description=f'Total: {self.view.player_score} {TICKET}\n{next_situation.desciption}').set_image(url=SIGNAL)
            await interaction.response.edit_message(embed=embed, view=self.view)

        else:
            if self.view.player_score > 0:
                self.view.add_item(PayoutButton(f'{self.view.player_score} (Collect)'))
                await interaction.response.edit_message(view=self.view)
            else:
                embed= discord.Embed(description='You are lucky I am not making you pay for my losses.').set_image(url=MR_K)
                await interaction.response.edit_message(embed=embed, view=None)
                self.view.stop()


class PayoutButton(discord.ui.Button):
    """
    A discord button that is sent at the end of the game when all situations are delt with. This is only sent if the survivor
    profited

    Parameters
    -----------
    label: str
        The text that appears on this button
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


class DifficultySelect(discord.ui.Select):
    """
    A discord select menu that is sent at the start of the game. This allows the survivor to select the difficulty level of the game.
    Higher the difficulty, better the prizes. The select is disabled if the player is not at least level 5

    Parameters
    -----------
    placeholder: str
        The text that appears on the select when no option is selected
    disabled: bool
        bool representing if the select is disabled or not
    """

    view: GameView
    def __init__(self, *, placeholder: Optional[str], disabled: bool) -> None:
        super().__init__(
            placeholder=placeholder, 
            disabled=disabled, 
            options=[
                discord.SelectOption(label='Easy', value='75'),
                discord.SelectOption(label='Medium', value='45'),
                discord.SelectOption(label='Hard', value='25')
            ]
            )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        self.disabled = True
        self.view.difficulty = int(self.values[0])
        await interaction.response.edit_message(view=self.view)


class BoostSelect(discord.ui.Select):
    """
    A discord select menu that is sent at the start of the game. This allows the survivor to select a boost that is applied to the game.
    The select is disabled if the player is not at least level 10

    Parameters
    -----------
    placeholder: str
        The text that appears on the select when no option is selected
    disabled: bool
        bool representing if the select is disabled or not
    """

    view: GameView
    def __init__(self, *, placeholder: Optional[str], disabled: bool) -> None:
        super().__init__(
            placeholder=placeholder, 
            disabled=disabled,
            options=[
                discord.SelectOption(label='No losses', description='Even if you lose a situation you will not recieve negative points.', value='1'),
                discord.SelectOption(label='2x Rewards', description='Get double the rewards!.', value='2'),
                discord.SelectOption(label='One extra situation', description='Instead of 3 situations you face 4!', value='3')
            ]
            )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = int(self.values[0])
        self.disabled = True
        if val == 1:
            self.view.no_losses = True
        elif val == 2:
            self.view.double_rewards = True
        elif val == 3:
            self.view.no_of_situations += 1
        await interaction.response.edit_message(view=self.view)


class ChooseGameSelect(discord.ui.Select):
    """
    A discord select menu that is sent at the start of the game. This allows the survivor to select an event for the game.

    Parameters
    -----------
    options: List[discord.SelectOption]
        List of Select Options each representing an event
    """
    view: GameView
    def __init__(self, *, options: List[discord.SelectOption]) -> None:
        super().__init__(
            placeholder='Select Task',
            options=options, 
            )

    async def callback(self, interaction: discord.Interaction) -> None:
        event_id = int(self.values[0])
        query = 'SELECT description, outcomes FROM events.situations WHERE game_id = $1 ORDER BY random() LIMIT $2'
        self.view.clear_items()

        async with self.view.bot.pool.acquire() as con:
            rows: List[asyncpg.Record] = await con.fetch(query, event_id, self.view.no_of_situations)
            self.view.situations = [Situation(description, json.loads(options)) for (description, options) in rows]

        next_situation = self.view.situations.pop()
        for option in next_situation.options:
            self.view.add_item(GameButton(option))
        
        embed = discord.Embed(description=f'Total: {self.view.player_score} {TICKET}\n{next_situation.desciption}').set_image(url=SIGNAL)
        await interaction.response.edit_message(embed=embed, view=self.view)


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
        self.no_of_situations: int = 3
        self.player_score: int = 0
        self.difficulty: int = 75
        self.double_rewards: bool = False
        self.no_losses: bool = False

        if player.level < 5:
            self.add_item(DifficultySelect(placeholder='Reach lvl 5 to unlock difficulties', disabled=True))
        else:
            self.add_item(DifficultySelect(placeholder='Select Difficulty', disabled=False))

        if player.level < 10:
            self.add_item(BoostSelect(placeholder='Reach lvl 10 to unlock boosts', disabled=True))
        else:
            self.add_item(BoostSelect(placeholder='Select Boost', disabled=False))

        self.add_item(ChooseGameSelect(options=[discord.SelectOption(label=game_name, value=str(game_id)) for (game_name, game_id) in game_names]))

    @property
    def determine_situation_successs(self) -> Tuple[bool, int]:
        outcome = True if randint(1, 100) <= self.difficulty else False
        min_rewards, max_reward = AWARDS[self.difficulty]
        prize = randint(min_rewards, max_reward) if outcome else -randint(min_rewards/2, max_reward/2)

        if self.no_losses and prize < 0:
            prize = 0

        if self.double_rewards and prize > 0:
            prize *= 2

        return outcome, prize

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return self.player.user.id == interaction.user.id # type: ignore


class game(commands.Cog):

    games: List[Tuple[str, int]]
    game_tasks: Dict[str, asyncio.Task] = {}
    def __init__(self, bot: BunkerBot) -> None:
        self.bot = bot
        bot.loop.create_task(self.get_games())
        self.game_command_ttl.start()

    async def get_games(self) -> None:
        query = 'SELECT game_id, name FROM events.games ORDER BY random()'

        async with self.bot.pool.acquire() as con:
            rows = await con.fetch(query)
            self.games = [(game_name, game_id) for (game_id, game_name) in rows]

    def cog_unload(self):
        for task in self.game_tasks.values():
            task.cancel()
    
    @tasks.loop(hours=1)
    async def game_command_ttl(self):
        query = f'SELECT user_id, time FROM {TABLE_GAME_TTL} WHERE time < $1'

        async with self.bot.pool.acquire() as con:
            rows = await con.fetch(query, discord.utils.utcnow() + timedelta(hours=1))
        
        for row in rows:
            task = self.bot.loop.create_task(self.remove_cooldown_from_game(row['user_id'], row['time']), name=str(row['user_id']))
            self.game_tasks[task.get_name()] = task

    async def remove_cooldown_from_game(self, user_id: int, time: datetime) -> None:
        await discord.utils.sleep_until(time)
        query = f'DELETE FROM {TABLE_GAME_TTL} WHERE user_id = $1'
        async with self.bot.pool.acquire() as con:
            await con.execute(query, user_id)
        del self.game_tasks[str(user_id)]
    
    @commands.command(aliases=['tasks'])
    @is_beta_tester()
    @spam_channel_only()
    async def task(self, ctx: BBContext):
        """
        A bunker bot special game. Complete tasks given to you by MR.K and earn tickets!
        """

        con = await ctx.get_connection()
        query = f'SELECT time FROM {TABLE_GAME_TTL} WHERE user_id = $1'

        if time := await con.fetchval(query, ctx.author.id):
            embed = discord.Embed(description=f'Back so soon? I do not have any more tasks for you right now. Check again {discord.utils.format_dt(time, "R")}')
            embed.set_image(url=MR_K)
            return await ctx.reply(embed=embed)

        query = f'INSERT INTO {TABLE_GAME_TTL}(user_id, time) VALUES($1, $2)'
        await con.execute(query, ctx.author.id, discord.utils.utcnow() + timedelta(days=1))
        player = await LeaderboardPlayer.fetch(await ctx.get_connection(), ctx.author)

        if player.level < 1:
            return await ctx.send('You must be at least level 1 to play the game :(')

        embed = discord.Embed(description="Hey survivor!\nCan you do me favor? Don't worry you succeed and you get payed well").set_image(url=MR_K)
        game = GameView(player, choices(self.games, k=1)) # TODO add more events and change k to 3
        game.bot = self.bot
        await ctx.send(embed=embed, view=game)


def setup(bot: BunkerBot) -> None:
    bot.add_cog(game(bot))