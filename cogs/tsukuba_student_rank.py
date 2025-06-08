import os
from io import StringIO

import discord
import pandas as pd
import requests
import yaml
from discord import app_commands
from discord.ext import commands

import calculate_hash
from env.config import Config

# 環境変数から設定を読み込む
config = Config()
SEASON = config.season
YEAR = config.year

# 学校名略称を読み込む
with open("asset/school_abbreviations.yaml", encoding="utf-8") as f:
    school_abbreviations = yaml.safe_load(f)

# 筑波大学附属中学校の生徒の前回の順位を保存するファイル名
TSUKUBA_STUDENT_RANK_FILE = "./asset/tsukuba_student_rank.yaml"

# HTMLファイル保存ディレクトリを設定
html_dir = "html/"

# ランキングページのベースURL
GRADE_A_BASE_URL = f"https://img.atcoder.jp/ajl{YEAR}{{}}/grade_{{}}_rankings_A_score.html"
GRADE_H_BASE_URL = f"https://img.atcoder.jp/ajl{YEAR}{{}}/grade_{{}}_rankings_H_score.html"


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
                    # 必要なキーがあるか確認し、なければ初期化する
                    required_keys = ["A", "H", "P_A", "P_H", "L_A", "L_H"]
                    for key in required_keys:
                        if key not in ranks_dict:
                            ranks_dict[key] = {f"grade{i + 1}": [] for i in range(3)}
                    return ranks_dict
                else:
                    return {
                        "A": {f"grade{i + 1}": [] for i in range(3)},
                        "H": {f"grade{i + 1}": [] for i in range(3)},
                        "P_A": {f"grade{i + 1}": [] for i in range(3)},
                        "P_H": {f"grade{i + 1}": [] for i in range(3)},
                        "L_A": {f"grade{i + 1}": [] for i in range(3)},
                        "L_H": {f"grade{i + 1}": [] for i in range(3)},
                    }

        except (FileNotFoundError, yaml.YAMLError, TypeError, KeyError) as e:
            print(f"YAMLファイルの読み込みエラー: {e}")
            return {
                "A": {f"grade{i + 1}": [] for i in range(3)},
                "H": {f"grade{i + 1}": [] for i in range(3)},
                "P_A": {f"grade{i + 1}": [] for i in range(3)},
                "P_H": {f"grade{i + 1}": [] for i in range(3)},
                "L_A": {f"grade{i + 1}": [] for i in range(3)},
                "L_H": {f"grade{i + 1}": [] for i in range(3)},
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

    async def get_rank_info(
        self, user_id, df, saved_ranks, contest_type, grade, html_changed
    ):
        """順位比較のための情報を取得する"""
        rank_info = ""
        tsukuba_row = df[df["ユーザID"] == user_id].index[0]

        # 現在の順位を取得
        rank = df[df["ユーザID"] == user_id]["順位"].iloc[0]

        # 過去の順位情報を取得
        previous_rank_key = "P_" + contest_type
        last_rank_key = "L_" + contest_type
        previous_rank_for_user = None
        last_rank_for_user = None

        # 過去のデータを検索
        if saved_ranks[last_rank_key] and f"grade{grade}" in saved_ranks[last_rank_key]:
            for prev_user_data in saved_ranks[last_rank_key][f"grade{grade}"]:
                if prev_user_data["name"] == user_id:
                    last_rank_for_user = prev_user_data["rank"]
                    break

        if (
            saved_ranks[previous_rank_key]
            and f"grade{grade}" in saved_ranks[previous_rank_key]
        ):
            for prev_user_data in saved_ranks[previous_rank_key][f"grade{grade}"]:
                if prev_user_data["name"] == user_id:
                    previous_rank_for_user = prev_user_data["rank"]
                    break

        # HTMLに変更があった場合は最新のデータとlast_rankを比較
        if html_changed:
            if last_rank_for_user is not None:
                rank_info += f" {last_rank_for_user}位 → **{rank}**位"
            else:
                rank_info += f" 初参加 → **{rank}**位"
        # 変更がなかった場合はprevious_rankと比較
        else:
            if previous_rank_for_user is not None:
                rank_info += f" {previous_rank_for_user}位 → **{rank}**位"
            else:
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
        self, contest_type, season_suffix, saved_ranks, html_changed
    ):
        """各学年の順位を取得し、Embed用のdescriptionを作成する"""
        description = ""
        new_participants = []
        base_url = GRADE_A_BASE_URL if contest_type == "A" else GRADE_H_BASE_URL
        grade_ranks_all = []

        for grade in range(1, 4):
            # 冬季の3年生は処理しない
            if grade == 3 and SEASON == "WINTER":
                grade_ranks_all.append([])
                continue

            # HTMLファイルパスを設定
            html_file_path = os.path.join(
                html_dir, f"grade_{grade}_rankings_{contest_type}_{season_suffix}.html"
            )

            # HTMLをダウンロードして保存
            response = requests.get(base_url.format(season_suffix, grade))
            response.raise_for_status()
            response.encoding = "utf-8"
            html = response.text

            with open(html_file_path, "w", encoding="utf-8") as f:
                f.write(html)

            grade_ranks = await self.get_student_rank(html, "筑波大学附属中学校")
            grade_ranks_all.append(grade_ranks)

            if grade_ranks:
                description += f"## 中{grade}\n"
                df = pd.read_html(StringIO(html), encoding="utf-8")[0]
                df = df[df["学校名"] != "学校名"]

                for rank, user_id in grade_ranks:
                    rank_info = await self.get_rank_info(
                        user_id, df, saved_ranks, contest_type, grade, html_changed
                    )

                    description += f"\n### **{user_id}**\n> {rank_info}\n"

                    # 新規参加者かどうかを判定
                    is_new_participant = True
                    if (
                        saved_ranks["L_" + contest_type]
                        and f"grade{grade}" in saved_ranks["L_" + contest_type]
                    ):
                        for prev_user_data in saved_ranks["L_" + contest_type][
                            f"grade{grade}"
                        ]:
                            if prev_user_data["name"] == user_id:
                                is_new_participant = False
                                break

                    if (
                        is_new_participant
                        and saved_ranks["P_" + contest_type]
                        and f"grade{grade}" in saved_ranks["P_" + contest_type]
                    ):
                        for prev_user_data in saved_ranks["P_" + contest_type][
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
            html_changed = {"A": False, "H": False}

            # 前回のハッシュ値を確認するコンテスト種類と学年
            check_contest = "A"
            check_grade = 1

            # 前回のハッシュ値を取得
            html_file_path = os.path.join(
                html_dir,
                f"grade_{check_grade}_rankings_{check_contest}_{season_suffix}.html",
            )
            try:
                previous_html_hash = calculate_hash.calculate_hash(html_file_path)
            except FileNotFoundError:
                previous_html_hash = None

            # 最新のHTMLをダウンロード
            response = requests.get(GRADE_A_BASE_URL.format(season_suffix, check_grade))
            response.raise_for_status()
            response.encoding = "utf-8"
            html = response.text

            # HTMLをファイルに保存
            with open(html_file_path, "w", encoding="utf-8") as f:
                f.write(html)

            # 現在のHTMLのハッシュ値を取得
            current_html_hash = calculate_hash.calculate_hash(html_file_path)

            # ハッシュ値を比較して変更を検出
            if current_html_hash != previous_html_hash:
                html_changed["A"] = True
                html_changed["H"] = True

            # 前回の順位を読み込み
            saved_ranks = await self.load_tsukuba_student_rank(
                TSUKUBA_STUDENT_RANK_FILE
            )

            # Aコンテストの処理
            description_a, grade_ranks_a = await self.process_grade_ranks(
                "A", season_suffix, saved_ranks, html_changed["A"]
            )
            url_a = f"https://img.atcoder.jp/ajl{YEAR}{season_suffix}/school_rankings_grades_1to3_A.html"
            embed_a = discord.Embed(
                title="アルゴリズム",
                description=description_a,
                color=discord.Color.blue(),
                url=url_a,
            )

            # Hコンテストの処理
            description_h, grade_ranks_h = await self.process_grade_ranks(
                "H", season_suffix, saved_ranks, html_changed["H"]
            )
            url_h = f"https://img.atcoder.jp/ajl{YEAR}{season_suffix}/school_rankings_grades_1to3_H.html"
            embed_h = discord.Embed(
                title="ヒューリスティック",
                description=description_h,
                color=discord.Color.blue(),
                url=url_h,
            )

            # HTMLに変更があった場合のみデータを更新
            if html_changed["A"] or html_changed["H"]:
                # 現在の順位を整形
                current_ranks = {
                    "A": {
                        f"grade{i + 1}": [
                            {"name": user_id, "rank": rank}
                            for rank, user_id in grade_ranks
                        ]
                        for i, grade_ranks in enumerate(grade_ranks_a)
                    },
                    "H": {
                        f"grade{i + 1}": [
                            {"name": user_id, "rank": rank}
                            for rank, user_id in grade_ranks
                        ]
                        for i, grade_ranks in enumerate(grade_ranks_h)
                    },
                    "P_A": saved_ranks["L_A"],
                    "P_H": saved_ranks["L_H"],
                    "L_A": {
                        f"grade{i + 1}": [
                            {"name": user_id, "rank": rank}
                            for rank, user_id in grade_ranks
                        ]
                        for i, grade_ranks in enumerate(grade_ranks_a)
                    },
                    "L_H": {
                        f"grade{i + 1}": [
                            {"name": user_id, "rank": rank}
                            for rank, user_id in grade_ranks
                        ]
                        for i, grade_ranks in enumerate(grade_ranks_h)
                    },
                }
                # データを保存
                await self.save_tsukuba_student_rank(
                    current_ranks, TSUKUBA_STUDENT_RANK_FILE
                )

            await interaction.followup.send(embeds=[embed_a, embed_h])

        except requests.RequestException as e:
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
