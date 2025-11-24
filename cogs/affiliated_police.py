import discord
from discord.ext import commands

# Keywords to detect
KEYWORDS = {
    "筑付": "筑附",
    "付属中": "附属中",
    "大学付属": "大学附属",
    "桐蔭祭": "桐陰祭",
    "桐蔭会": "桐陰会",
    "付属高": "附属高",
    "付属小": "附属小"

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

        if "UI/UX" in message_content:
            await message.reply("🚨 こちらは“UI/UX”警察です 🚨   UIとUXは似て非なる概念であるため、スラッシュ区切りの表記は推奨されていません。UIが実体ある一つのモノであるのに対し、UXには実体がなく、それも一つとは限りません。人々それぞれに内在する感情や記憶などの「目に見えない何か」を体験と称します。また、ソフトウェアなどのUIの影響を受けずに形成される体験についてもしっかりと熟慮する必要があります。もしも二つを併記したい場合には、「UIとその体験」と書くと収まりが良くなります。ご検討をよろしくお願いいたします。")
            return

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
