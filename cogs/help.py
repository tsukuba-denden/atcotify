import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Botの使い方を表示します")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(title="コマンド一覧", color=discord.Color.blue())

        # コマンドとその説明を追加
        embed.add_field(name="`/tsukuba_rank`", value="[AJL](https://info.atcoder.jp/utilize/school/ajl)における筑附の順位やスコア・一つ上の学校との比較を表示します", inline=False)
        embed.add_field(name="`/tsukuba_student_rank`", value="AJLにおける筑附の生徒の順位・1つ上の順位の人との比較・新規参加者を表示します", inline=False)
        embed.add_field(name="`/help`", value="今まさにあなたが使ったヘルプコマンドです", inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))