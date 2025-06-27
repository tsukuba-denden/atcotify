import datetime
import os
import time
import traceback
from typing import Dict, List

import aiohttp
import discord
import yaml
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, ChannelSelect, Select, View

from env.config import Config

from .contest_data import ContestData  # ContestData Cogをインポート

# TODO: 全てのメッセージをembedに
# TODO: ABCをスケジュール(Discordの機能)化←いる？
# TODO: Android/iOSクライアント
# TODO: リアクションで参加者ロール付与
# TODO: sentのやつもcontests.yamlに保存
# TODO: Xmas、Otherのコンテストタイプに対応
# TODO: JOIに個別対応
# TODO: スレッドがある場合はそこにリマインドを送信
# TODO: バチャ立て対応(TCA版AtcoderNotify参考)
# TODO: コンテスト情報取得の部分は独自Cog化

config = Config()

CONTESTS_FILE = "asset/contests.yaml"
REMINDERS_FILE = "asset/reminders.yaml"
ATCODER_CONTESTS_URL = "https://atcoder.jp/contests/"

CONTEST_TYPES = ["ABC", "ARC", "AGC", "AHC"]
REMINDER_TIMES = [
    "1分前",
    "5分前",
    "10分前",
    "15分前",
    "30分前",
    "1時間前",
    "カスタム設定",
]
TIME_MAPPING = {
    "1分前": 1,
    "5分前": 5,
    "10分前": 10,
    "15分前": 15,
    "30分前": 30,
    "1時間前": 60,
}


class Reminder(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # self.contests = self.load_contests()
        self.reminders = self.load_reminders()
        # self.fetch_contests.start()  # タスクは ContestData Cog で開始
        self.check_reminders.start()  # Start the check_reminders task
        self.last_checked_date_no_abc = None
        self.check_no_abc_notification.start()

    @tasks.loop(minutes=1)
    async def check_no_abc_notification(self):
        contest_data_cog = self.bot.get_cog("ContestData")
        if not contest_data_cog or not contest_data_cog.contests:
            print("Error: ContestData cog not found or no contests loaded for 'check_no_abc_notification'.")
            return

        now = datetime.datetime.now()
        today_date = now.date()

        if self.last_checked_date_no_abc == today_date:
            # Already checked today or notification sent.
            return

        if now.weekday() == 5 and now.hour == 20 and now.minute == 0:  # Saturday 20:00
            print(f"[{now}] Saturday 20:00 detected. Checking for ABC contests...")

            abc_scheduled_for_2100 = False
            contests = contest_data_cog.contests
            for contest in contests:
                try:
                    contest_start_time = datetime.datetime.strptime(contest["start_time"], "%Y-%m-%d %H:%M:%S")
                    if (contest["type"] == "ABC" and
                            contest_start_time.weekday() == 5 and  # Saturday
                            contest_start_time.date() == today_date and
                            contest_start_time.hour == 21):
                        abc_scheduled_for_2100 = True
                        print(f"Found ABC contest: {contest['name']} scheduled for today at 21:00.")
                        break
                except ValueError:
                    print(f"Error parsing start_time for contest: {contest.get('name', 'Unknown Contest')}")
                    continue # Skip this contest if date parsing fails

            if not abc_scheduled_for_2100:
                print(f"[{now}] No ABC contest found for today (Saturday) at 21:00. Sending 'no ABC' notifications.")
                for guild_id_str, reminder_config in self.reminders.items():
                    if "ABC" not in reminder_config or not reminder_config["ABC"]:
                        continue

                    abc_config_list = reminder_config["ABC"]
                    abc_reminders_enabled = any(config.get("enabled", False) for config in abc_config_list)

                    if abc_reminders_enabled:
                        channel_id_str = reminder_config.get("reminder_channel_id")
                        if not channel_id_str:
                            print(f"Error: 'reminder_channel_id' not found for guild {guild_id_str}.")
                            continue

                        try:
                            channel_id = int(channel_id_str)
                        except ValueError:
                            print(f"Error: Invalid 'reminder_channel_id' format for guild {guild_id_str}: {channel_id_str}")
                            continue

                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            try:
                                await channel.send("今日はABCないです！！！")
                                print(f"Sent 'no ABC' notification to channel {channel_id} in guild {guild_id_str}.")
                            except discord.Forbidden:
                                print(f"Error: Missing permissions to send to channel {channel_id} in guild {guild_id_str}.")
                            except Exception as e:
                                print(f"Error sending 'no ABC' notification to channel {channel_id} in guild {guild_id_str}: {e}")
                        else:
                            print(f"Error: Channel {channel_id} not found for guild {guild_id_str}.")

            # Update last checked date after processing for Saturday 20:00
            self.last_checked_date_no_abc = today_date
            # self.save_reminders(self.reminders) # Not strictly needed as last_checked_date_no_abc is in-memory

    @check_no_abc_notification.before_loop
    async def before_check_no_abc_notification(self):
        await self.bot.wait_until_ready()

    async def run_fetch_contests(self):
        """コンテスト情報を取得して保存する"""
        try:
            contests = await self.fetch_contests_from_web()
            if contests:
                self.contests = contests
                self.save_contests(self.contests)
                print("コンテスト情報を更新しました。")
            else:
                print("コンテスト情報の更新に失敗しました。")
        except Exception as e:
            print(f"コンテスト情報の取得中にエラーが発生しました: {e}")
            traceback.print_exc()

    def load_reminders(self) -> Dict:
        """リマインダー設定をYAMLファイルから読み込む"""
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:  # yaml.safe_load() が None を返した場合の処理を追加
                    return {}
                return data
        return {}

    def save_reminders(self, reminders: Dict):
        """リマインダー設定をYAMLファイルに保存する"""
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                reminders,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    def get_a_problem_url(self, contest_url: str) -> str:
        """A問題のURLを生成する"""
        return f"{contest_url}/tasks/{contest_url.split('/')[-1]}_a"

    async def send_reminder(
        self,
        guild_id: int,
        contest: Dict,
        reminder_time: int,
    ):
        """リマインダーを送信する"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.reminders:
            return
        reminder_config = self.reminders[guild_id_str]
        if contest["type"] not in reminder_config:
            return

        contest_type_config = next(
            (
                config
                for config in reminder_config[contest["type"]]
                if config["reminder_time"] == reminder_time and config["enabled"]
            ),
            None,
        )
        if not contest_type_config:
            return

        channel_id = int(reminder_config["reminder_channel_id"])
        channel = self.bot.get_channel(channel_id)
        if not channel:
            print(f"チャンネルが見つかりませんでした: {channel_id}")
            return

        start_time = datetime.datetime.strptime(
            contest["start_time"], "%Y-%m-%d %H:%M:%S"
        )
        end_time = datetime.datetime.strptime(contest["end_time"], "%Y-%m-%d %H:%M:%S")

        # タイムスタンプ形式に変換 (絶対表示用)
        start_timestamp = int(time.mktime(start_time.timetuple()))
        end_timestamp = int(time.mktime(end_time.timetuple()))

        # 相対時間表示用のタイムスタンプ (例: ○分後)
        relative_start_timestamp = int(time.mktime(start_time.timetuple()))

        a_problem_url = self.get_a_problem_url(contest["url"])

        embed = discord.Embed(
            title=f"{contest['name']} リマインダー",
            description=(
                f"**開始:** <t:{start_timestamp}:F> (<t:{relative_start_timestamp}:R>)\n"  # 相対時間表示を追加
                f"**終了:** <t:{end_timestamp}:F>\n"
                f"**時間:** {contest['duration']}\n"
                f"**URL:** {contest['url']}\n"
                f"**A問題:** {a_problem_url}\n"
                f"**Rated範囲:** {contest['rated_range']}\n"
                f"**atcoder-cli用:** ```acc new {contest['url'][-6:]}```\n```cd {contest['url'][-6:]}```"
            ),
            color=discord.Color.blue(),
        )

        role_name = f"{contest['type']}参加勢"
        role = discord.utils.get(channel.guild.roles, name=role_name)
        if role:
            message_content = role.mention
        else:
            # ロールがない場合、作成を試みる
            try:
                role = await channel.guild.create_role(name=role_name)
                message_content = role.mention
                print(f"ロール {role_name} を作成しました。")
            except discord.Forbidden:
                print(f"ロール {role_name} の作成に必要な権限がありません。")
                message_content = f"{contest['type']}参加勢はいませんか？"  # ロール作成失敗時にメンションを諦める
            except Exception as e:
                print(f"ロール {role_name} の作成中にエラーが発生しました: {e}")
                message_content = f"{contest['type']}参加勢はいませんか？"  # ロール作成失敗時にメンションを諦める

        try:
            await channel.send(content=message_content, embed=embed)
            contest_type_config["sent_reminders"].append(contest["name"])
            self.save_reminders(self.reminders)
            print(
                f"リマインダーを送信しました: {contest['name']} ({reminder_time}分前), サーバーID: {guild_id}"
            )

        except discord.Forbidden:
            print(
                f"リマインダー送信に必要な権限がありません: {channel.name} , サーバーID: {guild_id_str}"
            )
        except Exception as e:
            print(f"リマインダーの送信中にエラーが発生しました: {e}")
            traceback.print_exc()

    @tasks.loop(minutes=0.5)
    async def check_reminders(self):
        """設定された時間に基づいてリマインダーを送信する"""
        now = datetime.datetime.now()
        contest_data_cog = self.bot.get_cog("ContestData")  # ContestData Cogを取得
        if not contest_data_cog:
            print("Error: ContestData cog not found!")
            return
        contests = contest_data_cog.contests  # ContestData Cogからコンテスト情報を取得
        if not contests:
            return
        for guild_id, reminder_config in self.reminders.items():
            for contest in contests:  # 変更: self.contests -> contests
                start_time = datetime.datetime.strptime(
                    contest["start_time"], "%Y-%m-%d %H:%M:%S"
                )
                for contest_type, type_configs in reminder_config.items():
                    if contest["type"] == contest_type:
                        for type_config in type_configs:
                            if type_config["enabled"]:
                                reminder_time = type_config["reminder_time"]
                                if isinstance(reminder_time, int):
                                    reminder_time_delta = datetime.timedelta(
                                        minutes=reminder_time
                                    )
                                    reminder_time_dt = start_time - reminder_time_delta
                                    if (
                                        now >= reminder_time_dt
                                        and now
                                        < reminder_time_dt
                                        + datetime.timedelta(minutes=1)
                                        and contest["name"]
                                        not in type_config.get("sent_reminders", [])
                                    ):
                                        await self.send_reminder(
                                            int(guild_id), contest, reminder_time
                                        )

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="reminder---set", description="リマインダー設定")
    async def set_reminder(self, interaction: discord.Interaction):
        """リマインダー設定コマンド"""
        guild_id = str(interaction.guild_id)
        if guild_id not in self.reminders:
            self.reminders[guild_id] = {
                "reminder_channel_id": str(interaction.channel_id),
            }
            for contest_type in CONTEST_TYPES:
                self.reminders[guild_id][contest_type] = []
                self.save_reminders(self.reminders)

        view = ReminderSettingsView(self, guild_id)
        await interaction.response.send_message(  # interaction.response.send_message に変更
            "リマインダー設定", view=view, ephemeral=False
        )

    @app_commands.command(
        name="reminder---set_channel",
        description="リマインダーを送信するチャンネルを設定",
    )
    async def set_reminder_channel(self, interaction: discord.Interaction):
        """リマインダー送信チャンネル設定コマンド"""
        guild_id = str(interaction.guild_id)
        view = ChannelSelectView(self, guild_id)  # ChannelSelectView を使用
        await interaction.response.send_message(
            "リマインダー送信チャンネルを選択してください", view=view, ephemeral=False
        )

    @app_commands.command(
        name="reminder---show", description="現在設定されているリマインダーを表示"
    )
    async def show_reminder(self, interaction: discord.Interaction):
        """Displays the currently configured reminders for the server."""
        guild_id = str(interaction.guild_id)

        if guild_id not in self.reminders or not self.reminders[guild_id]:
            await interaction.response.send_message(
                "このサーバーにはリマインダーが設定されていません。", ephemeral=False
            )
            return

        reminder_config = self.reminders[guild_id]
        embed = discord.Embed(title="リマインダー設定", color=discord.Color.blue())

        channel_id = reminder_config.get("reminder_channel_id")
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                embed.add_field(
                    name="通知チャンネル",
                    value=channel.mention,
                    inline=False,
                )
            else:
                embed.add_field(
                    name="通知チャンネル",
                    value=f"不明なチャンネル (ID: {channel_id})",
                    inline=False,
                )

        for contest_type in CONTEST_TYPES:
            if contest_type in reminder_config:
                type_configs = reminder_config[contest_type]
                if type_configs:
                    reminder_times_str_list = []  # リマインダー時間文字列のリストを初期化
                    unique_reminder_times = set()  # setで重複を排除
                    for config in type_configs:
                        if config["enabled"]:
                            reminder_time = config["reminder_time"]
                            if isinstance(
                                reminder_time, list
                            ):  # reminder_time がリストの場合
                                for t in reminder_time:
                                    unique_reminder_times.add(t)  # setに追加
                            elif isinstance(
                                reminder_time, int
                            ):  # reminder_time が整数の場合
                                unique_reminder_times.add(reminder_time)  # setに追加

                    for reminder_time in sorted(
                        list(unique_reminder_times)
                    ):  # setからリストに変換してソート
                        reminder_times_str_list.append(
                            f"{reminder_time}分前"
                        )  # "X分前" 形式に

                    if reminder_times_str_list:
                        reminder_times_str = ", ".join(
                            reminder_times_str_list
                        )  # リストを結合して最終的な文字列を作成
                        embed.add_field(
                            name=contest_type,
                            value=reminder_times_str,
                            inline=False,
                        )
        await interaction.response.send_message(embed=embed, ephemeral=False)


class ReminderSettingsView(View):
    def __init__(self, cog: Reminder, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.reminder_data = self.cog.reminders.get(self.guild_id, {})
        self.add_item(self.create_contest_type_select())

    def create_contest_type_select(self) -> Select:
        """コンテストタイプ選択メニューを作成する"""
        options = [
            discord.SelectOption(label=contest_type, value=contest_type)
            for contest_type in CONTEST_TYPES
        ]
        select = Select(
            placeholder="コンテストタイプを選択",
            options=options,
            custom_id="contest_type_select",
        )
        select.callback = self.contest_type_select_callback
        return select

    def create_channel_button(self) -> Button:
        """チャンネル設定ボタンを作成する"""
        button = Button(
            label="チャンネル設定",
            style=discord.ButtonStyle.primary,
            custom_id="channel_button",
        )
        button.callback = self.channel_button_callback
        return button

    async def contest_type_select_callback(self, interaction: discord.Interaction):
        """コンテストタイプが選択されたときのコールバック"""
        contest_type = interaction.data["values"][0]
        view = ContestTypeSettingsView(self.cog, self.guild_id, contest_type)
        await interaction.response.edit_message(
            content=f"{contest_type} のリマインダー設定", view=view
        )


class ContestTypeSettingsView(View):
    def __init__(self, cog: Reminder, guild_id: str, contest_type: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.contest_type = contest_type
        self.reminder_data = self.cog.reminders.get(self.guild_id, {}).get(
            self.contest_type, []
        )
        self.add_item(self.create_reminder_time_select())
        self.add_item(self.create_cancel_button())
        self.add_item(self.create_enabled_button())

    def create_reminder_time_select(self) -> Select:
        """通知時間選択メニューを作成する"""
        options = [
            discord.SelectOption(label=time, value=time) for time in REMINDER_TIMES
        ]
        # 選択済みの時間をハイライト
        default_values = [
            option.value
            for option in options
            if option.value != "カスタム設定"
            and any(
                config["reminder_time"] == TIME_MAPPING.get(option.value)
                for config in self.reminder_data
            )
        ]

        select = Select(
            placeholder="通知時間を選択",
            options=options,
            custom_id="reminder_time_select",
            max_values=len(REMINDER_TIMES)
            - 1,  # カスタム設定以外すべて選択できるようにする
        )

        # カスタム設定のデフォルト値を設定
        if any(
            isinstance(config["reminder_time"], list) for config in self.reminder_data
        ):
            default_values.append("カスタム設定")

        select.callback = self.reminder_time_select_callback

        # 選択済みのオプションにチェックマークを追加
        for option in select.options:
            if option.value in default_values:
                option.default = True

        return select

    def create_cancel_button(self) -> Button:
        """キャンセルボタンを作成する"""
        button = Button(
            label="キャンセル",
            style=discord.ButtonStyle.secondary,
            custom_id="cancel_button",
        )
        button.callback = self.cancel_button_callback
        return button

    def create_enabled_button(self) -> Button:
        """有効/無効ボタンを作成する"""
        is_enabled = self.is_enabled()
        button = Button(
            label="リマインダーを無効化" if is_enabled else "リマインダーを有効化",
            style=discord.ButtonStyle.success
            if is_enabled
            else discord.ButtonStyle.danger,
            custom_id="enabled_button",
        )
        button.callback = self.enabled_button_callback
        return button

    def is_enabled(self) -> bool:
        """現在の設定が有効かどうかを返す"""
        return any(config["enabled"] for config in self.reminder_data)

    async def reminder_time_select_callback(self, interaction: discord.Interaction):
        """通知時間が選択されたときのコールバック"""
        selected_times = interaction.data["values"]
        if "カスタム設定" in selected_times:
            modal = CustomTimeModal(self.cog, self.guild_id, self.contest_type)
            await interaction.response.send_modal(modal)
        else:
            reminder_times = [
                TIME_MAPPING.get(time)
                for time in selected_times
                if time != "カスタム設定"
            ]
            self.update_reminder_config(reminder_times)
            times_str = ", ".join(
                [time for time in selected_times if time != "カスタム設定"]
            )
            embed = discord.Embed(
                title=f"**{self.contest_type}** リマインダー設定完了！",
                description=f"{self.contest_type} のリマインダーを {times_str} に設定しました！",
                color=discord.Color.green(),  # Embedの色はお好みで設定
            )
            await interaction.response.edit_message(  # interaction.response.edit_message で編集
                content=None,  # content を None にして Embed を送信
                view=None,  # view を None にしてボタンなどを削除
                embed=embed,  # Embed を設定
            )
            self.cog.save_reminders(self.cog.reminders)

    def update_reminder_config(self, reminder_times: List[int]):
        """リマインダー設定を更新する (setで管理)"""
        unique_reminder_times = set()  # setで重複を排除
        reminder_data = []  # 新しい reminder_data を作成

        # 新しい設定を追加 (重複を排除しながら set に追加)
        for reminder_time in reminder_times:
            unique_reminder_times.add(reminder_time)

        # set からリストに戻して reminder_data を作成
        for reminder_time in sorted(
            list(unique_reminder_times)
        ):  # set をリストに変換してソート
            reminder_data.append(
                {"reminder_time": reminder_time, "enabled": True, "sent_reminders": []}
            )

        self.cog.reminders[self.guild_id][self.contest_type] = reminder_data

    async def cancel_button_callback(self, interaction: discord.Interaction):
        """キャンセルボタンが押されたときのコールバック"""
        view = ReminderSettingsView(self.cog, self.guild_id)
        await interaction.response.edit_message(content="リマインダー設定", view=view)

    async def enabled_button_callback(self, interaction: discord.Interaction):
        """有効/無効ボタンが押されたときのコールバック"""
        if not self.reminder_data:
            self.reminder_data.append(
                {"reminder_time": 30, "enabled": True, "sent_reminders": []}
            )
            self.cog.reminders[self.guild_id][self.contest_type] = self.reminder_data
        else:
            for config in self.reminder_data:
                config["enabled"] = not config["enabled"]
                if "sent_reminders" not in config:
                    config["sent_reminders"] = []
        self.cog.save_reminders(self.cog.reminders)
        is_enabled = self.is_enabled()
        self.children[2].label = "有効" if is_enabled else "無効"
        self.children[2].style = (
            discord.ButtonStyle.success if is_enabled else discord.ButtonStyle.danger
        )
        await interaction.response.edit_message(
            content=f"{self.contest_type} のリマインダー設定",
            view=self,
        )

    async def reminder_time_select_callback(self, interaction: discord.Interaction):
        """通知時間が選択されたときのコールバック"""
        selected_times = interaction.data["values"]
        if "カスタム設定" in selected_times:
            modal = CustomTimeModal(self.cog, self.guild_id, self.contest_type)
            await interaction.response.send_modal(modal)
        else:
            reminder_times = [
                TIME_MAPPING.get(time)
                for time in selected_times
                if time != "カスタム設定"
            ]
            self.update_reminder_config(reminder_times)
            times_str = ", ".join(
                [time for time in selected_times if time != "カスタム設定"]
            )
            embed = discord.Embed(
                title=f"**{self.contest_type}** リマインダー設定完了！",
                description=f"{self.contest_type} のリマインダーを {times_str} に設定しました！",
                color=discord.Color.green(),  # Embedの色はお好みで設定
            )
            await interaction.response.edit_message(  # interaction.response.edit_message で編集
                content=None,  # content を None にして Embed を送信
                view=None,  # view を None にしてボタンなどを削除  <- こちらのみ残す
                embed=embed,  # Embed を設定
            )
            self.cog.save_reminders(self.cog.reminders)


class CustomTimeModal(discord.ui.Modal, title="カスタム通知時間設定"):
    custom_time = discord.ui.TextInput(
        label="通知時間 (分単位, 空白区切りで複数)",
        placeholder="例: 5 10 30",
        required=True,
    )

    def __init__(self, cog: Reminder, guild_id: str, contest_type: str):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.contest_type = contest_type

    async def on_submit(self, interaction: discord.Interaction):
        """モーダルが送信されたときのコールバック"""
        try:
            times = [int(time) for time in self.custom_time.value.split()]
            self.update_reminder_config(times)
            times_str = ", ".join([f"{time}分前" for time in times])
            embed = discord.Embed(
                title=f"**{self.contest_type}** リマインダー設定完了！",
                description=f"{self.contest_type} のカスタムリマインダーを {times_str} に設定しました！",
                color=discord.Color.green(),  # Embedの色はお好みで設定
            )
            await interaction.response.edit_message(  # interaction.response.edit_message で編集
                content=None,  # content を None にして Embed を送信
                view=None,  # view を None にしてボタンなどを削除  <- こちらのみ残す
                embed=embed,  # Embed を設定
            )
            self.cog.save_reminders(self.cog.reminders)
        except ValueError:
            await interaction.response.send_message(
                "無効な入力です。半角数字で空白区切りで入力してください。",
                ephemeral=False,
            )
        except Exception as e:
            print(f"カスタム通知時間設定中にエラーが発生しました: {e}")
            traceback.print_exc()

    def update_reminder_config(self, times: List[int]):
        """カスタム時間設定を保存する (setで管理)"""
        unique_reminder_times = set()  # setで重複を排除
        reminder_data = self.cog.reminders.get(self.guild_id, {}).get(
            self.contest_type, []
        )
        existing_times = set()  # 既存の時間を set に格納
        for config in reminder_data:
            if isinstance(config["reminder_time"], list):
                for t in config["reminder_time"]:
                    existing_times.add(t)
            elif isinstance(config["reminder_time"], int):
                existing_times.add(config["reminder_time"])

        # 既存の設定と新しい設定を合わせて set に追加 (重複を排除)
        for time in existing_times:
            unique_reminder_times.add(time)
        for time in times:
            unique_reminder_times.add(time)

        reminder_data = []  # 新しい reminder_data を作成
        # set からリストに戻して reminder_data を作成
        for reminder_time in sorted(
            list(unique_reminder_times)
        ):  # set をリストに変換してソート
            reminder_data.append(
                {"reminder_time": reminder_time, "enabled": True, "sent_reminders": []}
            )
        self.cog.reminders[self.guild_id][self.contest_type] = reminder_data


class ChannelSelectView(View):  # ChannelSelect 用の View を作成
    def __init__(self, cog: Reminder, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.add_item(self.create_channel_select())

    def create_channel_select(self) -> ChannelSelect:
        """チャンネル選択メニューを作成する"""
        channel_select = ChannelSelect(
            channel_types=[discord.ChannelType.text],
            custom_id="reminder_channel_select",
        )
        channel_select.callback = self.channel_select_callback
        return channel_select

    async def channel_select_callback(self, interaction: discord.Interaction):
        """チャンネルが選択されたときのコールバック"""
        channel = interaction.data["values"][0]  # 選択されたチャンネルIDを取得
        self.cog.reminders[self.guild_id]["reminder_channel_id"] = str(channel)
        self.cog.save_reminders(self.cog.reminders)
        channel_mention = f"<#{channel}>"  # チャンネルメンションを作成
        embed = discord.Embed(
            title="リマインダーチャンネル設定完了！",
            description=f"リマインダー送信チャンネルを {channel_mention} に設定しました！",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, view=None, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Reminder(bot))
