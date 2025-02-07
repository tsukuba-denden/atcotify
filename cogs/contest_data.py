import asyncio
import datetime
import os
import traceback
import random

import aiohttp
import yaml
from bs4 import BeautifulSoup
from discord.ext import commands, tasks
from env.config import Config

CONTESTS_FILE = "asset/contests.yaml"
ATCODER_CONTESTS_URL = "https://atcoder.jp/contests/"

# 複数の User-Agent をリストで定義
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:96.0) Gecko/20100101 Firefox/96.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
]

class ContestData(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.fetch_contests.start()  # タスクを初期化時に開始
        self.contests = self.load_contests()

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

    async def fetch_contests_from_web(self) -> list[dict]:
        """AtCoderのウェブサイトからコンテスト情報をスクレイピングする"""
        headers = {
            "User-Agent": random.choice(USER_AGENTS)  # ランダムにUser-Agentを選択
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(ATCODER_CONTESTS_URL, timeout=10) as response:
                try:
                    response.raise_for_status()  # ステータスコードが200番台でない場合に例外を発生
                    html = await response.text()
                except aiohttp.ClientResponseError as e:
                    print(f"AtCoderへのリクエストエラー: {e.status} {e.message}")
                    return []
                except asyncio.TimeoutError:
                    print("AtCoderへのリクエストがタイムアウトしました")
                    return []
                except Exception as e:
                    print(f"AtCoderからの情報取得中に予期せぬエラーが発生: {e}")
                    traceback.print_exc()
                    return []

        soup = BeautifulSoup(html, "html.parser")
        contests = []

        upcoming_contests_table = soup.find(id="contest-table-upcoming")
        if upcoming_contests_table:
            table = upcoming_contests_table.find("table")
            if table:
                for row in table.find("tbody").find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) == 4:
                        start_time_str = cells[0].find("time").text
                        start_time_str = start_time_str.split("+")[0]
                        start_time = datetime.datetime.strptime(
                            start_time_str, "%Y-%m-%d %H:%M:%S"
                        )
                        contest_name = cells[1].find("a").text
                        duration_str = cells[2].text
                        rated_range = cells[3].text.strip()
                        contest_url = cells[1].find("a")["href"]
                        contest_type = self.extract_contest_type(cells[1])

                        if contest_type:
                            end_time = start_time + self.parse_duration(duration_str)

                            contests.append(
                                {
                                    "name": contest_name,
                                    "start_time": start_time.strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                    "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "duration": duration_str,
                                    "type": contest_type,
                                    "url": f"https://atcoder.jp{contest_url}",
                                    "rated_range": rated_range,
                                    "threads_created": False,  # スレッド作成フラグを初期化
                                }
                            )

        return contests

    def extract_contest_type(self, cell) -> str | None:
        """コンテストタイプを抽出する"""
        contest_type_span = cell.find("span", {"aria-hidden": "true"})
        if not contest_type_span:
            return None
        title = contest_type_span.get("title", "")
        if title == "Algorithm":
            if "Beginner" in cell.text:
                return "ABC"
            elif "Regular" in cell.text:
                return "ARC"
            elif "Grand" in cell.text:
                return "AGC"
        elif title == "Heuristic":
            return "AHC"
        return None

    def parse_duration(self, duration_str: str) -> datetime.timedelta:
        """コンテスト時間文字列をtimedeltaオブジェクトに変換する"""
        hours, minutes = map(int, duration_str.split(":"))
        return datetime.timedelta(hours=hours, minutes=minutes)

    @tasks.loop(hours=24)
    async def fetch_contests(self):
        """定期的にコンテスト情報を取得・更新する"""
        contests = await self.fetch_contests_from_web()
        if contests:
            self.contests = contests
            self.save_contests(self.contests)
            print("コンテスト情報を更新しました。")
        else:
            print("コンテスト情報の更新に失敗しました。")

    @fetch_contests.before_loop
    async def before_fetch_contests(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ContestData(bot))
