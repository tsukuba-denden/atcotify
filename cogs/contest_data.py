import asyncio
import datetime # Ensure this is imported
import os
import traceback
import random

import aiohttp
import yaml
# from bs4 import BeautifulSoup # Removed
from discord.ext import commands, tasks
from discord import app_commands # Added for slash command
import discord # Added for Embed
from env.config import Config

CONTESTS_FILE = "asset/contests.yaml"
# ATCODER_CONTESTS_URL = "https://atcoder.jp/contests/" # Removed

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
        self.fetch_contests.start()
        self.contests = self.load_contests()

    def load_contests(self) -> list[dict]:
        if os.path.exists(CONTESTS_FILE):
            with open(CONTESTS_FILE, "r", encoding="utf-8") as f:
                contests_yaml = yaml.safe_load(f)
                return contests_yaml if contests_yaml is not None else []
        return []

    def save_contests(self, contests_to_save: list[dict]):
        with open(CONTESTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                contests_to_save,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    async def fetch_contests_from_web(self) -> list[dict]:
        headers = {
            "User-Agent": random.choice(USER_AGENTS)
        }
        new_url = "https://github.com/tsukuba-denden/atcoder-contest-info/raw/refs/heads/main/contests.yaml"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(new_url, timeout=10) as response:
                try:
                    response.raise_for_status()
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
            contests_from_yaml = yaml.safe_load(yaml_text)
            return contests_from_yaml if contests_from_yaml is not None else []
        except yaml.YAMLError as e:
            print(f"YAMLパースエラー: {e}")
            traceback.print_exc()
            return []

    def _determine_contest_type(self, name: str) -> str:
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
        raw_contests = await self.fetch_contests_from_web()
        if raw_contests:
            transformed_contests = []
            jst = datetime.timezone(datetime.timedelta(hours=9))
            for item in raw_contests:
                try:
                    name = item.get("name_en") or item.get("name_ja", "Unknown Contest")

                    # item["start_time"] is ISO 8601 string e.g. "2024-07-27T21:00:00+09:00"
                    start_time_dt_aware = datetime.datetime.fromisoformat(item["start_time"])

                    start_time_jst = start_time_dt_aware.astimezone(jst)
                    start_time_formatted_str = start_time_jst.strftime("%Y-%m-%d %H:%M:%S")

                    duration_min = int(item.get("duration_min", 0))

                    end_time_dt_aware = start_time_dt_aware + datetime.timedelta(minutes=duration_min)
                    end_time_jst = end_time_dt_aware.astimezone(jst)
                    end_time_formatted_str = end_time_jst.strftime("%Y-%m-%d %H:%M:%S")

                    hours, remainder_minutes = divmod(duration_min, 60)
                    duration_formatted = f"{int(hours):02d}:{int(remainder_minutes):02d}"
                    contest_type = self._determine_contest_type(name)

                    transformed_contests.append(
                        {
                            "name": name,
                            "start_time": start_time_formatted_str,
                            "end_time": end_time_formatted_str,
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
                    continue

            self.contests = transformed_contests
            self.save_contests(self.contests)
            print(f"{len(transformed_contests)}件のコンテスト情報を更新・保存しました。")
        else:
            print("コンテスト情報の取得に失敗したため、更新できませんでした。")

    @fetch_contests.before_loop
    async def before_fetch_contests(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="reminder---schedule", description="Displays upcoming AtCoder contests.")
    async def contest_schedule_command(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.contests:
            embed = discord.Embed(
                title="Upcoming Contests",
                description="No contest data loaded. Please try again later.",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)
            return

        jst = datetime.timezone(datetime.timedelta(hours=9))
        now_jst = datetime.datetime.now(jst)

        upcoming_contests_details = []
        for contest_data in self.contests:
            try:
                # contest_data["start_time"] is a "YYYY-MM-DD HH:MM:SS" string in JST.
                start_time_naive = datetime.datetime.strptime(contest_data["start_time"], "%Y-%m-%d %H:%M:%S")
                start_time_jst_obj = start_time_naive.replace(tzinfo=jst)

                # contest_data["end_time"] is also a "YYYY-MM-DD HH:MM:SS" string in JST.
                end_time_naive = datetime.datetime.strptime(contest_data["end_time"], "%Y-%m-%d %H:%M:%S")
                end_time_jst_obj = end_time_naive.replace(tzinfo=jst)

                if end_time_jst_obj > now_jst:
                    upcoming_contests_details.append({
                        "data": contest_data,
                        "start_time_obj": start_time_jst_obj
                    })
            except ValueError as e:
                print(f"Error parsing date for contest {contest_data.get('name', 'N/A')}: {e}")
                continue

        upcoming_contests_details.sort(key=lambda c: c["start_time_obj"])

        if not upcoming_contests_details:
            embed = discord.Embed(
                title="Upcoming Contests",
                description="No upcoming contests found.",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="🗓️ Upcoming Contests",
                color=discord.Color.blue()
            )
            description_lines = []
            for contest_entry in upcoming_contests_details[:10]:
                contest = contest_entry["data"]
                start_time_to_display = contest_entry["start_time_obj"]

                description_lines.append(
                    f"**[{contest['name']}]({contest['url']})**\n"
                    f"**Starts:** {start_time_to_display.strftime('%Y-%m-%d %H:%M')} JST\n"
                    f"**Duration:** {contest['duration']}\n"
                    f"**Type:** {contest['type']}\n"
                    f"**Rated:** {contest['rated_range'] if contest['rated_range'] else '-'}\n"
                )
            embed.description = "\n".join(description_lines)
            if len(upcoming_contests_details) > 10:
                embed.set_footer(text=f"Showing 10 of {len(upcoming_contests_details)} upcoming contests.")

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ContestData(bot))
