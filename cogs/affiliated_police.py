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
            await message.reply("🚨 こちらは“UI/UX”警察です 🚨\nUIとUXは似て非なる概念であるため、スラッシュ区切りの表記は推奨されていません。UIが実体ある一つのモノであるのに対し、UXには実体がなく、それも一つとは限りません。人々それぞれに内在する感情や記憶などの「目に見えない何か」を体験と称します。また、ソフトウェアなどのUIの影響を受けずに形成される体験についてもしっかりと熟慮する必要があります。もしも二つを併記したい場合には、「UIとその体験」と書くと収まりが良くなります。ご検討をよろしくお願いいたします。")
            return

        if "アフォーダンス" in message_content:
            await message.reply("🚨 こちらはアフォーダンス警察です 🚨\nその「アフォーダンス」、**「シグニファイア」**ではありませんか？本来、ジェームズ・J・ギブソンが提唱したアフォーダンスは「環境が動物に提供する価値」そのものを指す客観的な概念です。ドン・ノーマンが著書『誰のためのデザイン？』でこの言葉を紹介した際、彼はこれを「ユーザーが直感的にどう扱えばいいか分かること（知覚されたアフォーダンス）」という意味で使いました。これにより、デザイン業界では「アフォーダンス＝使い方のヒント」という誤解が広まってしまいました。彼は後に、自身の定義がギブソンの本来の定義と混同されていることを認め、混乱を解消するために「シグニファイア」という用語を強調するようになりました。あなたはどうせアフォーダンスをシグニファイアの意味で使いましたよね？あなたの為に例を用いて説明しましょう。\n**アフォーダンス（実体）：**\nシステム上、その領域をクリックするとデータが送信される機能そのもの。画面にボタンの絵がなくても、そこをクリックして送信できるならアフォーダンスはあります。 \n**シグニファイア（合図）：**\n立体的なデザイン、ドロップシャドウ、あるいは「送信」という文字ラベルとか。これらが「ここは押せそうだ」とユーザーに伝える。\nつまり、**アフォーダンスは「設計（Design/Engineering）」**の問題であり、**シグニファイアは「伝達（Communication/UI）」**の問題なのです。優れたデザインとは、**「適切なアフォーダンスが用意され、それが適切なシグニファイアによって過不足なくユーザーに伝わっている状態」**を指します。")
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
