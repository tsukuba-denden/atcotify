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
        """AtCoderのコンテスト情報をYAMLファイルから取得する"""
        headers = {
            "User-Agent": random.choice(USER_AGENTS)  # ランダムにUser-Agentを選択
        }
        new_url = "https://github.com/tsukuba-denden/atcoder-contest-info/raw/refs/heads/main/contests.yaml"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(new_url, timeout=10) as response:
                try:
                    response.raise_for_status()  # ステータスコードが200番台でない場合に例外を発生
                    yaml_text = await response.text()
                except aiohttp.ClientResponseError as e:
                    print(f"YAMLファイル取得エラー: {e.status} {e.message}")
                    return []
                except asyncio.TimeoutError:
                    print("YAMLファイル取得リクエストがタイムアウトしました")
                    return []
                except Exception as e:
                    print(f"YAMLファイル取得中に予期せぬエラーが発生: {e}")
                    traceback.print_exc()
                    return []

        try:
            contests = yaml.safe_load(yaml_text)
            return contests if contests is not None else []
        except yaml.YAMLError as e:
            print(f"YAMLパースエラー: {e}")
            traceback.print_exc()
            return []

    def _determine_contest_type(self, name: str) -> str:
        """コンテスト名からタイプを判定する"""
        name_upper = name.upper()
        if "BEGINNER CONTEST" in name_upper or "ABC" in name_upper:
            return "ABC"
        elif "REGULAR CONTEST" in name_upper or "ARC" in name_upper:
            return "ARC"
        elif "GRAND CONTEST" in name_upper or "AGC" in name_upper:
            return "AGC"
        elif "HEURISTIC CONTEST" in name_upper or "AHC" in name_upper:
            return "AHC"
        return "Other"

    @tasks.loop(hours=24)
    async def fetch_contests(self):
        """定期的にコンテスト情報を取得・更新し、指定された形式に変換する"""
        raw_contests = await self.fetch_contests_from_web()
        if raw_contests:
            transformed_contests = []
            for item in raw_contests:
                try:
                    name = item.get("name_en") or item.get("name_ja", "Unknown Contest")

                    # start_time (ISO 8601 to "YYYY-MM-DD HH:MM:SS")
                    # Python 3.11+ fromisoformat handles +09:00 directly.
                    # For older versions, one might need to strip it manually if not supported.
                    start_time_dt = datetime.datetime.fromisoformat(item["start_time"])
                    # Convert to naive datetime in local time for formatting
                    start_time_formatted = start_time_dt.replace(tzinfo=None).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    duration_min = int(item.get("duration_min", 0))

                    # end_time
                    end_time_dt = start_time_dt + datetime.timedelta(
                        minutes=duration_min
                    )
                    end_time_formatted = end_time_dt.replace(tzinfo=None).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    # duration ("HH:MM")
                    hours, remainder_minutes = divmod(duration_min, 60)
                    duration_formatted = f"{int(hours):02d}:{int(remainder_minutes):02d}"

                    contest_type = self._determine_contest_type(name)

                    transformed_contests.append(
                        {
                            "name": name,
                            "start_time": start_time_formatted,
                            "end_time": end_time_formatted,
                            "duration": duration_formatted,
                            "type": contest_type,
                            "url": item.get("url", ""),
                            "rated_range": item.get("rated_range", ""),
                            "threads_created": False,
                        }
                    )
                except Exception as e:
                    print(f"コンテスト情報の変換中にエラーが発生: {item.get('name_ja', 'N/A')} - {e}")
                    traceback.print_exc()
                    continue # Skip this contest if there's an error

            self.contests = transformed_contests
            self.save_contests(self.contests)
            print(f"{len(transformed_contests)}件のコンテスト情報を更新・保存しました。")
        else:
            print("コンテスト情報の取得に失敗したため、更新できませんでした。")

    @fetch_contests.before_loop
    async def before_fetch_contests(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ContestData(bot))
