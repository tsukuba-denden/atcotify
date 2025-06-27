import discord
from discord.ext import commands

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def welcome(self, ctx):
        """Displays a welcome message for new users."""
        message = """
Welcome to the server!

This bot has several commands to help you with AtCoder.
Here are some of them:
- `/help`: Shows the list of all commands.
- `/reminder---set`: Sets a reminder for AtCoder contests.
- `/result---contest_result`: Shows the result of a contest.

Feel free to explore and use these commands!
"""
        await ctx.send(message)

async def setup(bot):
    await bot.add_cog(Welcome(bot))
