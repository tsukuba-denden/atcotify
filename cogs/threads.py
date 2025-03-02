import asyncio
import datetime
import os

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, ChannelSelect, Select, View

from .contest_data import ContestData  # ContestData Cog をインポート

THREADS_FILE = "asset/threads.yaml"
CONTEST_TYPES = ["ABC", "ARC", "AGC", "AHC"]


class Threads(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_contests_and_create_threads.start()
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

    @tasks.loop(minutes=1)
    async def check_contests_and_create_threads(self):
        """コンテストをチェックし、スレッドを作成する"""
        now = datetime.datetime.now()
        contest_data_cog = self.bot.get_cog("ContestData")  # ContestData Cogを取得
        if not contest_data_cog:
            print("Error: ContestData cog not found!")
            return
        contests = contest_data_cog.contests  # ContestData Cogからコンテスト情報を取得
        if not contests:
            return

        for guild_id_str, config in self.threads_config.items():
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
                # コンテストタイプごとの設定を確認
                contest_type_config = config.get(contest["type"])
                if not contest_type_config or not contest_type_config.get(
                    "enabled", False
                ):  # コンテストタイプの設定がないか、Falseならスキップ
                    continue

                if (
                    start_time - datetime.timedelta(hours=1)
                    <= now
                    < start_time - datetime.timedelta(minutes=59)
                ):
                    try:
                        # 括弧がない場合のエラー回避
                        thread_name = contest["type"]
                        if "(" in contest["name"]:
                            nameindex = contest["name"].index("(")
                            thread_name += contest["name"][-4:-1] + " " + contest["name"][:nameindex]
                        else:
                            # 括弧がない場合のフォールバック
                            thread_name = f"{contest['type']} {contest['name']}"
                        
                        # スレッド名の長さを制限（Discordの制限は100文字）
                        if len(thread_name) > 100:
                            thread_name = thread_name[:97] + "..."
                            
                        thread = await channel.create_thread(
                            name=thread_name,
                            type=discord.ChannelType.public_thread,
                            auto_archive_duration=1440,
                        )
                        await thread.send(
                            f"{contest['name']} のスレッドを作成しました！"
                        )
                        print(f"スレッド {contest['name']} を作成しました")

                        # スレッド作成済みフラグを立てる
                        contest["threads_created"] = True
                        contest_data_cog.save_contests(
                            contests
                        )  # ContestData Cog の save_contests を呼び出す

                    except discord.errors.Forbidden:
                        print(
                            f"スレッド作成: チャンネル {channel.name} (ID: {channel_id}) でスレッド作成権限がありません。"
                        )
                    except ValueError as e:
                        print(f"スレッド名の生成中にエラーが発生しました: {e}")
                    except discord.errors.HTTPException as e:
                        print(f"Discord APIエラー: {e} (レート制限またはスレッド数制限の可能性があります)")
                    except Exception as e:
                        print(f"スレッド作成中にエラーが発生しました: {e}")

    @check_contests_and_create_threads.before_loop
    async def before_check_contests_and_create_threads(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="thread---show", description="現在のスレッド設定を表示")
    async def show_thread_settings(self, interaction: discord.Interaction):
        """現在のスレッド設定を表示するコマンド"""
        guild_id = str(interaction.guild_id)

        # ギルドの設定が存在するか確認
        if guild_id not in self.threads_config:
            await interaction.response.send_message(
                "このサーバーではスレッド設定が行われていません。\n`/thread---set_channel` コマンドでチャンネルを設定してください。",
                ephemeral=True,
            )
            return

        # チャンネルが設定されているか確認
        channel_id = self.threads_config[guild_id].get("channel_id")
        if not channel_id:
            await interaction.response.send_message(
                "スレッド作成チャンネルが設定されていません。\n`/thread---set_channel` コマンドでチャンネルを設定してください。",
                ephemeral=True,
            )
            return

        # Embedを作成
        embed = discord.Embed(
            title="スレッド設定情報",
            description="現在のスレッド自動作成に関する設定情報です",
            color=0x00BFFF,  # 水色
        )

        # チャンネル情報をフィールドに追加
        channel_mention = f"<#{channel_id}>"
        embed.add_field(
            name="スレッド作成チャンネル", value=channel_mention, inline=False
        )

        # コンテストタイプごとの設定をフィールドに追加
        contest_settings = ""
        for contest_type in CONTEST_TYPES:
            is_enabled = (
                self.threads_config[guild_id]
                .get(contest_type, {})
                .get("enabled", False)
            )
            status = "✅ 有効" if is_enabled else "❌ 無効"
            contest_settings += f"**{contest_type}**: {status}\n"

        embed.add_field(
            name="コンテストタイプ別設定", value=contest_settings, inline=False
        )

        # 使い方のヒントをフッターに追加
        embed.set_footer(
            text="設定を変更するには /thread---set_channel または /thread---set_contest_type コマンドを使用してください"
        )

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(
        name="thread---set_channel", description="スレッドを作成するチャンネルを設定"
    )
    async def set_thread_channel(self, interaction: discord.Interaction):
        """スレッド作成チャンネル設定コマンド"""
        guild_id = str(interaction.guild_id)
        # 初回設定時、コンテストタイプごとの設定を初期化 (Falseで初期化)
        if guild_id not in self.threads_config:
            self.threads_config[guild_id] = {"channel_id": None}
            for contest_type in CONTEST_TYPES:
                self.threads_config[guild_id][contest_type] = {"enabled": False}
            self.save_threads_config()

        view = ChannelSelectView(self, guild_id)
        await interaction.response.send_message(
            "スレッドを作成するチャンネルを選択してください", view=view, ephemeral=True
        )

    @app_commands.command(
        name="thread---set_contest_type",
        description="コンテストタイプごとのスレッド作成をON/OFF",
    )
    async def set_thread_type(self, interaction: discord.Interaction):
        """コンテストタイプごとのスレッド作成ON/OFF設定コマンド"""
        guild_id = str(interaction.guild_id)
        if guild_id not in self.threads_config or not self.threads_config[guild_id].get(
            "channel_id"
        ):
            await interaction.response.send_message(
                "先に `/thread---set_channel` コマンドでチャンネルを設定してください。",
                ephemeral=True,
            )
            return
        # ContestTypeThreadsView を表示
        view = ContestTypeThreadsView(self, guild_id)
        await interaction.response.send_message(
            "コンテストタイプごとのスレッド作成設定", view=view, ephemeral=True
        )


class ChannelSelectView(View):
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
        self.cog.threads_config[self.guild_id]["channel_id"] = str(
            channel_id
        )  # channel_id のみ更新
        self.cog.save_threads_config()
        channel_mention = f"<#{channel_id}>"  # チャンネルメンションを作成
        await interaction.response.edit_message(
            content=f"スレッド作成チャンネルを {channel_mention} に設定しました！\n`/thread---set_contest_type` コマンドで、コンテストタイプごとのスレッド作成設定を行ってください。",
            view=None,
        )


class ContestTypeThreadsView(View):
    """コンテストタイプごとのスレッド作成ON/OFF設定View"""

    def __init__(self, cog: Threads, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.threads_config = self.cog.threads_config[
            self.guild_id
        ]  # guild_id に紐づく設定を読み込む
        self.create_buttons()

    def create_buttons(self):
        """コンテストタイプごとのボタンを作成"""
        for contest_type in CONTEST_TYPES:
            is_enabled = self.threads_config.get(contest_type, {}).get("enabled", False)
            button = Button(
                label=f"{contest_type} ({'ON' if is_enabled else 'OFF'})",
                style=discord.ButtonStyle.green
                if is_enabled
                else discord.ButtonStyle.red,
                custom_id=f"threads_toggle_{contest_type}",
            )
            button.callback = self.create_button_callback(
                contest_type
            )  # コールバック関数を作成
            self.add_item(button)

    def create_button_callback(self, contest_type):
        """ボタンのコールバック関数を作成"""

        async def button_callback(interaction: discord.Interaction):
            # 設定を反転
            if contest_type not in self.threads_config:  # 設定がない場合は初期化
                self.threads_config[contest_type] = {"enabled": False}
            self.threads_config[contest_type]["enabled"] = not self.threads_config[
                contest_type
            ].get("enabled", False)
            self.cog.save_threads_config()

            # ボタンの表示を更新
            for child in self.children:
                if child.custom_id == f"threads_toggle_{contest_type}":
                    child.label = f"{contest_type} ({'ON' if self.threads_config[contest_type]['enabled'] else 'OFF'})"
                    child.style = (
                        discord.ButtonStyle.green
                        if self.threads_config[contest_type]["enabled"]
                        else discord.ButtonStyle.red
                    )
                    break
            await interaction.response.edit_message(view=self)

        return button_callback


async def setup(bot):
    await bot.add_cog(Threads(bot))
