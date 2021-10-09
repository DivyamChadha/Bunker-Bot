from __future__ import annotations

from .constants import *
from discord.ext import commands
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import BBContext

def is_beta_tester():
    def predicate(ctx: BBContext) -> bool:
        if ret := ctx.author.id in ctx.bot.beta_testers:
            return ret
        else:
            raise commands.CheckFailure('This command is currently limited to beta testers only.')
    return commands.check(predicate)

def is_staff():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := any(role_id in STAFF for role_id in role_ids):
            return ret
        else:
            raise commands.CheckFailure('This is a staff only command.')
    return commands.check(predicate)

def is_staff_or_guide():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := any(role_id in STAFF_AND_GUIDE for role_id in role_ids):
            return ret
        else:
            raise commands.CheckFailure('This is command is limited to staff or staff in training only.')
    return commands.check(predicate)

def is_staff_or_support():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := any(role_id in STAFF_AND_SUPPORT for role_id in role_ids):
            return ret
        else:
            raise commands.CheckFailure('This command is limited to staff and ambassadors only.')
    return commands.check(predicate)

def has_kick_permissions():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := any(role_id in ELEVATED_STAFF for role_id in role_ids):
            return ret
        else:
            raise commands.CheckFailure('This command is limited to global moderators and above only.')
    return commands.check(predicate)

def is_clan_leader():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := clan_leaders in role_ids:
            return ret
        else:
            raise commands.CheckFailure('This is command is limited to clan leaders only.')
    return commands.check(predicate)

def is_clan_coord():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := clan_cords in role_ids:
            return ret
        else:
            raise commands.CheckFailure('This is command is limited to clan coordinators only.')
    return commands.check(predicate)

def is_event_coord():
    def predicate(ctx: BBContext) -> bool:
        role_ids = set(role.id for role in ctx.author.roles) # type: ignore (DM message intent is disabled, author will always be a member)
        if ret := events_coords in role_ids:
            return ret
        else:
            raise commands.CheckFailure('This is command is limited to event coordinators only.')
    return commands.check(predicate)

def spam_channel_only():
    def predicate(ctx: BBContext) -> bool:
        if ret := ctx.channel.id in SPAM_CHANNELS:
            return ret
        else:
            raise commands.CheckFailure('This command can only be used in one of the spam channels.')
    return commands.check(predicate)
