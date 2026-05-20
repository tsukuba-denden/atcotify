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
    DEFAULT_SCHOOL_TYPE,
    format_school_label,
    get_school_name_for_guild,
    get_school_type_for_guild,
    iter_guild_settings,
    normalize_school_type,
    set_channel_id_for_guild,
    set_school_for_guild,
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
AJL_RANKING_BASE_URL = f"https://img.atcoder.jp/ajl{YEAR}{{}}/school_rankings_grades_{{}}_{{}}.html"
CONTEST_TYPES = ("A", "H")
SCHOOL_TYPES = ("junior_high", "high")
MAX_SEARCH_RESULT_EMBEDS = 10


def abbreviate_school_name(school_name: Any) -> Any:
    if school_name in school_abbreviations:
        return school_abbreviations[school_name]
    if isinstance(school_name, str) and school_name.endswith("高等専門学校"):
        return school_name[:-6] + "高専"
    return school_name


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
    school_type: str = DEFAULT_SCHOOL_TYPE,
) -> dict[str, dict[str, Any]]:
    history_key = school_history_key(school_name, school_type)
    if history_key not in data or not isinstance(data[history_key], dict):
        data[history_key] = default_school_rank_history()

    for contest_type in CONTEST_TYPES:
        if contest_type not in data[history_key] or not isinstance(
            data[history_key][contest_type], dict
        ):
            data[history_key][contest_type] = empty_rank_entry()
        for key, value in empty_rank_entry().items():
            data[history_key][contest_type].setdefault(key, value)
    return data[history_key]


def school_history_key(school_name: str, school_type: str) -> str:
    return f"{normalize_school_type(school_type)}:{school_name}"


def load_school_rank_history() -> dict[str, Any]:
    if SCHOOL_RANK_FILE.exists():
        with SCHOOL_RANK_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif LEGACY_TSUKUBA_RANK_FILE.exists():
        with LEGACY_TSUKUBA_RANK_FILE.open("r", encoding="utf-8") as f:
            legacy_data = yaml.safe_load(f) or {}
        data = {school_history_key(DEFAULT_SCHOOL_NAME, DEFAULT_SCHOOL_TYPE): legacy_data}
    else:
        data = {}

    if all(contest_type in data for contest_type in CONTEST_TYPES):
        data = {school_history_key(DEFAULT_SCHOOL_NAME, DEFAULT_SCHOOL_TYPE): data}
    for key in list(data.keys()):
        if ":" not in str(key) and isinstance(data[key], dict):
            data[school_history_key(str(key), DEFAULT_SCHOOL_TYPE)] = data.pop(key)
    ensure_school_rank_history(data, DEFAULT_SCHOOL_NAME, DEFAULT_SCHOOL_TYPE)
    return data


def save_school_rank_history(data: dict[str, Any]) -> None:
    SCHOOL_RANK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SCHOOL_RANK_FILE.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def season_suffix() -> str:
    return "winter" if SEASON == "WINTER" else "summer"


def school_grade_range(school_type: str) -> str:
    return "4to6" if normalize_school_type(school_type) == "high" else "1to3"


def html_file_path(contest_type: str, school_type: str) -> Path:
    return (
        HTML_DIR
        / f"ajl_ranking_{season_suffix()}_{school_grade_range(school_type)}_{contest_type}.html"
    )


def fetch_school_rank_tables(
    school_type: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, bool]]:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    frames = {}
    html_changed = {}
    grade_range = school_grade_range(school_type)

    for contest_type in CONTEST_TYPES:
        path = html_file_path(contest_type, school_type)
        try:
            previous_hash = calculate_hash.calculate_hash(str(path))
        except FileNotFoundError:
            previous_hash = None

        response = requests.get(
            AJL_RANKING_BASE_URL.format(season_suffix(), grade_range, contest_type)
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


def find_matching_schools(
    query: str,
    tables_by_type: dict[str, tuple[dict[str, pd.DataFrame], dict[str, bool]]],
) -> list[tuple[str, str]]:
    exact_matches = []
    partial_matches = []
    seen = set()
    query = query.strip()
    query_lower = query.lower()

    for school_type in SCHOOL_TYPES:
        frames, _ = tables_by_type[school_type]
        for df in frames.values():
            for raw_school_name in df["学校名"].dropna().unique():
                school_name = str(raw_school_name).strip()
                school_key = (school_name, school_type)
                if school_key in seen:
                    continue
                seen.add(school_key)

                if school_name == query:
                    exact_matches.append(school_key)
                elif query_lower in school_name.lower():
                    partial_matches.append(school_key)

    return exact_matches or partial_matches


def build_school_rank_embeds(
    school_name: str,
    school_type: str,
    frames: dict[str, pd.DataFrame],
    html_changed: dict[str, bool],
    history: dict[str, Any],
) -> tuple[list[discord.Embed], bool, bool]:
    embeds = []
    changed = False
    school_type = normalize_school_type(school_type)
    school_history = ensure_school_rank_history(history, school_name, school_type)

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
            above_school_abbr = abbreviate_school_name(above_row["学校名"])
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
            f"school_rankings_grades_{school_grade_range(school_type)}_{contest_type}.html"
        )
        contest_label = "アルゴリズム" if contest_type == "A" else "ヒューリスティック"
        embed = discord.Embed(
            title=f"{contest_label}",
            description=description,
            color=discord.Color.blue(),
            url=embed_url,
        )
        embed.set_author(name=format_school_label(school_name, school_type))
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
        school_type: str = DEFAULT_SCHOOL_TYPE,
        frames: dict[str, pd.DataFrame] | None = None,
        html_changed: dict[str, bool] | None = None,
        history: dict[str, Any] | None = None,
    ) -> tuple[list[discord.Embed], bool]:
        if frames is None or html_changed is None:
            frames, html_changed = fetch_school_rank_tables(school_type)
        if history is None:
            history = load_school_rank_history()

        embeds, found, changed = build_school_rank_embeds(
            school_name, school_type, frames, html_changed, history
        )
        if changed:
            save_school_rank_history(history)
        if not found:
            return [], changed
        return embeds, changed

    async def send_school_rank(
        self,
        interaction: discord.Interaction,
        school_name: str,
        school_type: str,
    ):
        try:
            await interaction.response.defer()
            embeds, _ = await self.get_school_rank_data(school_name, school_type)

            if embeds:
                await interaction.followup.send(embeds=embeds)
            else:
                await interaction.followup.send(
                    f"{format_school_label(school_name, school_type)}"
                    "のデータが見つかりませんでした。"
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

    async def search_and_send_school_rank(
        self,
        interaction: discord.Interaction,
        query: str,
    ):
        try:
            await interaction.response.defer()
            tables_by_type = {
                school_type: fetch_school_rank_tables(school_type)
                for school_type in SCHOOL_TYPES
            }
            matches = find_matching_schools(query, tables_by_type)
            if not matches:
                await interaction.followup.send(
                    f"「{query}」に一致する学校データが見つかりませんでした。"
                )
                return

            history = load_school_rank_history()
            embeds = []
            changed = False
            omitted_count = 0
            for school_name, school_type in matches:
                frames, html_changed = tables_by_type[school_type]
                school_embeds, found, school_changed = build_school_rank_embeds(
                    school_name, school_type, frames, html_changed, history
                )
                if not found:
                    continue
                if len(embeds) + len(school_embeds) > MAX_SEARCH_RESULT_EMBEDS:
                    omitted_count += 1
                    continue
                embeds.extend(school_embeds)
                changed = changed or school_changed

            if changed:
                save_school_rank_history(history)

            if not embeds:
                await interaction.followup.send(
                    f"「{query}」に一致する学校データが見つかりませんでした。"
                )
                return

            content = None
            if omitted_count:
                content = f"候補が多いため、追加の{omitted_count}校は省略しました。"
            await interaction.followup.send(content=content, embeds=embeds)
        except requests.RequestException as e:
            print(f"Error fetching data: {e}")
            await interaction.followup.send(
                "データの取得中にエラーが発生しました。しばらくしてからもう一度お試しください。"
            )
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。")

    @app_commands.command(name="school_set", description="このサーバーの学校名を設定します。")
    @app_commands.choices(
        school_type=[
            app_commands.Choice(name="中学", value="junior_high"),
            app_commands.Choice(name="高校", value="high"),
        ]
    )
    @can_manage_school_settings()
    async def school_set(
        self,
        interaction: discord.Interaction,
        school_name: str,
        school_type: str = DEFAULT_SCHOOL_TYPE,
    ):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        school_type = normalize_school_type(school_type)
        set_school_for_guild(interaction.guild_id, school_name, school_type)
        embed = discord.Embed(
            title="設定完了",
            description=(
                f"このサーバーの学校を "
                f"{format_school_label(school_name, school_type)}に設定しました。"
            ),
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
            description=(
                "このサーバーの学校設定を削除しました。"
                f"デフォルトは "
                f"{format_school_label(DEFAULT_SCHOOL_NAME, DEFAULT_SCHOOL_TYPE)}です。"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="school_rank",
        description="AJL学校順位を表示します。学校名を指定しない場合はサーバー設定を使います。",
    )
    @app_commands.describe(
        school_name="表示する学校名。未指定の場合はこのサーバーに設定された学校を表示します。"
    )
    async def school_rank(
        self,
        interaction: discord.Interaction,
        school_name: str | None = None,
    ):
        if school_name and school_name.strip():
            await self.search_and_send_school_rank(interaction, school_name.strip())
            return

        await self.send_school_rank(
            interaction,
            get_school_name_for_guild(interaction.guild_id),
            get_school_type_for_guild(interaction.guild_id),
        )

    @app_commands.command(
        name="tsukuba_rank",
        description="現在のAJLの筑波大学附属中学校の順位を表示します。",
    )
    async def tsukuba_rank(self, interaction: discord.Interaction):
        await self.send_school_rank(interaction, DEFAULT_SCHOOL_NAME, DEFAULT_SCHOOL_TYPE)

    @tasks.loop(minutes=15)
    async def check_school_rank_loop(self):
        print("Checking School Rank...")
        try:
            history = load_school_rank_history()
            target_guilds = []
            for guild_id, guild_settings in iter_guild_settings():
                channel_id = guild_settings.get("school_rank_channel_id") or guild_settings.get(
                    "tsukuba_rank_channel_id"
                )
                if channel_id:
                    target_guilds.append(
                        (
                            guild_id,
                            str(channel_id),
                            get_school_name_for_guild(guild_id),
                            get_school_type_for_guild(guild_id),
                        )
                    )

            tables_by_type = {}
            for school_type in sorted({school_type for _, _, _, school_type in target_guilds}):
                frames, html_changed = fetch_school_rank_tables(school_type)
                tables_by_type[school_type] = (frames, html_changed)

            if not any(
                any(html_changed.values()) for _, html_changed in tables_by_type.values()
            ):
                print("No changes in School Rank.")
                return

            embeds_by_school = {}
            changed_by_school = {}
            for school_name, school_type in sorted(
                {(school, school_type) for _, _, school, school_type in target_guilds}
            ):
                frames, html_changed = tables_by_type[school_type]
                embeds, found, changed = build_school_rank_embeds(
                    school_name, school_type, frames, html_changed, history
                )
                school_key = (school_name, school_type)
                embeds_by_school[school_key] = embeds if found else []
                changed_by_school[school_key] = changed

            if any(changed_by_school.values()):
                save_school_rank_history(history)

            for guild_id, channel_id, school_name, school_type in target_guilds:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    print(f"Channel with ID {channel_id} not found in guild {guild_id}.")
                    continue

                school_key = (school_name, school_type)
                embeds = embeds_by_school.get(school_key, [])
                if embeds and changed_by_school.get(school_key, False):
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
        school_type = get_school_type_for_guild(interaction.guild_id)
        embed = discord.Embed(
            title="設定完了",
            description=(
                f"{format_school_label(school_name, school_type)}"
                f"の順位通知チャンネルを {channel.mention} に設定しました。"
            ),
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
