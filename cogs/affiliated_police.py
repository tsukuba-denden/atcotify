import discord
from discord.ext import commands

# Keywords to detect
KEYWORDS = ["筑付", "付属中", "大学付属", "桐陰祭", "桐陰会"]

class AffiliatedPolice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # Check if any keyword is in the message content
        message_content = message.content.lower() # Convert to lowercase for case-insensitive matching if needed, though Japanese keywords might not need this.

        found_keyword = None
        for keyword in KEYWORDS:
            if keyword in message_content:
                found_keyword = keyword
                break

        if found_keyword:
            # Action to be taken when a keyword is found
            print(f"Keyword '{found_keyword}' detected in message: {message.content}")
            await message.reply("附属警察です！") # Changed from the previous reply

async def setup(bot):
    await bot.add_cog(AffiliatedPolice(bot))
