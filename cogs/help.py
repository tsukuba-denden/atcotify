import discord
from discord import app_commands
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Botの使い方を表示します")
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(title="コマンド一覧", color=discord.Color.blue())

        embed.add_field(
            name="`/help`",
            value="今まさにあなたが使ったヘルプコマンドです",
            inline=False,
        )
        embed.add_field(
            name="`/reminder---set`",
            value="AtCoderのコンテストリマインダーを設定します。コンテストの種類、通知時間を選択できます。",
            inline=False,
        )
        embed.add_field(
            name="`/reminder---set_channel`",
            value="リマインダーを送信するチャンネルを設定します。",
            inline=False,
        )
        embed.add_field(
            name="`/reminder---show`",
            value="現在設定されているリマインダーを表示します。",
            inline=False,
        )
        embed.add_field(
            name="`/result---contest_result`",
            value="コンテストの結果画像を送信します",
            inline=False,
        )
        embed.add_field(
            name="`/result---set_channel`",
            value="コンテスト結果を自動送信するチャンネルを設定します",
            inline=False,
        )
        embed.add_field(
            name="`/thread---set_channel`",
            value="コンテスト1時間前にスレッドを自動作成するチャンネルを設定します",
            inline=False,
        )
        embed.add_field(
            name="`/thread---set_contest_type`",
            value="コンテストタイプごとにスレッド作成のON/OFFを設定します。",
            inline=False,
        )   
        embed.add_field(
            name="`/school_set school_name school_type`",
            value="このサーバーで表示・通知する学校名と中学/高校を設定します。管理者または許可ユーザーのみ実行できます。",
            inline=False,
        )
        embed.add_field(
            name="`/school_unset`",
            value="このサーバーの学校名設定を削除し、デフォルトの筑波大学附属中学校に戻します。管理者または許可ユーザーのみ実行できます。",
            inline=False,
        )
        embed.add_field(
            name="`/school_rank [school_name]`",
            value="[AJL](https://info.atcoder.jp/utilize/school/ajl)における、指定した学校またはこのサーバーに設定された学校の順位やスコア・一つ上の学校との比較を表示します。",
            inline=False,
        )
        embed.add_field(
            name="`/school_student_rank [school_name]`",
            value="AJLにおける、指定した学校またはこのサーバーに設定された学校の生徒順位・1つ上の順位の人との比較・新規参加者を表示します。",
            inline=False,
        )
        embed.add_field(
            name="`/school_rank_set_ch` / `/school_rank_unset_ch`",
            value="学校順位の定期通知チャンネルを設定・解除します。管理者または許可ユーザーのみ実行できます。",
            inline=False,
        )
        embed.add_field(
            name="`/school_student_rank_set_ch` / `/school_student_rank_unset_ch`",
            value="生徒順位の定期通知チャンネルを設定・解除します。管理者または許可ユーザーのみ実行できます。",
            inline=False,
        )
        embed.add_field(
            name="筑波用の旧コマンド",
            value="`/tsukuba_rank`、`/tsukuba_student_rank`、`/tsukuba_rank---set_ch`、`/tsukuba_rank---unset_ch`、`/tsukuba_student_rank---set_ch`、`/tsukuba_student_rank---unset_ch` は互換用に残っています。",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
