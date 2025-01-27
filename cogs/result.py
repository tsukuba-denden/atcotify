import datetime
import os
import traceback
from typing import Dict, List
import aiohttp
import discord
import yaml
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, Select, View, ChannelSelect
from env.config import Config
import time
import requests
import urllib.parse
import re
from time import sleep

CONTESTS_FILE = "asset/contests.yaml"
REMINDERS_FILE = "asset/reminders.yaml"
RESULTS_FILE = "asset/results.yaml"
ATCODER_CONTESTS_URL = "https://atcoder.jp/contests/"

config = Config()
ATCODER_USERNAME = config.config["ATCODER"][
    "ATCODER_USERNAME"
]  # config.iniからAtCoderのユーザー名を取得
ATCODER_PASSWORD = config.config["ATCODER"][
    "ATCODER_PASSWORD"
]  # config.iniからAtCoderのパスワードを取得


def login():
    """AtCoder にログインし、セッションを返す"""
    print("ログイン中…")
    login_url = "https://atcoder.jp/login"
    session = requests.session()
    res = session.get(login_url)
    revel_session = res.cookies.get_dict().get("REVEL_SESSION")

    if revel_session:
        revel_session = urllib.parse.unquote(revel_session)
        csrf_token_match = re.search(r"csrf_token\:(.*)_TS", revel_session)
        if csrf_token_match:
            csrf_token = csrf_token_match.groups()[0].replace("\x00\x00", "")
            sleep(1)
            headers = {"content-type": "application/x-www-form-urlencoded"}
            params = {
                "username": ATCODER_USERNAME,
                "password": ATCODER_PASSWORD,
                "csrf_token": csrf_token,
            }
            data = {"continue": "https://atcoder.jp:443/home"}
            res = session.post(login_url, params=params, data=data, headers=headers)
        try:
            res.raise_for_status()
            return session
        except requests.exceptions.HTTPError as e:
            print(f"ログインエラー: {e}")
            return None
    else:
        print("Error: REVEL_SESSION cookie not found")
    return None  # ログイン失敗


def get_task_list(contest_id):
    """コンテストのタスクリストを取得する"""
    url = f"https://atcoder.jp/contests/{contest_id}/tasks"
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    tasks = []
    task_table = soup.find("table", {"class": "table table-bordered table-striped"})
    if task_table:
        task_links = task_table.find_all("a")
        for link in task_links:
            task_url = link.get("href")
            if task_url and "/tasks/" in task_url:
                task_id = task_url.split("/")[-1]
                if "_" in task_id:
                    tasks.append(
                        task_id.split("_")[-1].upper()
                    )  # タスクIDを大文字に変換
    return tasks


def get_latest_atcoder_results(contest_id):
    """最新の AtCoder コンテスト結果を取得する"""
    session = login()
    if session is None:  # ログイン失敗時の処理を追加
        return None
    print("ログイン完了")

    url = f"https://atcoder.jp/contests/{contest_id}/standings/json"
    response = session.get(url)
    response.raise_for_status()
    data = response.json()

    results = []
    dennoh_rank = 1
    for row in data["StandingsData"]:
        affiliation = row.get("Affiliation")
        if affiliation and "電子電脳技術研究会" in affiliation:
            user_name = row["UserScreenName"]
            rank = f"{dennoh_rank} ({row['Rank']})"
            total_score = row["TotalResult"]["Score"] / 100
            rating_change = f"{row.get('OldRating', '')} → {row.get('Rating', '')} ({row.get('Rating', 0) - row.get('OldRating', 0)})"
            task_results = row.get("TaskResults", {})

            task_data = []
            for task in get_task_list(contest_id):
                task_result = task_results.get(task)
                if task_result:
                    count = task_result["Count"]
                    penalty = task_result["Penalty"]
                    failure = task_result["Failure"]  # Failure を取得
                    if task_result["Score"] >= 1:
                        score = task_result["Score"] // 100
                        task_data.append(
                            f"{score} ({penalty})" if penalty > 0 else f"{score}"
                        )
                    elif task_result["Score"] == 0:  # Score が 0 の場合
                        task_data.append(f"({failure + penalty})")
                        print("スコア0だった", failure, penalty)
                    else:
                        task_data.append(f"({penalty})")
                else:
                    task_data.append("-")

            results.append([rank, user_name, total_score] + task_data + [rating_change])
            dennoh_rank += 1
    return results


class Result(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.results_config = (
            self.load_results_config()
        )  # 送信済みコンテストIDの読み込み
        self.check_contest_results.start()  # 定期的にコンテスト結果をチェックするタスクを開始

    def load_results_config(self) -> List[str]:
        """送信済みコンテストIDをYAMLファイルから読み込む"""
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:
                    return []
                return data
        return []

    def save_results_config(self, results_config: List[str]):
        """送信済みコンテストIDをYAMLファイルに保存する"""
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                results_config,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    @app_commands.command(
        name="send_result", description="指定されたコンテストIDの結果を手動で送信します"
    )
    async def send_result_command(
        self, interaction: discord.Interaction, contest_id: str
    ):
        """コンテスト結果送信コマンド"""
        await (
            interaction.response.defer()
        )  # interaction.response.defer() で処理を遅延させる
        channel_id = self.get_result_channel_id(interaction.guild_id)
        if not channel_id:
            await interaction.followup.send(
                "結果送信チャンネルが設定されていません。/set_result_channel で設定してください。",
                ephemeral=True,
            )
            return
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            await interaction.followup.send(
                f"指定されたチャンネルが見つかりません。チャンネルID: {channel_id}",
                ephemeral=True,
            )
            return

        await self.send_contest_result(contest_id, channel)
        await interaction.followup.send(
            f"コンテスト {contest_id} の結果を送信しました。", ephemeral=True
        )

    async def send_contest_result(self, contest_id, channel):
        """コンテスト結果を送信する"""
        results = get_latest_atcoder_results(contest_id)
        if results is None:  # AtCoderログインに失敗した場合
            await channel.send(
                f"コンテスト {contest_id} の結果取得に失敗しました。AtCoderへのログインに失敗した可能性があります。"
            )
            return
        if not results:
            await channel.send(
                f"コンテスト {contest_id} の結果が見つかりませんでした。"
            )
            return

        embed = discord.Embed(
            title=f"AtCoder コンテスト結果 ({contest_id})", color=discord.Color.blue()
        )
        output = ""
        header = "| 順位 | ユーザー名 | 合計 |"
        task_header = ""
        tasks = get_task_list(contest_id)
        for task in tasks:
            task_header += f" {task} |"
        header += task_header + " Rating変動 |\n"
        header += "|:---:|:---|:---:|"
        for _ in tasks:
            header += ":---:|"
        header += ":---:|\n"
        output += header

        for row in results:
            rank, user_name, total_score, *task_scores, rating_change = row
            row_str = f"| {rank} | {user_name} | {total_score} |"
            for task_score in task_scores:
                row_str += f" {task_score} |"
            row_str += f" {rating_change} |\n"
            output += row_str

        embed.description = (
            f"```markdown\n{output}\n```"  # code block + markdown tableで表示
        )
        await channel.send(embed=embed)
        self.results_config.append(contest_id)  # 送信済みコンテストIDリストに追加
        self.save_results_config(self.results_config)  # results.yamlに保存

    def get_result_channel_id(self, guild_id: int) -> str or None:
        """結果送信チャンネルIDを取得する"""
        guild_id_str = str(guild_id)
        reminders = self.load_reminders()  # reminders.yamlから設定を読み込む
        if guild_id_str in reminders and "result_channel_id" in reminders[guild_id_str]:
            return reminders[guild_id_str]["result_channel_id"]
        return None

    def load_reminders(self) -> Dict:
        """リマインダー設定をYAMLファイルから読み込む (reminder.pyからコピー)"""
        if os.path.exists(REMINDERS_FILE):
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:  # yaml.safe_load() が None を返した場合の処理を追加
                    return {}
                return data
        return {}

    def save_reminders(self, reminders: Dict):
        """リマインダー設定をYAMLファイルに保存する (reminder.pyからコピー)"""
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                reminders,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    @app_commands.command(
        name="set_result_channel",
        description="コンテスト結果を送信するチャンネルを設定",
    )
    async def set_result_channel(self, interaction: discord.Interaction):
        """コンテスト結果送信チャンネル設定コマンド"""
        guild_id = str(interaction.guild_id)
        view = ResultChannelSelectView(self, guild_id)  # ChannelSelectView を使用
        await interaction.response.send_message(
            "コンテスト結果送信チャンネルを選択してください", view=view, ephemeral=False
        )

    @tasks.loop(minutes=1)  # 1分おきにコンテスト終了時刻を確認
    async def check_contest_results(self):
        """定期的にコンテスト終了時刻を確認し、結果を送信する"""
        now = datetime.datetime.now()
        contests = self.load_contests()  # contests.yamlからコンテスト情報を読み込む
        if not contests:
            return

        for contest in contests:
            if contest["type"] == "AHC":  # AHCは対象外
                continue
            contest_id = contest["url"].split("/")[-1]
            if contest_id in self.results_config:  # 送信済みコンテストはスキップ
                continue

            end_time = datetime.datetime.strptime(
                contest["end_time"], "%Y-%m-%d %H:%M:%S"
            )
            if now >= end_time:  # コンテスト終了時刻になったら
                print(
                    f"コンテスト {contest['name']} が終了しました。結果を送信します。"
                )
                for guild_id in (
                    self.get_guilds_with_result_channel()
                ):  # 結果送信チャンネルが設定されているサーバーを取得
                    channel_id = self.get_result_channel_id(guild_id)
                    if channel_id:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            await self.send_contest_result(
                                contest_id, channel
                            )  # コンテスト結果を送信
                            print(
                                f"コンテスト {contest['name']} の結果をサーバー {guild_id} に送信しました。"
                            )
                        else:
                            print(
                                f"結果送信チャンネルが見つかりませんでした。サーバーID: {guild_id}, チャンネルID: {channel_id}"
                            )

    def get_guilds_with_result_channel(self) -> List[int]:
        """結果送信チャンネルが設定されているサーバーIDのリストを取得する"""
        guild_ids = []
        reminders = self.load_reminders()
        for guild_id_str, reminder_config in reminders.items():
            if "result_channel_id" in reminder_config:
                guild_ids.append(int(guild_id_str))
        return guild_ids

    def load_contests(self) -> List[Dict]:
        """コンテスト情報をYAMLファイルから読み込む (reminder.pyからコピー)"""
        if os.path.exists(CONTESTS_FILE):
            with open(CONTESTS_FILE, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        return []

    @check_contest_results.before_loop
    async def before_check_contest_results(self):
        await self.bot.wait_until_ready()


class ResultChannelSelectView(
    View
):  # ChannelSelect 用の View を作成 (reminder.pyからコピー)
    def __init__(self, cog: Result, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.add_item(self.create_channel_select())

    def create_channel_select(self) -> ChannelSelect:
        """チャンネル選択メニューを作成する (reminder.pyからコピー)"""
        channel_select = ChannelSelect(
            channel_types=[discord.ChannelType.text],
            custom_id="result_channel_select",
        )
        channel_select.callback = self.channel_select_callback
        return channel_select

    async def channel_select_callback(self, interaction: discord.Interaction):
        """チャンネルが選択されたときのコールバック (reminder.pyからコピー)"""
        channel = interaction.data["values"][0]  # 選択されたチャンネルIDを取得
        reminders = self.cog.load_reminders()
        if self.guild_id not in reminders:
            reminders[self.guild_id] = {}
        reminders[self.guild_id]["result_channel_id"] = str(channel)
        self.cog.save_reminders(reminders)
        channel_mention = f"<#{channel}>"  # チャンネルメンションを作成
        embed = discord.Embed(
            title="コンテスト結果送信チャンネル設定完了！",
            description=f"コンテスト結果送信チャンネルを {channel_mention} に設定しました！",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, view=None, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Result(bot))
