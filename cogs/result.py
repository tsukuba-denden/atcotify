# cogs/result.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError,
)
from pdf2image import convert_from_path
import os
import requests
import urllib.parse
import re
import math
from time import sleep
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image
import yaml
from env.config import Config
import datetime
import asyncio
import traceback

config = Config()

SERVICE_ACCOUNT_FILE = config.google_service_account_file
SPREADSHEET_ID = config.google_spreadsheet_id
SHEET_NAME = config.google_sheet_name
ATCODER_USERNAME = config.atcoder_username
ATCODER_PASSWORD = config.atcoder_password

RESULTS_CONFIG_FILE = "asset/results_config.yaml"
CONTESTS_FILE = "asset/contests.yaml"


class Contest_result(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.results_config = self.load_results_config()
        self.contests = self.load_contests()
        self.check_contest_end.start()

    def load_results_config(self):
        """結果送信チャンネル設定をYAMLファイルから読み込む"""
        if os.path.exists(RESULTS_CONFIG_FILE):
            with open(RESULTS_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                if config is None:
                    return {}
                return config
        return {}

    def save_results_config(self, config):
        """結果送信チャンネル設定をYAMLファイルに保存する"""
        with open(RESULTS_CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                config, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )

    def load_contests(self):
        """コンテスト情報をYAMLファイルから読み込む"""
        if os.path.exists(CONTESTS_FILE):
            with open(CONTESTS_FILE, "r", encoding="utf-8") as f:
                contests = yaml.safe_load(f)
                if contests is None:
                    return []
                return contests
        return []

    def save_contests(self, contests):
        """コンテスト情報をYAMLファイルに保存する"""
        with open(CONTESTS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(
                contests,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    async def get_rating_color(self, rating):
        """Rating に応じた色を返す"""
        if rating < 400:
            return {"red": 0.5, "green": 0.5, "blue": 0.5}  # 灰色
        elif rating < 800:
            return {"red": 0.47, "green": 0.262, "blue": 0.082}  # 茶色
        elif rating < 1200:
            return {"red": 0.215, "green": 0.494, "blue": 0.133}  # 緑色
        elif rating < 1600:
            return {"red": 0.337, "green": 0.741, "blue": 0.749}  # 水色
        elif rating < 2000:
            return {"red": 0, "green": 0, "blue": 0.960}  # 青色
        elif rating < 2400:
            return {"red": 0.752, "green": 0.752, "blue": 0.239}  # 黄色
        elif rating < 2800:
            return {"red": 0.937, "green": 0.529, "blue": 0.200}  # 橙色
        else:
            return {"red": 0.917, "green": 0.200, "blue": 0.137}  # 赤色

    async def connect_to_spreadsheet(self):
        """Google スプレッドシートに接続する"""
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            credentials = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=scopes
            )
            gc = gspread.authorize(credentials)
            print("接続完了")
            return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME), gc.open_by_key(
                SPREADSHEET_ID
            )
        except Exception as e:
            print(f"Error connecting to spreadsheet: {e}")
            raise e

    async def write_to_spreadsheet(self, worksheet, data, workbook):
        """スプレッドシートにデータを書き込む"""
        worksheet.clear()

        print("データ書き込み中…")

        # ヘッダー行とデータ行をまとめて書き込み
        worksheet.update(
            [
                [
                    "順位",
                    "ユーザー",
                    "得点",
                    "A",
                    "B",
                    "C",
                    "D",
                    "E",
                    "F",
                    "G",
                    "perf",
                    "レート変化",
                ]
            ]
            + data
        )

        # Rating とパフォに応じてセルの文字色を変更
        for i, row in enumerate(data):
            # Rating から色を取得
            rating_change_str = row[11]
            try:
                if rating_change_str != "-":
                    rating = int(rating_change_str.split("→")[1].split("(")[0].strip())
                    rating_color = await self.get_rating_color(rating)  # 変数名を変更
                    if rating_color:
                        worksheet.format(
                            f"B{i + 2}",
                            {"textFormat": {"foregroundColor": rating_color}},
                        )
            except (ValueError, IndexError) as e:
                print(f"Rating の取得中にエラーが発生しました: {e}")
                continue

            # パフォから色を取得
            performance = row[10]
            try:
                if performance != "-":
                    performance = int(performance)
                    performance_color = await self.get_rating_color(performance)
                    if performance_color:
                        worksheet.format(
                            f"K{i + 2}",
                            {"textFormat": {"foregroundColor": performance_color}},
                        )  # パフォのセルに色を設定
            except (ValueError, TypeError) as e:
                print(f"パフォの取得中にエラーが発生しました: {e}")
                continue

        # penalty 部分だけを赤くする
        start_col = 3  # penalty 部分の開始列 (A=0, B=1, ...)
        end_col = 9  # penalty 部分の終了列
        for row_index, row_data in enumerate(data):
            for col_index in range(start_col, end_col + 1):
                cell_value = row_data[col_index]
                if cell_value != "-" and "(" in cell_value and ")" in cell_value:
                    # penalty 部分の開始位置を取得
                    penalty_start = cell_value.find("(")

                    requests_body = {  # requestsのbody引数に辞書を渡すように修正
                        "updateCells": {
                            "start": {
                                "sheetId": worksheet.id,
                                "rowIndex": row_index + 1,  # ヘッダー行があるので +1
                                "columnIndex": col_index,
                            },
                            "rows": [
                                {
                                    "values": [
                                        {
                                            "userEnteredValue": {
                                                "stringValue": cell_value
                                            },
                                            "userEnteredFormat": {
                                                "textFormat": {
                                                    "foregroundColor": {
                                                        "blue": 0.29803923,
                                                        "green": 0.654902,
                                                        "red": 0.29803923,
                                                    },
                                                    "foregroundColorStyle": {
                                                        "rgbColor": {
                                                            "blue": 0.29803923,
                                                            "green": 0.654902,
                                                            "red": 0.29803923,
                                                        }
                                                    },
                                                    "fontFamily": "MS PGothic",
                                                },
                                            },
                                            "textFormatRuns": [
                                                {
                                                    "format": {}  # 最初の部分はデフォルト
                                                },
                                                {
                                                    "startIndex": penalty_start,  # penalty 部分から赤色
                                                    "format": {
                                                        "foregroundColor": {"red": 1},
                                                        "foregroundColorStyle": {
                                                            "rgbColor": {"red": 1}
                                                        },
                                                    },
                                                },
                                            ],
                                        }
                                    ]
                                }
                            ],
                            "fields": "userEnteredValue,userEnteredFormat,textFormatRuns,userEnteredFormat.textFormat",
                        }
                    }
                    workbook.batch_update(
                        {"requests": [requests_body]}
                    )  # リストで囲むように修正
        print("データ書き込み完了")

    def login(self):
        """AtCoder にログインし、セッションを返す"""
        try:
            login_url = "https://atcoder.jp/login"
            session = requests.session()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }  # User-Agent を追加
            res = session.get(login_url, headers=headers)  # headers を追加
            res.raise_for_status()  # HTTPエラーをチェック
            revel_session = res.cookies.get_dict().get("REVEL_SESSION")

            if not revel_session:
                raise ValueError("REVEL_SESSION cookie not found")

            revel_session = urllib.parse.unquote(revel_session)
            csrf_token_match = re.search(r"csrf_token\:(.*)_TS", revel_session)
            if not csrf_token_match:
                raise ValueError("csrf_token not found in REVEL_SESSION")

            csrf_token = csrf_token_match.groups()[0].replace("\x00\x00", "")
            sleep(1)
            headers = {
                "content-type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            }  # content-type と User-Agent を設定
            params = {
                "username": ATCODER_USERNAME,
                "password": ATCODER_PASSWORD,
                "csrf_token": csrf_token,
            }  # params に username, password, csrf_token を設定
            data = {
                "continue": "https://atcoder.jp:443/home"
            }  # data に continue を設定
            res = session.post(login_url, params=params, data=data, headers=headers) # params, data, headers を設定
            res.raise_for_status() # HTTPエラーをチェック
            return session
        except requests.exceptions.HTTPError as e: # HTTPError をキャッチ
            print(f"AtCoderログイン中にHTTPエラーが発生しました: {e}")
            if e.response is not None:
                print(f"レスポンスステータスコード: {e.response.status_code}")
                print(f"レスポンスヘッダー: {e.response.headers}")
                print(f"レスポンス内容: {e.response.content.decode('utf-8', errors='ignore')}") # レスポンス内容を出力 (decodeとerrors='ignore'を追加)
            return None
        except Exception as e:
            print(f"AtCoderログイン中にエラーが発生しました: {e}")
            return None

    async def get_task_list(self, contest_id):
        """コンテストIDから問題のリストを生成する"""
        # contest_number = int(contest_id[3:])  # abcXXX の XXX 部分を数値に変換
        return [
            f"{contest_id}_{chr(ord('a') + i)}" for i in range(7)
        ]  # a から g までの問題

    async def get_contest_performance(self, contest_id):
        """コンテストのパフォーマンスを取得する"""
        url = f"https://raw.githubusercontent.com/key-moon/ac-predictor-data/refs/heads/master/results/{contest_id}.json"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            performance_data = {}
            for item in data:
                performance_data[item["UserScreenName"]] = (
                    item["Performance"],
                    item["OldRating"],
                    item["NewRating"],
                )

            return performance_data
        except requests.exceptions.RequestException as e:
            print(f"パフォーマンスデータの取得に失敗しました ({contest_id}): {e}")
            return {}

    async def get_atcoder_results(self, contest_id):
        """コンテスト結果を取得する"""
        try:
            session = self.login()
            if not session:
                raise ValueError("AtCoder へのログインに失敗しました。")

            url = f"https://atcoder.jp/contests/{contest_id}/standings/json"
            response = session.get(url)
            response.raise_for_status()
            data = response.json()

            # パフォーマンスデータを取得
            performance_data = await self.get_contest_performance(contest_id)

            # IsRated を取得
            is_rated = data.get("IsRated", True)

            results = []
            dennoh_rank = 1
            for row in data["StandingsData"]:
                affiliation = row.get("Affiliation")
                if affiliation and "電子電脳技術研究会" in affiliation:
                    try:
                        user_name = row["UserScreenName"]

                        if performance_data:
                            performance, old_rating, new_rating = performance_data.get(
                                user_name, (None, None, None)
                            )
                        else:
                            performance, old_rating, new_rating = None, None, None

                        if performance is None:
                            performance = (
                                "-"  # パフォーマンスが取得できない場合は "-" を設定
                            )
                        elif performance <= 400 and is_rated:
                            true_performance = round(
                                400 / (math.exp((400 - performance) / 400))
                            )
                            performance = true_performance

                        rank = f"{dennoh_rank} ({row['Rank']})"
                        total_score = row["TotalResult"]["Score"] / 100

                        if old_rating is not None and new_rating is not None:
                            rating_change = f"{old_rating} → {new_rating} ({new_rating - old_rating})"
                        else:
                            rating_change = "-"

                        task_results = row.get("TaskResults", {})
                        task_data = []
                        for task in await self.get_task_list(contest_id):
                            task_result = task_results.get(task)
                            if task_result:
                                try:  # task_result の処理中に例外が発生する可能性があるため try-except で囲む
                                    # count = task_result['Count']
                                    penalty = task_result["Penalty"]
                                    failure = task_result.get("Failure", 0)
                                    if task_result["Score"] >= 1:
                                        score = task_result["Score"] // 100
                                        task_data.append(
                                            f"{score} ({penalty})"
                                            if penalty > 0
                                            else f"{score}"
                                        )
                                    elif task_result["Score"] == 0:
                                        task_data.append(f"({failure + penalty})")
                                    else:
                                        task_data.append(f"({penalty})")
                                except (
                                    KeyError,
                                    TypeError,
                                ) as e:  # task_result の処理中に発生する可能性のあるエラーをキャッチ
                                    print(
                                        f"Task result 処理中にエラーが発生しました: {e}, task_result: {task_result}"
                                    )
                                    task_data.append(
                                        "-"
                                    )  # エラーが発生した場合は "-" を追加
                            else:
                                task_data.append("-")

                        results.append(
                            [rank, user_name, total_score]
                            + task_data
                            + [performance, rating_change]
                        )
                        dennoh_rank += 1
                    except (
                        KeyError,
                        TypeError,
                    ) as e:  # row の処理中に発生する可能性のあるエラーをキャッチ
                        print(f"行の処理中にエラーが発生しました: {e}, row: {row}")
                        continue  # エラーが発生した場合は次の行に進む
            return results
        except Exception as e:
            print(f"AtCoder results の取得に失敗しました ({contest_id}): {e}")
            return None

    async def generate_contest_result_image(self, contest_id="abc001"):
        """コンテスト結果の画像を生成する"""

        results = await self.get_atcoder_results(contest_id)
        if not results:
            print("なんかバグって数値取得できなかったわ")
            return None

        # スプレッドシートに書き込み
        print("接続中…")
        worksheet, workbook = await self.connect_to_spreadsheet()  # await を追加
        await self.write_to_spreadsheet(worksheet, results, workbook)

        # 参加人数を取得
        num_participants = len(results) + 1  # ヘッダー行も含める

        # PDFとして出力 (URLを直接指定, rangeパラメータを動的に変更)
        pdf_url = (
            f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=pdf"
            f"&gid={worksheet.id}"
            f"&ir=false&ic=false"
            f"&r1=0&c1=0&r2={num_participants}&c2=12"
            f"&portrait=false&scale=2&size=B5&fitw=true"
            f"&horizontal_alignment=CENTER&vertical_alignment=CENTER"
            f"&right_margin=0.00&left_margin=0.00&bottom_margin=0.00&top_margin=0.00"
        )
        try:
            response = requests.get(pdf_url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"PDFダウンロードに失敗しました ({contest_id}): {e}")
            return None

        # 保存先フォルダのパス
        output_dir = "pdf_and_png"  # Atcotify_v2 フォルダの中に作成する場合

        # フォルダが存在しない場合に作成
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        pdf_path = os.path.join(output_dir, f"{contest_id}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(response.content)

        # PDF を PNG に変換
        try:
            print("変換中…")
            images = convert_from_path(
                pdf_path, poppler_path="C:/Program Files/poppler-24.08.0/Library/bin"
            )  # popplerのパスを指定
            print("変換完了")
            png_path = os.path.join(
                output_dir, f"{contest_id}.png"
            )  # pdf_and_pngフォルダの中に保存
            images[0].save(png_path, "PNG")

        except (PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError) as e:
            print(f"PDF変換エラー: {e}")
            return None

        # 画像の切り抜き
        try:
            img = Image.open(png_path)
            # 行数を取得
            num_rows = len(results)
            # 切り抜く高さを計算
            crop_height = 37.6 * num_rows
            cropped_img = img.crop((0, 0, img.width, crop_height))
            cropped_img.save(png_path)
            return png_path

        except Exception as e:
            print(f"画像切り抜きエラー: {e}")
            return None

    async def send_contest_result(self, contest, guild_id):
        """コンテスト結果を送信する"""
        contest_id = contest["url"].split("/")[-1]
        image_path = await self.generate_contest_result_image(contest_id)
        if image_path:
            try:
                channel_id = self.results_config.get(str(guild_id))
                if channel_id:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        with open(image_path, "rb") as f:
                            image_file = discord.File(f, filename=f"{contest_id}.png")
                        await channel.send(file=image_file) # 画像のみ送信
                        print(f"{contest['name']} のコンテスト結果を送信しました。")
                        return True
                    else:
                        print(f"結果送信チャンネルが見つかりません: {channel_id}")
                        return False
                else:
                    print(
                        f"サーバー {guild_id} の結果送信チャンネルが設定されていません。"
                    )
                    return False
            except Exception as e:
                print(f"コンテスト結果送信中にエラーが発生しました: {e}")
                return False
        else:
            print(f"{contest['name']} のコンテスト結果画像の生成に失敗しました。")
            return False

    @app_commands.command(
        name="result---contest_result", description="コンテスト結果を表示します"
    )
    @app_commands.describe(contest_id="コンテストID (例: abc001)")
    async def contest_result_command(
        self, interaction: discord.Interaction, contest_id: str
    ):
        await interaction.response.defer()  # defer を先に呼び出す
        await asyncio.sleep(2) # defer 後に少し待機 # sleep時間を1秒から2秒に延長

        image_path = await self.generate_contest_result_image(contest_id)
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    image_file = discord.File(f, filename=f"{contest_id}.png") # ファイル名を指定
                await interaction.followup.send(file=image_file) # 画像のみ送信
                embed = discord.Embed(title=f"{contest_id} のコンテスト結果", color=discord.Color.orange()) # タイトルのみのEmbed
                await interaction.followup.send(embed=embed) # タイトルEmbedを送信
            except Exception as e:
                print(f"コンテスト結果送信中にエラーが発生しました: {e}")
                traceback.print_exc()
                embed = discord.Embed(title="エラー", description="コンテスト結果の送信に失敗しました。", color=discord.Color.red()) # 赤色
                await interaction.followup.send(embed=embed)
        else:
            embed = discord.Embed(title="エラー", description="対象のデータが見つかりませんでした。", color=discord.Color.red()) # 赤色
            await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="result---set_channel",
        description="コンテスト結果を送信するチャンネルを設定",
    )
    async def set_result_channel(self, interaction: discord.Interaction):
        """リマインダー送信チャンネル設定コマンド"""
        guild_id = str(interaction.guild_id)
        view = ResultChannelSelectView(self, guild_id)  # ChannelSelectView を使用
        await interaction.response.send_message(
            "コンテスト結果送信チャンネルを選択してください", view=view, ephemeral=False
        )

    @tasks.loop(minutes=1)
    async def check_contest_end(self):
        """コンテスト終了時刻をチェックし、結果を自動送信する"""
        now = datetime.datetime.now()
        updated_contests = []
        for contest in self.contests:
            end_time = datetime.datetime.strptime(
                contest["end_time"], "%Y-%m-%d %H:%M:%S"
            )
            if end_time <= now and not contest.get("result_sent", False):
                guild_ids = self.results_config.keys()
                sent_to_any_guild = False
                for guild_id in guild_ids:
                    if await self.send_contest_result(contest, guild_id):
                        sent_to_any_guild = True
                if sent_to_any_guild:
                    contest["result_sent"] = True
                    print(f"{contest['name']} のコンテスト結果の自動送信処理完了。")
                else:
                    print(f"{contest['name']} のコンテスト結果の自動送信に失敗。")
            updated_contests.append(contest)
        if updated_contests != self.contests:
            self.contests = updated_contests
            self.save_contests(self.contests)

    @check_contest_end.before_loop
    async def before_check_contest_end(self):
        await self.bot.wait_until_ready()


class ResultChannelSelectView(discord.ui.View):  # ChannelSelect 用の View を作成
    def __init__(self, cog: Contest_result, guild_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.results_config = self.cog.results_config

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="チャンネルを選択してください",
        custom_id="result_channel_select",
    )
    async def select_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ):
        channel_id = select.values[0].id
        self.results_config[self.guild_id] = str(channel_id)
        self.cog.save_results_config(self.results_config)
        channel_mention = f"<#{channel_id}>"
        embed = discord.Embed(
            title="コンテスト結果送信チャンネル設定完了！",
            description=f"コンテスト結果送信チャンネルを {channel_mention} に設定しました！",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Contest_result(bot))
