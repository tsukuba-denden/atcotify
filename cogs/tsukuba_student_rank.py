import discord
from discord import app_commands
from discord.ext import commands
import pandas as pd
import requests
from io import StringIO
import yaml
import calculate_hash
from env.config import Config

# 環境変数から設定を読み込む
config = Config()
SEASON = config.season

# 学校名略称を読み込む
with open("asset/school_abbreviations.yaml", encoding="utf-8") as f:
    school_abbreviations = yaml.safe_load(f)

# 筑波大学附属中学校の生徒の前回の順位を保存するファイル名
TSUKUBA_STUDENT_RANK_FILE = "./asset/tsukuba_student_rank.yaml"

# tsukuba_student_rank用のHTMLファイル名
TSUKUBA_STUDENT_RANK_HTML_FILE = "./html/tsukuba_student_rank.html"

# ランキングページのベースURL
GRADE_A_BASE_URL = "https://img.atcoder.jp/ajl2024{}/grade_{}_rankings_A_score.html"
GRADE_H_BASE_URL = "https://img.atcoder.jp/ajl2024{}/grade_{}_rankings_H_score.html"


class Tsukuba_student_rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def save_tsukuba_student_rank(self, ranks_dict, filename):
        """筑波大学附属中学校の生徒の順位とユーザIDをYAMLファイルに保存する"""
        with open(filename, "w", encoding="utf-8") as f:
            yaml.dump(
                ranks_dict,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    async def load_tsukuba_student_rank(self, filename):
        """筑波大学附属中学校の生徒の順位とユーザIDをYAMLファイルから読み込む"""
        try:
            with open(filename, "r", encoding="utf-8") as f:
                ranks_dict = yaml.safe_load(f)
                if ranks_dict is not None:
                    # 読み込んだデータに前回の順位データが存在しない場合は初期化する
                    if "P_A" not in ranks_dict or "P_H" not in ranks_dict:
                        ranks_dict["P_A"] = {f"grade{i+1}": [] for i in range(3)}
                        ranks_dict["P_H"] = {f"grade{i+1}": [] for i in range(3)}
                    return ranks_dict
                else:
                    return {
                        "A": {f"grade{i+1}": [] for i in range(3)},
                        "H": {f"grade{i+1}": [] for i in range(3)},
                        "P_A": {f"grade{i+1}": [] for i in range(3)},
                        "P_H": {f"grade{i+1}": [] for i in range(3)},
                    }

        except (FileNotFoundError, yaml.YAMLError, TypeError, KeyError) as e:
            print(f"YAMLファイルの読み込みエラー: {e}")
            return {
                "A": {f"grade{i+1}": [] for i in range(3)},
                "H": {f"grade{i+1}": [] for i in range(3)},
                "P_A": {f"grade{i+1}": [] for i in range(3)},
                "P_H": {f"grade{i+1}": [] for i in range(3)},
            }

    async def get_student_rank(self, html, school_name):
        """HTMLから指定された学校の生徒の順位とユーザー名をリストとして取得する"""
        df = pd.read_html(StringIO(html), encoding="utf-8")[0]

        # 学校名で検索
        student_rows = df[df["学校名"] == school_name]
        results = []
        for _, row in student_rows.iterrows():
            results.append((row["順位"], row["ユーザID"]))
        return results

    async def get_rank_info(self, user_id, df, previous_rank, contest_type, grade):
        """順位比較のための情報を取得する"""
        rank_info = ""
        tsukuba_row = df[df["ユーザID"] == user_id].index[0]

        # 過去の順位情報から前回の順位を取得
        previous_rank_for_user = None
        if previous_rank and f"grade{grade}" in previous_rank:
            for prev_user_data in previous_rank[f"grade{grade}"]:
                if prev_user_data["name"] == user_id:
                    previous_rank_for_user = prev_user_data["rank"]
                    break

        if previous_rank_for_user is not None:
            rank = df[df["ユーザID"] == user_id]["順位"].iloc[0]
            rank_info += f" {previous_rank_for_user}位 → **{rank}**位"
        else:
            rank = df[df["ユーザID"] == user_id]["順位"].iloc[0]
            rank_info += f" 初参加 → **{rank}**位"

        if tsukuba_row > 0:
            above_row = df.iloc[tsukuba_row - 1]
            above_school = above_row["学校名"]
            if above_school in school_abbreviations:
                above_school = school_abbreviations[above_school]
            elif above_school.endswith("中学校"):
                above_school = above_school[:-3]
            above_user = above_row["ユーザID"]
            score_diff = int(above_row["スコア"]) - int(
                df[df["ユーザID"] == user_id]["スコア"].iloc[0]
            )
            rank_info += (
                f"\n>  _{above_school}_ **{above_user}** まであと **{score_diff}**点！"
            )
        else:
            rank_info += "  現在トップです！"

        return rank_info

    async def process_grade_ranks(
        self, contest_type, season_suffix, saved_previous_ranks
    ):
        """各学年の順位を取得し、Embed用のdescriptionを作成する"""
        description = ""
        new_participants = []
        base_url = GRADE_A_BASE_URL if contest_type == "A" else GRADE_H_BASE_URL
        grade_ranks_all = []

        for grade in range(1, 4):
            response = requests.get(base_url.format(season_suffix, grade))
            response.raise_for_status()
            response.encoding = "utf-8"
            html = response.text

            if grade == 3 and SEASON == "WINTER":
                grade_ranks_all.append([])
                continue

            grade_ranks = await self.get_student_rank(html, "筑波大学附属中学校")
            grade_ranks_all.append(grade_ranks)

            if grade_ranks:
                description += f"## 中{grade}\n"
                df = pd.read_html(StringIO(html), encoding="utf-8")[0]
                df = df[df["学校名"] != "学校名"]

                for rank, user_id in grade_ranks:
                    rank_info = await self.get_rank_info(
                        user_id,
                        df,
                        saved_previous_ranks[contest_type],
                        contest_type,
                        grade,
                    )

                    description += f"\n### **{user_id}**\n> {rank_info}\n"

                    # 新規参加者かどうかを判定
                    is_new_participant = True
                    if (
                        saved_previous_ranks[contest_type]
                        and f"grade{grade}" in saved_previous_ranks[contest_type]
                    ):
                        for prev_user_data in saved_previous_ranks[contest_type][
                            f"grade{grade}"
                        ]:
                            if prev_user_data["name"] == user_id:
                                is_new_participant = False
                                break

                    if is_new_participant:
                        new_participants.append(user_id)

        if new_participants:
            description += "\n:tada: 新規参加者 :tada:\n"
            for user_id in new_participants:
                description += f"- **{user_id}**\n"

        return description, grade_ranks_all

    @app_commands.command(
        name="tsukuba_student_rank",
        description="筑波大学附属中学校の生徒の順位を表示します",
    )
    async def tsukuba_student_rank_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            season_suffix = "winter" if SEASON == "WINTER" else "summer"

            # 前回のハッシュ値を取得（ファイルが存在しない場合はNone）
            try:
                previous_html_hash = calculate_hash.calculate_hash(
                    TSUKUBA_STUDENT_RANK_HTML_FILE
                )
            except FileNotFoundError:
                previous_html_hash = None

            # 最新のHTMLをダウンロード (Aコンテストのgrade1のものを使用)
            response = requests.get(GRADE_A_BASE_URL.format(season_suffix, 1))
            response.raise_for_status()
            response.encoding = "utf-8"

            # HTMLをファイルに保存
            with open(TSUKUBA_STUDENT_RANK_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(response.text)

            # 現在のHTMLのハッシュ値を取得
            current_html_hash = calculate_hash.calculate_hash(
                TSUKUBA_STUDENT_RANK_HTML_FILE
            )

            # 前回の順位を読み込み
            loaded_ranks = await self.load_tsukuba_student_rank(
                TSUKUBA_STUDENT_RANK_FILE
            )
            saved_previous_ranks = {
                "A": loaded_ranks["P_A"],
                "H": loaded_ranks["P_H"],
            }

            # 初回実行時または前回のデータがない場合は、空のリストで初期化して保存する
            if not any(saved_previous_ranks["A"].values()) or not any(
                saved_previous_ranks["H"].values()
            ):
                saved_previous_ranks = {
                    "A": {f"grade{i+1}": [] for i in range(3)},
                    "H": {f"grade{i+1}": [] for i in range(3)},
                }
                await self.save_tsukuba_student_rank(
                    {
                        "A": saved_previous_ranks["A"],
                        "H": saved_previous_ranks["H"],
                        "P_A": saved_previous_ranks["A"],
                        "P_H": saved_previous_ranks["H"],
                    },
                    TSUKUBA_STUDENT_RANK_FILE,
                )

            # Aコンテストの処理
            description_a, grade_ranks_a = await self.process_grade_ranks(
                "A", season_suffix, saved_previous_ranks
            )
            embed_a = discord.Embed(
                title="アルゴリズム",
                description=description_a,
                color=discord.Color.blue(),
            )

            # Hコンテストの処理
            description_h, grade_ranks_h = await self.process_grade_ranks(
                "H", season_suffix, saved_previous_ranks
            )
            embed_h = discord.Embed(
                title="ヒューリスティック",
                description=description_h,
                color=discord.Color.blue(),
            )

            # 現在の順位を整形
            current_ranks = {
                "A": {
                    f"grade{i+1}": [
                        {"name": user_id, "rank": rank} for rank, user_id in grade_ranks
                    ]
                    for i, grade_ranks in enumerate(grade_ranks_a)
                },
                "H": {
                    f"grade{i+1}": [
                        {"name": user_id, "rank": rank} for rank, user_id in grade_ranks
                    ]
                    for i, grade_ranks in enumerate(grade_ranks_h)
                },
                "P_A": saved_previous_ranks["A"],
                "P_H": saved_previous_ranks["H"],
            }

            # 現在の順位を保存
            await self.save_tsukuba_student_rank(
                current_ranks, TSUKUBA_STUDENT_RANK_FILE
            )

            await interaction.followup.send(embeds=[embed_a, embed_h])

        except requests.exceptions.RequestException as e:
            error_message = f"順位表の取得中にエラーが発生しました: {e}"
            embed = discord.Embed(
                title="エラー", description=error_message, color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            error_message = f"エラーが発生しました: {e}"
            embed = discord.Embed(
                title="エラー", description=error_message, color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tsukuba_student_rank(bot))
