import os
from io import StringIO
import json # 追加

import discord
import pandas as pd
import requests
import yaml
from discord import app_commands
from discord.ext import commands, tasks # tasks を追加

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
BOT_SETTINGS_FILE = "bot_settings.json" # 追加


class Tsukuba_rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_tsukuba_rank_loop.start() # ループ処理を開始

    def cog_unload(self):
        self.check_tsukuba_rank_loop.cancel() # コグがアンロードされるときにループをキャンセル

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

    async def get_tsukuba_rank_data(self):
        """筑波大学附属中学校の順位データを取得する"""
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

        embeds = []
        updated_data = await self.load_tsukuba_rank(TSUKUBA_RANK_FILE)
        changed = False

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
                tsukuba_rank_index = tsukuba_row.index[0] # インデックス名を変更
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
                if tsukuba_rank_index > 0: # 変数名を変更
                    above_row = df.iloc[tsukuba_rank_index - 1] # 変数名を変更
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
                embed_url = f"https://img.atcoder.jp/ajl{YEAR}{season_suffix}/school_rankings_grades_1to3_{contest_type}.html"
                embed = discord.Embed(
                    title="アルゴリズム"
                    if contest_type == "A"
                    else "ヒューリスティック",
                    description=description,
                    color=discord.Color.blue(),
                    url=embed_url,
                )
                embeds.append(embed)


                # HTMLに更新があった場合、順位・スコアの変更にかかわらず更新する
                if current_html_hash != previous_hash:
                    updated_data[contest_type]["previous_rank"] = last_rank
                    updated_data[contest_type]["previous_score"] = last_score
                    updated_data[contest_type]["last_rank"] = current_rank
                    updated_data[contest_type]["last_score"] = current_score
                    changed = True
        
        if changed:
            await self.save_tsukuba_rank(TSUKUBA_RANK_FILE, updated_data)
        
        return embeds, changed

    @app_commands.command(
        name="tsukuba_rank", # 元に戻す
        description="現在のAJLの筑波大学附属中学校の順位を表示します",
    )
    async def tsukuba_rank(self, interaction: discord.Interaction): # メソッド名を元に戻す
        try:
            await interaction.response.defer()  # レスポンスを遅らせても大丈夫にする
            embeds, _ = await self.get_tsukuba_rank_data() # changed を無視

            if embeds:
                await interaction.followup.send(embeds=embeds)
            else:
                await interaction.followup.send("筑波大学附属中学校のデータが見つかりませんでした。")

        except requests.RequestException as e: # 変更
            print(f"Error fetching data: {e}")
            await interaction.followup.send(
                "データの取得中にエラーが発生しました。しばらくしてからもう一度お試しください。"
            )
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            await interaction.followup.send("予期せぬエラーが発生しました。")

    @tasks.loop(minutes=15)
    async def check_tsukuba_rank_loop(self):
        """15分ごとに筑波大学附属中学校の順位を確認し、変更があれば通知する"""
        print("Checking Tsukuba Rank...")
        try:
            # Call get_tsukuba_rank_data before the loop
            embeds, changed = await self.get_tsukuba_rank_data()

            with open(BOT_SETTINGS_FILE, "r") as f:
                settings = json.load(f)
            
            guild_ids = [guild.id for guild in self.bot.guilds]

            for guild_id in guild_ids:
                guild_settings = settings.get(str(guild_id))
                if guild_settings:
                    channel_id = guild_settings.get("tsukuba_rank_channel_id")
                    if channel_id:
                        channel = self.bot.get_channel(int(channel_id))
                        if channel:
                            # Use stored embeds and changed values
                            if changed and embeds:
                                await channel.send(embeds=embeds)
                                print(f"Tsukuba Rank updated and sent to guild {guild_id}.")
                            elif not embeds:
                                print(f"Tsukuba Rank data not found for guild {guild_id}.")
                            else:
                                print(f"No changes in Tsukuba Rank for guild {guild_id}.")
                        else:
                            print(f"Channel with ID {channel_id} not found in guild {guild_id}.")
                    # else: # チャンネルIDが設定されていない場合、何もしない
                    #     print(f"Tsukuba rank channel not set for guild {guild_id}.") 
                # else: # サーバーの設定が存在しない場合、何もしない
                #    print(f"Settings not found for guild {guild_id}.")

        except FileNotFoundError:
            print(f"{BOT_SETTINGS_FILE} not found.")
        except Exception as e:
            print(f"Error in check_tsukuba_rank_loop: {e}")
    
    @check_tsukuba_rank_loop.before_loop
    async def before_check_tsukuba_rank_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="tsukuba_rank---set_ch",
        description="筑波大学附属中学校の順位通知チャンネルを設定します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tsukuba_rank_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        try:
            guild_id = str(interaction.guild_id)
            with open(BOT_SETTINGS_FILE, "r+") as f:
                settings = json.load(f)
                if guild_id not in settings:
                    settings[guild_id] = {}
                settings[guild_id]["tsukuba_rank_channel_id"] = str(channel.id)
                f.seek(0)
                json.dump(settings, f, indent=4)
                f.truncate()
            embed = discord.Embed(
                title="設定完了",
                description=f"筑波大学附属中学校の順位通知チャンネルを {channel.mention} に設定しました。",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="エラー",
                description=f"エラーが発生しました: {e}",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="tsukuba_rank---unset_ch",
        description="筑波大学附属中学校の順位通知チャンネルを解除します。",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tsukuba_rank_unset_channel(self, interaction: discord.Interaction):
        try:
            guild_id = str(interaction.guild_id)
            with open(BOT_SETTINGS_FILE, "r+") as f:
                settings = json.load(f)
                if guild_id in settings and "tsukuba_rank_channel_id" in settings[guild_id]:
                    del settings[guild_id]["tsukuba_rank_channel_id"]
                    if not settings[guild_id]: # 他に設定がなければサーバーIDごと削除
                        del settings[guild_id]
                    f.seek(0)
                    json.dump(settings, f, indent=4)
                    f.truncate()
                    embed = discord.Embed(
                        title="設定解除",
                        description="筑波大学附属中学校の順位通知チャンネルを解除しました。",
                        color=discord.Color.green(),
                    )
                    await interaction.response.send_message(embed=embed)
                else:
                    embed = discord.Embed(
                        title="情報",
                        description="筑波大学附属中学校の順位通知チャンネルは設定されていません。",
                        color=discord.Color.blue(),
                    )
                    await interaction.response.send_message(embed=embed)
        except Exception as e:
            embed = discord.Embed(
                title="エラー",
                description=f"エラーが発生しました: {e}",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Tsukuba_rank(bot))
