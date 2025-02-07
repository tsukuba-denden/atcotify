import asyncio
import datetime
import os

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, ChannelSelect

CONTESTS_FILE = "asset/contests.yaml"
THREADS_FILE = "asset/threads.yaml"


class Threads(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_contests_and_create_threads.start()  # タスクを初期化時に開始
        self.threads_config = self.load_threads_config()

    def load_threads_config(self):
        """スレッド設定をYAMLファイルから読み込む"""
        if os.path.exists(THREADS_FILE):
            with open(THREADS_FILE, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config if config is not None else {}
        return {}

    def save_threads_config(self):
        """スレッド設定をYAMLファイルに保存する"""
        with open(THREADS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                self.threads_config,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    def load_contests(self) -> list[dict]:
        """コンテスト情報をYAMLファイルから読み込む"""
        if os.path.exists(CONTESTS_FILE):
            with open(CONTESTS_FILE, "r", encoding="utf-8") as f:
                contests = yaml.safe_load(f)
                return contests if contests is not None else []
        return []

    def save_contests(self, contests: list[dict]):
        """コンテスト情報をYAMLファイルに保存"""
        with open(CONTESTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                contests,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    @tasks.loop(minutes=1)
    async def check_contests_and_create_threads(self):
        """コンテストをチェックし、スレッドを作成する"""
        now = datetime.datetime.now()
        contests = self.load_contests()
        if not contests:
            return

        for guild_id_str, config in self.threads_config.items():
            if not config.get("enabled", False):  # 機能がOFFならスキップ
                continue

            channel_id = config.get("channel_id")
            if not channel_id:  # チャンネルID未設定ならスキップ
                continue

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                print(f"スレッド作成: チャンネルID {channel_id} が見つかりません")
                continue

            for contest in contests:
                # スレッド作成済みならスキップ
                if contest.get("threads_created"):
                    continue

                start_time = datetime.datetime.strptime(
                    contest["start_time"], "%Y-%m-%d %H:%M:%S"
                )
                if (
                    start_time - datetime.timedelta(hours=1)
                    <= now
                    < start_time - datetime.timedelta(minutes=59)
                ):
                    try:
                        thread = await channel.create_thread(
                            name=contest["name"],
                            type=discord.ChannelType.public_thread,
                            auto_archive_duration=1440,
                        )
                        await thread.send(
                            f"{contest['name']} のスレッドを作成しました！"
                        )
                        print(f"スレッド {contest['name']} を作成しました")

                        # スレッド作成済みフラグを立てる
                        contest["threads_created"] = True
                        self.save_contests(contests)

                    except discord.errors.Forbidden:
                        print(
                            f"スレッド作成: チャンネル {channel.name} (ID: {channel_id}) でスレッド作成権限がありません。"
                        )
                    except Exception as e:
                        print(f"スレッド作成中にエラーが発生しました: {e}")

    @check_contests_and_create_threads.before_loop
    async def before_check_contests_and_create_threads(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="set_thread_channel", description="スレッドを作成するチャンネルを設定"
    )
    async def set_thread_channel(self, interaction: discord.Interaction):
        """スレッド作成チャンネル設定コマンド"""
        guild_id = str(interaction.guild_id)
        view = ChannelSelectView(self, guild_id)
        await interaction.response.send_message(
            "スレッドを作成するチャンネルを選択してください", view=view, ephemeral=True
        )

    @app_commands.command(
        name="toggle_threads", description="スレッド作成機能のON/OFFを切り替え"
    )
    async def toggle_threads(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        if guild_id not in self.threads_config:
            self.threads_config[guild_id] = {"enabled": False}  # 初期値
        self.threads_config[guild_id]["enabled"] = not self.threads_config[
            guild_id
        ].get("enabled", False)
        self.save_threads_config()
        status = "ON" if self.threads_config[guild_id]["enabled"] else "OFF"
        await interaction.response.send_message(
            f"スレッド作成機能を {status} にしました。", ephemeral=True
        )


class ChannelSelectView(View):  # ChannelSelect 用の View を作成
    def __init__(self, cog: Threads, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.add_item(self.create_channel_select())

    def create_channel_select(self) -> ChannelSelect:
        """チャンネル選択メニューを作成する"""
        channel_select = ChannelSelect(
            channel_types=[discord.ChannelType.text],
            custom_id="thread_channel_select",
        )
        channel_select.callback = self.channel_select_callback
        return channel_select

    async def channel_select_callback(self, interaction: discord.Interaction):
        """チャンネルが選択されたときのコールバック"""
        channel_id = interaction.data["values"][0]  # 選択されたチャンネルIDを取得
        self.cog.threads_config[self.guild_id] = {
            "channel_id": str(channel_id),
            "enabled": True,
        }  # enabledも一緒に保存
        self.cog.save_threads_config()
        channel_mention = f"<#{channel_id}>"  # チャンネルメンションを作成
        embed = discord.Embed(
            title="スレッド作成チャンネル設定完了！",
            description=f"スレッド作成チャンネルを {channel_mention} に設定しました！",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, view=None, embed=embed)


async def setup(bot):
    await bot.add_cog(Threads(bot))
