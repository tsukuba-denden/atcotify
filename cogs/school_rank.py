from io import StringIO
from pathlib import Path
from typing import Any

import discord
import pandas as pd
import requests
import yaml
from discord import app_commands
from discord.ext import commands, tasks

import calculate_hash
from cogs.permission_checks import can_manage_school_settings
from cogs.school_settings import (
    DEFAULT_SCHOOL_NAME,
    get_channel_id_for_guild,
    get_school_name_for_guild,
    iter_guild_settings,
    set_channel_id_for_guild,
    set_school_name_for_guild,
    unset_channel_id_for_guild,
    unset_school_name_for_guild,
)
from env.config import Config

config = Config()
SEASON = config.season
YEAR = config.year

with open("asset/school_abbreviations.yaml", encoding="utf-8") as f:
    school_abbreviations = yaml.safe_load(f) or {}

HTML_DIR = Path("html")
SCHOOL_RANK_FILE = Path("asset/school_rank.yaml")
LEGACY_TSUKUBA_RANK_FILE = Path("asset/tsukuba_rank.yaml")
AJL_RANKING_BASE_URL = (
    f"https://img.atcoder.jp/ajl{YEAR}{{}}/school_rankings_grades_1to3_{{}}.html"
)
CONTEST_TYPES = ("A", "H")


def empty_rank_entry() -> dict[str, int | None]:
    return {
        "previous_rank": None,
        "previous_score": None,
        "last_rank": None,
        "last_score": None,
    }


def default_school_rank_history() -> dict[str, dict[str, int | None]]:
    return {contest_type: empty_rank_entry() for contest_type in CONTEST_TYPES}


def ensure_school_rank_history(
    data: dict[str, Any],
    school_name: str,
) -> dict[str, dict[str, Any]]:
    if school_name not in data or not isinstance(data[school_name], dict):
        data[school_name] = default_school_rank_history()

    for contest_type in CONTEST_TYPES:
        if contest_type not in data[school_name] or not isinstance(
            data[school_name][contest_type], dict
        ):
            data[school_name][contest_type] = empty_rank_entry()
        for key, value in empty_rank_entry().items():
            data[school_name][contest_type].setdefault(key, value)
    return data[school_name]


def load_school_rank_history() -> dict[str, Any]:
    if SCHOOL_RANK_FILE.exists():
        with SCHOOL_RANK_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif LEGACY_TSUKUBA_RANK_FILE.exists():
        with LEGACY_TSUKUBA_RANK_FILE.open("r", encoding="utf-8") as f:
            legacy_data = yaml.safe_load(f) or {}
        data = {DEFAULT_SCHOOL_NAME: legacy_data}
    else:
        data = {}

    if all(contest_type in data for contest_type in CONTEST_TYPES):
        data = {DEFAULT_SCHOOL_NAME: data}
    ensure_school_rank_history(data, DEFAULT_SCHOOL_NAME)
    return data


def save_school_rank_history(data: dict[str, Any]) -> None:
    SCHOOL_RANK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SCHOOL_RANK_FILE.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def season_suffix() -> str:
    return "winter" if SEASON == "WINTER" else "summer"


def html_file_path(contest_type: str) -> Path:
    return HTML_DIR / f"ajl_ranking_{season_suffix()}_{contest_type}.html"


def fetch_school_rank_tables() -> tuple[dict[str, pd.DataFrame], dict[str, bool]]:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    frames = {}
    html_changed = {}

    for contest_type in CONTEST_TYPES:
        path = html_file_path(contest_type)
        try:
            previous_hash = calculate_hash.calculate_hash(str(path))
        except FileNotFoundError:
            previous_hash = None

        response = requests.get(
            AJL_RANKING_BASE_URL.format(season_suffix(), contest_type)
        )
        response.raise_for_status()
        response.encoding = "utf-8"

        with path.open("w", encoding="utf-8") as f:
            f.write(response.text)

        current_hash = calculate_hash.calculate_hash(str(path))
        html_changed[contest_type] = current_hash != previous_hash

        df = pd.read_html(StringIO(response.text), encoding="utf-8")[0]
        frames[contest_type] = df[df["学校名"] != "学校名"]

    return frames, html_changed


def build_school_rank_embeds(
    school_name: str,
    frames: dict[str, pd.DataFrame],
    html_changed: dict[str, bool],
    history: dict[str, Any],
) -> tuple[list[discord.Embed], bool, bool]:
    embeds = []
    changed = False
    school_history = ensure_school_rank_history(history, school_name)

    for contest_type in CONTEST_TYPES:
        df = frames[contest_type]
        school_row = df[df["学校名"] == school_name]
        if school_row.empty:
            continue

        school_rank_index = df.index.get_loc(school_row.index[0])
        current_rank = int(school_row.iloc[0]["順位"])
        current_score = int(school_row.iloc[0]["スコア"])

        previous_rank = school_history[contest_type]["previous_rank"]
        previous_score = school_history[contest_type]["previous_score"]
        last_rank = school_history[contest_type]["last_rank"]
        last_score = school_history[contest_type]["last_score"]

        description = "# "
        if html_changed[contest_type] or previous_rank is None:
            if previous_rank is not None:
                description += f"{last_rank}位→**||{current_rank}||位**\n"
            else:
                description += f"**||{current_rank}||位**\n"
        elif previous_rank is not None:
            description += f"{previous_rank}位→**||{current_rank}||位**\n"
        else:
            description += f"**||{current_rank}||位**\n"

        if school_rank_index > 0:
            above_row = df.iloc[school_rank_index - 1]
            above_school = above_row["学校名"]
            above_school_abbr = school_abbreviations.get(above_school, above_school)
            above_score = int(above_row["スコア"])
            score_diff = above_score - current_score
            description += f"> **{above_school_abbr}**まであと**{score_diff}**点！"
        else:
            description += "> 現在トップです！"

        if previous_score is not None and last_score is not None:
            if html_changed[contest_type]:
                score_change = current_score - last_score
            else:
                score_change = current_score - previous_score
            description += f"\n# {current_score}点\n> 前回より**{score_change}点**増えました！"
        else:
            description += f"\n# {current_score}点"

        embed_url = (
            f"https://img.atcoder.jp/ajl{YEAR}{season_suffix()}/"
            f"school_rankings_grades_1to3_{contest_type}.html"
        )
        embed = discord.Embed(
            title="アルゴリズム" if contest_type == "A" else "ヒューリスティック",
            description=description,
            color=discord.Color.blue(),
            url=embed_url,
        )
        embed.set_author(name=f"{school_name} のAJL学校順位")
        embeds.append(embed)

        if html_changed[contest_type]:
            school_history[contest_type]["previous_rank"] = last_rank
            school_history[contest_type]["previous_score"] = last_score
            school_history[contest_type]["last_rank"] = current_rank
            school_history[contest_type]["last_score"] = current_score
            changed = True

    return embeds, bool(embeds), changed


class SchoolRank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_school_rank_loop.start()

    def cog_unload(self):
        self.check_school_rank_loop.cancel()

    async def get_school_rank_data(
        self,
        school_name: str,
        frames: dict[str, pd.DataFrame] | None = None,
        html_changed: dict[str, bool] | None = None,
        history: dict[str, Any] | None = None,
    ) -> tuple[list[discord.Embed], bool]:
        if frames is None or html_changed is None:
            frames, html_changed = fetch_school_rank_tables()
        if history is None:
            history = load_school_rank_history()

        embeds, found, changed = build_school_rank_embeds(
            school_name, frames, html_changed, history
        )
        if changed:
            save_school_rank_history(history)
        if not found:
            return [], changed
        return embeds, changed

    async def send_school_rank(self, interaction: discord.Interaction, school_name: str):
        try:
            await interaction.response.defer()
            embeds, _ = await self.get_school_rank_data(school_name)

            if embeds:
                await interaction.followup.send(embeds=embeds)
            else:
                await interaction.followup.send(
                    f"{school_name} のデータが見つかりませんでした。"
                    "学校名がAJL上の表記と完全一致しているか確認してください。"
                )
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            await interaction.followup.send(
                "データの取得中にエラーが発生しました。しばらくしてからもう一度お試しください。"
            )
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。")

    @app_commands.command(name="school_set", description="このサーバーの学校名を設定します。")
    @can_manage_school_settings()
    async def school_set(self, interaction: discord.Interaction, school_name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        set_school_name_for_guild(interaction.guild_id, school_name)
        embed = discord.Embed(
            title="設定完了",
            description=f"このサーバーの学校名を {school_name.strip()} に設定しました。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="school_unset",
        description="このサーバーの学校名設定を削除し、デフォルトに戻します。",
    )
    @can_manage_school_settings()
    async def school_unset(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        unset_school_name_for_guild(interaction.guild_id)
        embed = discord.Embed(
            title="設定解除",
            description=f"このサーバーの学校名設定を削除しました。デフォルトは {DEFAULT_SCHOOL_NAME} です。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="school_rank",
        description="このサーバーに設定された学校のAJL学校順位を表示します。",
    )
    async def school_rank(self, interaction: discord.Interaction):
        await self.send_school_rank(
            interaction, get_school_name_for_guild(interaction.guild_id)
        )

    @app_commands.command(
        name="tsukuba_rank",
        description="現在のAJLの筑波大学附属中学校の順位を表示します。",
    )
    async def tsukuba_rank(self, interaction: discord.Interaction):
        await self.send_school_rank(interaction, DEFAULT_SCHOOL_NAME)

    @tasks.loop(minutes=15)
    async def check_school_rank_loop(self):
        print("Checking School Rank...")
        try:
            frames, html_changed = fetch_school_rank_tables()
            if not any(html_changed.values()):
                print("No changes in School Rank.")
                return

            history = load_school_rank_history()
            target_guilds = []
            for guild_id, guild_settings in iter_guild_settings():
                channel_id = guild_settings.get("school_rank_channel_id") or guild_settings.get(
                    "tsukuba_rank_channel_id"
                )
                if channel_id:
                    target_guilds.append(
                        (guild_id, str(channel_id), get_school_name_for_guild(guild_id))
                    )

            embeds_by_school = {}
            changed_by_school = {}
            for school_name in sorted({school for _, _, school in target_guilds}):
                embeds, found, changed = build_school_rank_embeds(
                    school_name, frames, html_changed, history
                )
                embeds_by_school[school_name] = embeds if found else []
                changed_by_school[school_name] = changed

            if any(changed_by_school.values()):
                save_school_rank_history(history)

            for guild_id, channel_id, school_name in target_guilds:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    print(f"Channel with ID {channel_id} not found in guild {guild_id}.")
                    continue

                embeds = embeds_by_school.get(school_name, [])
                if embeds and changed_by_school.get(school_name, False):
                    await channel.send(embeds=embeds)
                    print(f"School Rank updated and sent to guild {guild_id}.")
                elif not embeds:
                    print(f"School Rank data not found for {school_name} in guild {guild_id}.")
        except Exception as e:
            print(f"Error in check_school_rank_loop: {e}")

    @check_school_rank_loop.before_loop
    async def before_check_school_rank_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="school_rank_set_ch",
        description="学校順位通知チャンネルを設定します。",
    )
    @can_manage_school_settings()
    async def school_rank_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        set_channel_id_for_guild(
            interaction.guild_id, "school_rank_channel_id", channel.id
        )
        school_name = get_school_name_for_guild(interaction.guild_id)
        embed = discord.Embed(
            title="設定完了",
            description=f"{school_name} の順位通知チャンネルを {channel.mention} に設定しました。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="school_rank_unset_ch",
        description="学校順位通知チャンネルを解除します。",
    )
    @can_manage_school_settings()
    async def school_rank_unset_channel(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        removed = unset_channel_id_for_guild(
            interaction.guild_id, "school_rank_channel_id", "tsukuba_rank_channel_id"
        )
        description = (
            "学校順位通知チャンネルを解除しました。"
            if removed
            else "学校順位通知チャンネルは設定されていません。"
        )
        embed = discord.Embed(
            title="設定解除" if removed else "情報",
            description=description,
            color=discord.Color.green() if removed else discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="tsukuba_rank---set_ch",
        description="筑波大学附属中学校の順位通知チャンネルを設定します。",
    )
    @can_manage_school_settings()
    async def tsukuba_rank_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self.school_rank_set_channel.callback(self, interaction, channel)

    @app_commands.command(
        name="tsukuba_rank---unset_ch",
        description="筑波大学附属中学校の順位通知チャンネルを解除します。",
    )
    @can_manage_school_settings()
    async def tsukuba_rank_unset_channel(self, interaction: discord.Interaction):
        await self.school_rank_unset_channel.callback(self, interaction)


async def setup(bot):
    await bot.add_cog(SchoolRank(bot))
