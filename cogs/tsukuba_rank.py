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

# TODO: 15分ごとにスクレイピングして更新があれば送信するようにする(studentも)
# TODO: 前回実行時と同じ場合に前々回順位が表示されない問題

# 環境変数から設定を読み込む
config = Config()
SEASON = config.season
YEAR = config.year

# 学校名略称yamlを読み込む
with open("asset/school_abbreviations.yaml", encoding="utf-8") as f:
    school_abbreviations = yaml.safe_load(f)

# HTMLファイル保存ディレクトリを '../html/' に設定
html_dir = "html/"

TSUKUBA_RANK_FILE = "asset/tsukuba_rank.yaml"
AJL_RANKING_BASE_URL = (
    f"https://img.atcoder.jp/ajl{YEAR}{{}}/school_rankings_grades_1to3_{{}}.html"
)


class Tsukuba_rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def save_tsukuba_rank(self, filename, data):
        """筑波大学附属中学校の順位とスコアをYAMLファイルに保存する"""
        with open(filename, "w", encoding="utf-8") as f:
            yaml.dump(
                data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )

    async def load_tsukuba_rank(self, filename):
        """筑波大学附属中学校の順位とスコアをYAMLファイルから読み込む"""
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data
        else:
            return {
                "A": {
                    "previous_rank": None,
                    "previous_score": None,
                    "last_rank": None,
                    "last_score": None,
                },
                "H": {
                    "previous_rank": None,
                    "previous_score": None,
                    "last_rank": None,
                    "last_score": None,
                },
            }

    @app_commands.command(
        name="tsukuba_rank",
        description="現在のAJLの筑波大学附属中学校の順位を表示します",
    )
    async def tsukuba_rank(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()  # レスポンスを遅らせても大丈夫にする

            # SEASON に応じて URL の末尾を決定
            season_suffix = "winter" if SEASON == "WINTER" else "summer"

            # 前回のハッシュ値を取得（ファイルが存在しない場合はNone）
            try:
                previous_html_hash_school = calculate_hash.calculate_hash(
                    os.path.join(html_dir, f"ajl_ranking_{season_suffix}_A.html")
                )
            except FileNotFoundError:
                previous_html_hash_school = None
            try:
                previous_html_hash_school_h = calculate_hash.calculate_hash(
                    os.path.join(html_dir, f"ajl_ranking_{season_suffix}_H.html")
                )
            except FileNotFoundError:
                previous_html_hash_school_h = None

            embed_a = None
            embed_h = None

            # コンテスト種別ごとに処理
            for contest_type in ["A", "H"]:
                url = AJL_RANKING_BASE_URL.format(season_suffix, contest_type)
                response = requests.get(url)
                response.raise_for_status()
                response.encoding = "utf-8"
                html = response.text

                # HTMLファイルを保存
                html_file_path = os.path.join(
                    html_dir, f"ajl_ranking_{season_suffix}_{contest_type}.html"
                )
                with open(html_file_path, "w", encoding="utf-8") as f:
                    f.write(html)

                # ハッシュ値を計算
                current_html_hash = calculate_hash.calculate_hash(html_file_path)

                # 前回のハッシュ値と比較
                if contest_type == "A":
                    previous_hash = previous_html_hash_school
                else:
                    previous_hash = previous_html_hash_school_h

                df = pd.read_html(StringIO(html), encoding="utf-8")[0]
                df = df[df["学校名"] != "学校名"]
                tsukuba_row = df[df["学校名"] == "筑波大学附属中学校"]

                if not tsukuba_row.empty:
                    tsukuba_rank = tsukuba_row.index[0]
                    current_rank = int(tsukuba_row.iloc[0, 0])
                    current_score = int(tsukuba_row.iloc[0, 3])

                    # 前回のデータを取得
                    previous_data = await self.load_tsukuba_rank(TSUKUBA_RANK_FILE)
                    previous_rank = previous_data[contest_type]["previous_rank"]
                    previous_score = previous_data[contest_type]["previous_score"]
                    last_rank = previous_data[contest_type]["last_rank"]
                    last_score = previous_data[contest_type]["last_score"]

                    # 順位とスコアの比較のための説明文生成
                    description = "# "
                    if current_html_hash != previous_hash or previous_rank is None:
                        if previous_rank is not None:
                            description += f"{last_rank}位→**||{current_rank}||位**\n"
                        else:
                            description += f"**||{current_rank}||位**\n"
                    else:
                        if previous_rank is not None:
                            description += (
                                f"{previous_rank}位→**||{current_rank}||位**\n"
                            )
                        else:
                            description += f"**||{current_rank}||位**\n"

                    # 上の学校とのスコア差を計算
                    if tsukuba_rank > 0:
                        above_row = df.iloc[tsukuba_rank - 1]
                        above_school = above_row["学校名"]
                        above_school_abbr = school_abbreviations.get(
                            above_school, above_school
                        )
                        above_score = int(above_row["スコア"])
                        score_diff = above_score - current_score
                        description += (
                            f"> **{above_school_abbr}**まであと**{score_diff}**点！"
                        )
                    else:
                        description += "> 現在トップです！"

                    # スコア変動
                    score_change = 0
                    if previous_score is not None and last_score is not None:
                        if current_html_hash != previous_hash:
                            score_change = current_score - last_score
                        else:
                            score_change = current_score - previous_score
                        description += f"\n# {current_score}点\n> 前回より**{score_change}点**増えました！"
                    else:
                        description += f"\n# {current_score}点"

                    # Embedを作成
                    embed = discord.Embed(
                        title="アルゴリズム"
                        if contest_type == "A"
                        else "ヒューリスティック",
                        description=description,
                        color=discord.Color.blue(),
                    )
                    if contest_type == "A":
                        embed_a = embed
                    else:
                        embed_h = embed

                    # HTMLに更新があった場合、順位・スコアの変更にかかわらず更新する
                    if current_html_hash != previous_hash:
                        previous_data[contest_type]["previous_rank"] = last_rank
                        previous_data[contest_type]["previous_score"] = last_score
                        previous_data[contest_type]["last_rank"] = current_rank
                        previous_data[contest_type]["last_score"] = current_score
                        await self.save_tsukuba_rank(TSUKUBA_RANK_FILE, previous_data)

            # 有効なEmbedのみをリストに追加
            embeds_to_send = []
            if embed_a is not None:
                embeds_to_send.append(embed_a)
            if embed_h is not None:
                embeds_to_send.append(embed_h)
                
            # 少なくとも1つのEmbedがある場合のみ送信
            if embeds_to_send:
                await interaction.followup.send(embeds=embeds_to_send)
            else:
                # どちらのEmbedもNoneの場合はエラーメッセージを表示
                error_embed = discord.Embed(
                    title="エラー",
                    description="順位データを取得できませんでした。",
                    color=discord.Color.red(),
                )
                await interaction.followup.send(embed=error_embed)

        except requests.exceptions.RequestException as e:
            embed = discord.Embed(
                title="エラー",
                description=f"順位表の取得中にエラーが発生しました: {e}",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="エラー",
                description=f"エラーが発生しました: {e}",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tsukuba_rank(bot))
