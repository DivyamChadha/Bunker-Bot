from __future__ import annotations
from typing import Union
import asyncpg
import discord


class LeaderboardPlayer:
    """
    Represents a player in leaderboard

    Parameters
    -----------
    user: Union[discord.Member, discord.User]
        Member or User object
    xp: float
        Player's current xp. This is xp stored in database + the one in memory
    tickets: int
        Amount of tickets the player has
    coins: int
        Amount of tickets the player has.
    level: int
        PLayer's current level
    """

    __slots__ = ('user', 'xp', 'tickets', 'coins', 'level')

    def __init__(self, user: Union[discord.Member, discord.User], *, xp: float = 0.0, tickets: int = 0, coins: int = 0, level: int = 0) -> None:
        self.user = user
        self.xp = xp
        self.tickets = tickets
        self.coins = coins
        self.level = level

    def __eq__(self, other) -> bool:
        if isinstance(other, LeaderboardPlayer):
            return self.user.id == other.user.id
        elif isinstance(other, int):
            return self.user.id == other
        return False

    def __repr__(self) -> str:
        return f'LeaderboardPlayer<id={self.user.id} xp={self.xp} coins={self.coins} tickets={self.tickets} level={self.level}>'

    @classmethod
    async def fetch(cls, con: asyncpg.Connection, user: Union[discord.Member, discord.User]):
        query = 'SELECT l.xp, c.level, c.tickets, c.coins \
                 FROM events.leaderboard l \
                 INNER JOIN events.currency c ON l.user_id = c.user_id \
                 WHERE l.user_id = $1'

        row = await con.fetchrow(query, user.id)
        if row:
            return cls(
                user,
                xp = row['xp'] or 0.0,
                tickets = row['tickets'] or 0,
                coins = row['coins'] or 0,
                level = row['level'] or 0 
            )
        
        return cls(user)

    async def update(self, con: asyncpg.Connection, *, tickets: int = 0, coins: int = 0) -> str:
        if tickets == coins == 0:
            raise ValueError('You need to provide at least one: tickets or coins')

        query = 'INSERT INTO events.currency(user_id, tickets, coins) \
                 VALUES($1, $2, $3) \
                 ON CONFLICT(user_id) DO UPDATE \
                 SET tickets = coalesce(events.currency.tickets, 0) + $2, \
                 coins = coalesce(events.currency.coins, 0) + $3'
        return await con.execute(query, self.user.id, tickets, coins)