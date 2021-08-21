import re

from context import BBContext
from discord.ext import commands

time_regex = re.compile(r'(\d{1,5}(?:[.,]?\d{1,5})?)([smhdw])', re.IGNORECASE)
time_dict = {
    's': 1, 
    'm': 60, 
    'h': 3600, 
    'd': 86400,
    'w': 604800
    }

class TimeConverter(commands.Converter):
    async def convert(self, ctx: BBContext, argument: str) -> float:
        matches = time_regex.findall(argument)
        time = 0
        for v, k in matches:
            try:
                time += time_dict[k]*float(v)
            except KeyError:
                raise commands.BadArgument(f'{k} is an invalid time specifer! s/m/h/d/w are valid and stand for seconds, minutes, hours, days and weeks respectively.')
            except ValueError:
                raise commands.BadArgument(f'{v} is not a number!')
        return time