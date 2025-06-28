import discord
from discord.ext import commands

# Keywords to detect
KEYWORDS = {
    "筑付": "筑附",
    "付属中": "附属中",
    "大学付属": "大学附属",
    "桐蔭祭": "桐陰祭",
    "桐蔭会": "桐陰会"
}

class AffiliatedPolice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # Check if any keyword is in the message content
        message_content = message.content # No need for lower() with Japanese keywords

        found_keyword = None
        for keyword in KEYWORDS.keys():
            if keyword in message_content:
                found_keyword = keyword
                break

        if found_keyword:
            correct_term = KEYWORDS[found_keyword]
            # Action to be taken when a keyword is found
            print(f"メッセージ内でキーワード '{found_keyword}' が検出されました： {message.content}")
            await message.reply(f"🚨附属警察出動！！！🚨\n「{found_keyword}」ではなく「{correct_term}」です！！")

async def setup(bot):
    await bot.add_cog(AffiliatedPolice(bot))
