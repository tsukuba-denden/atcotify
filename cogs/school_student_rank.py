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
from cogs.school_settings import (
    DEFAULT_SCHOOL_NAME,
    get_school_name_for_guild,
    iter_guild_settings,
    set_channel_id_for_guild,
    unset_channel_id_for_guild,
)
from env.config import Config

config = Config()
SEASON = config.season
YEAR = config.year

with open("asset/school_abbreviations.yaml", encoding="utf-8") as f:
    school_abbreviations = yaml.safe_load(f) or {}

HTML_DIR = Path("html")
SCHOOL_STUDENT_RANK_FILE = Path("asset/school_student_rank.yaml")
LEGACY_TSUKUBA_STUDENT_RANK_FILE = Path("asset/tsukuba_student_rank.yaml")
GRADE_A_BASE_URL = f"https://img.atcoder.jp/ajl{YEAR}{{}}/grade_{{}}_rankings_A_score.html"
GRADE_H_BASE_URL = f"https://img.atcoder.jp/ajl{YEAR}{{}}/grade_{{}}_rankings_H_score.html"
CONTEST_TYPES = ("A", "H")
RANK_KEYS = ("A", "H", "P_A", "P_H", "L_A", "L_H")


def season_suffix() -> str:
    return "winter" if SEASON == "WINTER" else "summer"


def empty_grade_map() -> dict[str, list[dict[str, str]]]:
    return {f"grade{i + 1}": [] for i in range(3)}


def default_student_history() -> dict[str, dict[str, list[dict[str, str]]]]:
    return {key: empty_grade_map() for key in RANK_KEYS}


def ensure_student_history(data: dict[str, Any], school_name: str) -> dict[str, Any]:
    if school_name not in data or not isinstance(data[school_name], dict):
        data[school_name] = default_student_history()

    for key in RANK_KEYS:
        if key not in data[school_name] or not isinstance(data[school_name][key], dict):
            data[school_name][key] = empty_grade_map()
        for grade in range(1, 4):
            data[school_name][key].setdefault(f"grade{grade}", [])
    return data[school_name]


def load_school_student_rank_history() -> dict[str, Any]:
    if SCHOOL_STUDENT_RANK_FILE.exists():
        with SCHOOL_STUDENT_RANK_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif LEGACY_TSUKUBA_STUDENT_RANK_FILE.exists():
        with LEGACY_TSUKUBA_STUDENT_RANK_FILE.open("r", encoding="utf-8") as f:
            legacy_data = yaml.safe_load(f) or {}
        data = {DEFAULT_SCHOOL_NAME: legacy_data}
    else:
        data = {}

    if all(key in data for key in RANK_KEYS):
        data = {DEFAULT_SCHOOL_NAME: data}
    ensure_student_history(data, DEFAULT_SCHOOL_NAME)
    return data


def save_school_student_rank_history(data: dict[str, Any]) -> None:
    SCHOOL_STUDENT_RANK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SCHOOL_STUDENT_RANK_FILE.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def grade_html_path(contest_type: str, grade: int) -> Path:
    return HTML_DIR / f"grade_{grade}_rankings_{contest_type}_{season_suffix()}.html"


def grade_url(contest_type: str, grade: int) -> str:
    base_url = GRADE_A_BASE_URL if contest_type == "A" else GRADE_H_BASE_URL
    return base_url.format(season_suffix(), grade)


def fetch_student_rank_tables() -> tuple[dict[str, dict[int, pd.DataFrame]], dict[str, bool]]:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    frames: dict[str, dict[int, pd.DataFrame]] = {"A": {}, "H": {}}
    html_changed = {"A": False, "H": False}

    for contest_type in CONTEST_TYPES:
        for grade in range(1, 4):
            if grade == 3 and SEASON == "WINTER":
                frames[contest_type][grade] = pd.DataFrame()
                continue

            path = grade_html_path(contest_type, grade)
            try:
                previous_hash = calculate_hash.calculate_hash(str(path))
            except FileNotFoundError:
                previous_hash = None

            response = requests.get(grade_url(contest_type, grade))
            response.raise_for_status()
            response.encoding = "utf-8"

            with path.open("w", encoding="utf-8") as f:
                f.write(response.text)

            current_hash = calculate_hash.calculate_hash(str(path))
            if current_hash != previous_hash:
                html_changed[contest_type] = True

            df = pd.read_html(StringIO(response.text), encoding="utf-8")[0]
            frames[contest_type][grade] = df[df["学校名"] != "学校名"]

    return frames, html_changed


def get_student_rank(df: pd.DataFrame, school_name: str) -> list[tuple[str, str]]:
    student_rows = df[df["学校名"] == school_name]
    return [(str(row["順位"]), str(row["ユーザID"])) for _, row in student_rows.iterrows()]


def find_saved_rank(
    saved_ranks: dict[str, Any],
    rank_key: str,
    grade: int,
    user_id: str,
) -> str | None:
    for prev_user_data in saved_ranks.get(rank_key, {}).get(f"grade{grade}", []):
        if prev_user_data.get("name") == user_id:
            return prev_user_data.get("rank")
    return None


def get_rank_info(
    user_id: str,
    df: pd.DataFrame,
    saved_ranks: dict[str, Any],
    contest_type: str,
    grade: int,
    html_changed: bool,
) -> str:
    rank_info = ""
    student_index = df.index.get_loc(df[df["ユーザID"] == user_id].index[0])
    rank = str(df[df["ユーザID"] == user_id]["順位"].iloc[0])

    previous_rank = find_saved_rank(saved_ranks, "P_" + contest_type, grade, user_id)
    last_rank = find_saved_rank(saved_ranks, "L_" + contest_type, grade, user_id)

    if html_changed:
        if last_rank is not None:
            rank_info += f" {last_rank}位 → **{rank}**位"
        else:
            rank_info += f" 初参加 → **{rank}**位"
    elif previous_rank is not None:
        rank_info += f" {previous_rank}位 → **{rank}**位"
    else:
        rank_info += f" 初参加 → **{rank}**位"

    if student_index > 0:
        above_row = df.iloc[student_index - 1]
        above_school = above_row["学校名"]
        if above_school in school_abbreviations:
            above_school = school_abbreviations[above_school]
        elif isinstance(above_school, str) and above_school.endswith("中学校"):
            above_school = above_school[:-3]
        above_user = above_row["ユーザID"]
        score_diff = int(above_row["スコア"]) - int(
            df[df["ユーザID"] == user_id]["スコア"].iloc[0]
        )
        rank_info += f"\n>  _{above_school}_ **{above_user}** まであと **{score_diff}**点！"
    else:
        rank_info += "  現在トップです！"

    return rank_info


def process_grade_ranks(
    school_name: str,
    contest_type: str,
    frames: dict[str, dict[int, pd.DataFrame]],
    saved_ranks: dict[str, Any],
    html_changed: bool,
) -> tuple[str, list[list[tuple[str, str]]]]:
    description = ""
    new_participants = []
    grade_ranks_all = []

    for grade in range(1, 4):
        if grade == 3 and SEASON == "WINTER":
            grade_ranks_all.append([])
            continue

        df = frames[contest_type][grade]
        grade_ranks = get_student_rank(df, school_name)
        grade_ranks_all.append(grade_ranks)

        if not grade_ranks:
            continue

        description += f"## 中{grade}\n"

        for rank, user_id in grade_ranks:
            rank_info = get_rank_info(
                user_id, df, saved_ranks, contest_type, grade, html_changed
            )
            description += f"\n### **{user_id}**\n> {rank_info}\n"

            is_new_participant = (
                find_saved_rank(saved_ranks, "L_" + contest_type, grade, user_id) is None
                and find_saved_rank(saved_ranks, "P_" + contest_type, grade, user_id)
                is None
            )
            if is_new_participant:
                new_participants.append(user_id)

    if new_participants:
        description += "\n:tada: 新規参加者 :tada:\n"
        for user_id in new_participants:
            description += f"- **{user_id}**\n"

    return description, grade_ranks_all


def build_school_student_rank_embeds(
    school_name: str,
    frames: dict[str, dict[int, pd.DataFrame]],
    html_changed: dict[str, bool],
    history: dict[str, Any],
) -> tuple[list[discord.Embed], bool, bool]:
    embeds = []
    changed = False
    saved_ranks = ensure_student_history(history, school_name)
    grade_ranks_by_contest = {}

    for contest_type in CONTEST_TYPES:
        description, grade_ranks = process_grade_ranks(
            school_name,
            contest_type,
            frames,
            saved_ranks,
            html_changed[contest_type],
        )
        grade_ranks_by_contest[contest_type] = grade_ranks
        if not description:
            continue

        url = (
            f"https://img.atcoder.jp/ajl{YEAR}{season_suffix()}/"
            f"school_rankings_grades_1to3_{contest_type}.html"
        )
        embed = discord.Embed(
            title="アルゴリズム" if contest_type == "A" else "ヒューリスティック",
            description=description,
            color=discord.Color.blue(),
            url=url,
        )
        embed.set_author(name=f"{school_name} のAJL生徒順位")
        embeds.append(embed)

    for contest_type in CONTEST_TYPES:
        if not html_changed[contest_type]:
            continue

        saved_ranks["P_" + contest_type] = {
            grade: list(users)
            for grade, users in saved_ranks["L_" + contest_type].items()
        }
        for i, grade_rank_list in enumerate(grade_ranks_by_contest[contest_type]):
            saved_ranks["L_" + contest_type][f"grade{i + 1}"] = [
                {"name": user_id, "rank": rank} for rank, user_id in grade_rank_list
            ]
        changed = True

    return embeds, bool(embeds), changed


class SchoolStudentRank(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_school_student_rank_loop.start()

    def cog_unload(self):
        self.check_school_student_rank_loop.cancel()

    async def get_school_student_rank_data(
        self,
        school_name: str,
        frames: dict[str, dict[int, pd.DataFrame]] | None = None,
        html_changed: dict[str, bool] | None = None,
        history: dict[str, Any] | None = None,
    ) -> tuple[list[discord.Embed], bool]:
        if frames is None or html_changed is None:
            frames, html_changed = fetch_student_rank_tables()
        if history is None:
            history = load_school_student_rank_history()

        embeds, found, changed = build_school_student_rank_embeds(
            school_name, frames, html_changed, history
        )
        if changed:
            save_school_student_rank_history(history)
        if not found:
            return [], changed
        return embeds, changed

    async def send_school_student_rank(
        self, interaction: discord.Interaction, school_name: str
    ):
        await interaction.response.defer()
        try:
            embeds, _ = await self.get_school_student_rank_data(school_name)
            if embeds:
                await interaction.followup.send(embeds=embeds)
            else:
                await interaction.followup.send(
                    f"{school_name} の生徒データが見つかりませんでした。"
                    "学校名がAJL上の表記と完全一致しているか確認してください。"
                )
        except requests.RequestException as e:
            print(f"Error fetching student data: {e}")
            await interaction.followup.send(
                "生徒データの取得中にエラーが発生しました。しばらくしてからもう一度お試しください。"
            )
        except Exception as e:
            print(f"An unexpected error occurred in student rank: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。")

    @app_commands.command(
        name="school_student_rank",
        description="このサーバーに設定された学校のAJL生徒順位を表示します。",
    )
    async def school_student_rank(self, interaction: discord.Interaction):
        await self.send_school_student_rank(
            interaction, get_school_name_for_guild(interaction.guild_id)
        )

    @app_commands.command(
        name="tsukuba_student_rank",
        description="筑波大学附属中学校の生徒の順位を表示します。",
    )
    async def tsukuba_student_rank(self, interaction: discord.Interaction):
        await self.send_school_student_rank(interaction, DEFAULT_SCHOOL_NAME)

    @tasks.loop(minutes=15)
    async def check_school_student_rank_loop(self):
        print("Checking School Student Rank...")
        try:
            frames, html_changed = fetch_student_rank_tables()
            if not any(html_changed.values()):
                print("No changes in School Student Rank.")
                return

            history = load_school_student_rank_history()
            target_guilds = []
            for guild_id, guild_settings in iter_guild_settings():
                channel_id = guild_settings.get(
                    "school_student_rank_channel_id"
                ) or guild_settings.get("tsukuba_student_rank_channel_id")
                if channel_id:
                    target_guilds.append(
                        (guild_id, str(channel_id), get_school_name_for_guild(guild_id))
                    )

            embeds_by_school = {}
            changed_by_school = {}
            for school_name in sorted({school for _, _, school in target_guilds}):
                embeds, found, changed = build_school_student_rank_embeds(
                    school_name, frames, html_changed, history
                )
                embeds_by_school[school_name] = embeds if found else []
                changed_by_school[school_name] = changed

            if any(changed_by_school.values()):
                save_school_student_rank_history(history)

            for guild_id, channel_id, school_name in target_guilds:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    print(
                        f"Channel with ID {channel_id} not found in guild {guild_id} "
                        "for student rank."
                    )
                    continue

                embeds = embeds_by_school.get(school_name, [])
                if embeds and changed_by_school.get(school_name, False):
                    await channel.send(embeds=embeds)
                    print(f"School Student Rank updated and sent to guild {guild_id}.")
                elif not embeds:
                    print(
                        f"School Student Rank data not found for {school_name} "
                        f"in guild {guild_id}."
                    )
        except Exception as e:
            print(f"Error in check_school_student_rank_loop: {e}")

    @check_school_student_rank_loop.before_loop
    async def before_check_school_student_rank_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="school_student_rank_set_ch",
        description="生徒順位通知チャンネルを設定します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def school_student_rank_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        set_channel_id_for_guild(
            interaction.guild_id, "school_student_rank_channel_id", channel.id
        )
        school_name = get_school_name_for_guild(interaction.guild_id)
        embed = discord.Embed(
            title="設定完了",
            description=f"{school_name} の生徒順位通知チャンネルを {channel.mention} に設定しました。",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="school_student_rank_unset_ch",
        description="生徒順位通知チャンネルを解除します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def school_student_rank_unset_channel(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("このコマンドはサーバー内で実行してください。")
            return

        removed = unset_channel_id_for_guild(
            interaction.guild_id,
            "school_student_rank_channel_id",
            "tsukuba_student_rank_channel_id",
        )
        description = (
            "生徒順位通知チャンネルを解除しました。"
            if removed
            else "生徒順位通知チャンネルは設定されていません。"
        )
        embed = discord.Embed(
            title="設定解除" if removed else "情報",
            description=description,
            color=discord.Color.green() if removed else discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="tsukuba_student_rank---set_ch",
        description="筑波大学附属中学校の生徒の順位通知チャンネルを設定します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tsukuba_student_rank_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self.school_student_rank_set_channel.callback(self, interaction, channel)

    @app_commands.command(
        name="tsukuba_student_rank---unset_ch",
        description="筑波大学附属中学校の生徒の順位通知チャンネルを解除します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tsukuba_student_rank_unset_channel(self, interaction: discord.Interaction):
        await self.school_student_rank_unset_channel.callback(self, interaction)


async def setup(bot):
    await bot.add_cog(SchoolStudentRank(bot))
