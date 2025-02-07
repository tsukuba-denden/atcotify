import asyncio
import datetime
import os
import time
import traceback
from typing import Dict, List

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks

from env.config import Config

config = Config()

CONTESTS_FILE = "asset/contests.yaml"
REMINDERS_FILE = "asset/reminders.yaml"  # 既存のリマインダー設定ファイルも使用


class ContestThreads(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_for_threads.start()

    def load_contests(self) -> List[Dict]:
        """コンテスト情報をYAMLファイルから読み込む"""
        if os.path.exists(CONTESTS_FILE):
            with open(CONTESTS_FILE, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return []

    def load_reminders(self) -> Dict:  # リマインダー設定を読み込む関数も追加
        """リマインダー設定をYAMLファイルから読み込む"""
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:
                    return {}
                return data
        return {}

    def save_contests(self, contests: List[Dict]):
        """コンテスト情報をYAMLファイルに保存する"""
        with open(CONTESTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                contests,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    @tasks.loop(minutes=1)
    async def check_for_threads(self):
        """1時間前にスレッドを作成する"""
        contests = self.load_contests()
        if not contests:
            return

        reminders = self.load_reminders()
        now = datetime.datetime.now()

        for contest in contests:
            # contests.yaml に threads_created が存在しない場合、追加 (初回起動時など)
            if "threads_created" not in contest:
                contest["threads_created"] = False

            if contest["threads_created"]:  # 既にスレッド作成済みの場合はスキップ
                continue

            start_time = datetime.datetime.strptime(
                contest["start_time"], "%Y-%m-%d %H:%M:%S"
            )
            time_until_start = start_time - now

            if (
                datetime.timedelta(hours=0, minutes=59)
                <= time_until_start
                <= datetime.timedelta(hours=1)
            ):
                # スレッド作成処理 (サーバーIDとチャンネルIDを取得)
                for guild_id_str, reminder_config in reminders.items():
                    try:
                        guild_id = int(guild_id_str)
                        # channel_id が存在するかチェックし、存在しない場合は処理しない。
                        if (
                            "reminder_channel_id" not in reminder_config
                            or not reminder_config["reminder_channel_id"]
                        ):
                            print(
                                f"reminder_channel_id が設定されていません。 サーバーID: {guild_id}"
                            )
                            continue
                        channel_id = int(reminder_config["reminder_channel_id"])

                        try:
                            channel = self.bot.get_channel(channel_id)
                            if not channel:
                                print(
                                    f"チャンネルが見つかりませんでした: {channel_id} サーバーID: {guild_id}"
                                )
                                continue

                            if not isinstance(channel, discord.TextChannel):
                                print(
                                    f"チャンネルがテキストチャンネルではありません: {channel_id}"
                                )
                                continue

                            # スレッド名の作成 (例: "ABC389")
                            thread_name = contest["url"].split("/")[-1].upper()

                            # スレッド作成
                            thread = await channel.create_thread(
                                name=thread_name, auto_archive_duration=1440
                            )

                            await thread.send(
                                f"{contest['name']} のスレッドが作成されました！"
                            )
                            print(f"スレッド {thread_name} を作成しました。")

                            # スレッド作成済みフラグを立てる (contests.yaml を更新)
                            contest["threads_created"] = True
                            self.save_contests(contests)

                        except discord.Forbidden:
                            print(f"スレッド作成権限がありません: {channel_id}")
                        except discord.HTTPException as e:
                            print(f"スレッド作成中にHTTPエラーが発生しました: {e}")
                        except Exception as e:
                            print(f"スレッド作成中に予期せぬエラーが発生しました: {e}")
                            traceback.print_exc()

                    except ValueError:
                        print(f"無効なサーバーIDです: {guild_id_str}")

    @check_for_threads.before_loop
    async def before_check_for_threads(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ContestThreads(bot))
