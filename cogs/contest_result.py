import discord
from discord import app_commands
from discord.ext import commands
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError
)
from pdf2image import convert_from_path
import os
os.environ['LD_LIBRARY_PATH'] = '/home/yuubinnkyoku/miniconda3/lib' + ':' + os.environ.get('LD_LIBRARY_PATH', '')
import requests
import urllib.parse
import re
import math
from time import sleep
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image

class Contest_result(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_rating_color(self, rating):
        """Rating に応じた色を返す"""
        if rating < 400:
            return {'red': 0.5, 'green': 0.5, 'blue': 0.5}  # 灰色
        elif rating < 800:
            return {'red': 0.47, 'green': 0.262, 'blue': 0.082}  # 茶色
        elif rating < 1200:
            return {'red': 0.215, 'green': 0.494, 'blue': 0.133}  # 緑色
        elif rating < 1600:
            return {'red': 0.337, 'green': 0.741, 'blue': 0.749}  # 水色
        elif rating < 2000:
            return {'red': 0, 'green': 0, 'blue': 0.960}  # 青色
        elif rating < 2400:
            return {'red': 0.752, 'green': 0.752, 'blue': 0.239}  # 黄色
        elif rating < 2800:
            return {'red': 0.937, 'green': 0.529, 'blue': 0.200}  # 橙色
        else:
            return {'red': 0.917, 'green': 0.200, 'blue': 0.137}  # 赤色

    async def connect_to_spreadsheet(self):
        """Google スプレッドシートに接続する"""
        try:
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=scopes
            )
            gc = gspread.authorize(credentials)
            print("接続完了")
            return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME),gc.open_by_key(SPREADSHEET_ID)
        except Exception as e:
            print(f"Error connecting to spreadsheet: {e}")
            raise e
        
    async def write_to_spreadsheet(self, worksheet, data, workbook):
        """スプレッドシートにデータを書き込む"""
        worksheet.clear()

        print("データ書き込み中…")

        # ヘッダー行とデータ行をまとめて書き込み
        worksheet.update([["順位", "ユーザー", "得点", "A", "B", "C", "D", "E", "F", "G", "perf", "レート変化"]] + data)

        # Rating とパフォに応じてセルの文字色を変更
        for i, row in enumerate(data):
            # Rating から色を取得
            rating_change_str = row[11]
            try:
                if rating_change_str != "-":
                    rating = int(rating_change_str.split("→")[1].split("(")[0].strip())
                    rating_color = await self.get_rating_color(rating) # 変数名を変更
                    if rating_color:
                        worksheet.format(f'B{i+2}', {'textFormat': {'foregroundColor': rating_color}})
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
                        worksheet.format(f'K{i+2}', {'textFormat': {'foregroundColor': performance_color}}) # パフォのセルに色を設定
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

                    requests = [
                        {
                            "updateCells": {
                                "start": {
                                    "sheetId": worksheet.id,
                                    "rowIndex": row_index + 1, # ヘッダー行があるので +1
                                    "columnIndex": col_index
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
                                                            "red": 0.29803923
                                                        },
                                                        "foregroundColorStyle": {
                                                            "rgbColor": {
                                                            "blue": 0.29803923, 
                                                            "green": 0.654902, 
                                                            "red": 0.29803923
                                                            }
                                                        },
                                                        "fontFamily": "MS PGothic"
                                                    },
                                                },
                                                "textFormatRuns": [
                                                    {
                                                        "format": {}  # 最初の部分はデフォルト
                                                    },
                                                    {
                                                        "startIndex": penalty_start,  # penalty 部分から赤色
                                                        "format": {
                                                            "foregroundColor": {
                                                                "red": 1
                                                            },
                                                            "foregroundColorStyle":{
                                                                "rgbColor":{
                                                                    "red": 1
                                                                }
                                                            }
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ],
                                "fields": "userEnteredValue,userEnteredFormat,textFormatRuns,userEnteredFormat.textFormat"
                            }
                        }
                    ]
                    workbook.batch_update({"requests": requests}) 
        print("データ書き込み完了")

    def login(self):
        """AtCoder にログインし、セッションを返す"""
        try:
            login_url = "https://atcoder.jp/login"
            session = requests.session()
            res = session.get(login_url)
            res.raise_for_status() # HTTPエラーをチェック
            revel_session = res.cookies.get_dict().get('REVEL_SESSION')

            if not revel_session:
                raise ValueError("REVEL_SESSION cookie not found")

            revel_session = urllib.parse.unquote(revel_session)
            csrf_token_match = re.search(r'csrf_token\:(.*)_TS', revel_session)
            if not csrf_token_match:
                raise ValueError("csrf_token not found in REVEL_SESSION")

            csrf_token = csrf_token_match.groups()[0].replace('\x00\x00', '')
            sleep(1)
            headers = {'content-type': 'application/x-www-form-urlencoded'}
            params = {
                'username': ATCODER_USERNAME,
                'password': ATCODER_PASSWORD,
                'csrf_token': csrf_token,
            }
            data = {
                'continue': 'https://atcoder.jp:443/home'
            }
            res = session.post(login_url, params=params, data=data, headers=headers)
            res.raise_for_status() # HTTPエラーをチェック
            return session
        except Exception as e:
            print(f"AtCoderログイン中にエラーが発生しました: {e}")
            return None

    async def get_task_list(self, contest_id):
        """コンテストIDから問題のリストを生成する"""
        # contest_number = int(contest_id[3:])  # abcXXX の XXX 部分を数値に変換
        return [f"{contest_id}_{chr(ord('a') + i)}" for i in range(7)]  # a から g までの問題


    async def get_contest_performance(self, contest_id):
        """コンテストのパフォーマンスを取得する"""
        url = f"https://raw.githubusercontent.com/key-moon/ac-predictor-data/refs/heads/master/results/{contest_id}.json"
        if True:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            performance_data = {}
            for item in data:
                performance_data[item['UserScreenName']] = (item['Performance'], item['OldRating'], item['NewRating'])

            return performance_data

    async def get_atcoder_results(self, contest_id):
        """コンテスト結果を取得する"""
        if True:
            session = self.login()
            if not session:
                raise ValueError("AtCoder へのログインに失敗しました。")


            url = f'https://atcoder.jp/contests/{contest_id}/standings/json'
            response = session.get(url)
            response.raise_for_status()
            data = response.json()

            # パフォーマンスデータを取得
            performance_data = await self.get_contest_performance(contest_id)

            # IsRated を取得
            is_rated = data.get('IsRated', True)

            results = []
            dennoh_rank = 1
            for row in data['StandingsData']:
                affiliation = row.get('Affiliation')
                if affiliation and '電子電脳技術研究会' in affiliation:
                    try:
                        user_name = row['UserScreenName']

                        if performance_data:
                            performance, old_rating, new_rating = performance_data.get(user_name, (None, None, None))
                        else:
                            performance, old_rating, new_rating = None, None, None

                        if performance is None:
                            performance = 0
                        elif performance <= 400 and is_rated:
                            true_performance = round(400 / (math.exp((400 - performance) / 400)))
                            performance = true_performance

                        rank = f"{dennoh_rank} ({row['Rank']})"
                        total_score = row['TotalResult']['Score'] / 100

                        if old_rating is not None and new_rating is not None:
                            rating_change = f"{old_rating} → {new_rating} ({new_rating - old_rating})"
                        else:
                            rating_change = "-"

                        task_results = row.get('TaskResults', {})
                        task_data = []
                        for task in await self.get_task_list(contest_id):
                            task_result = task_results.get(task)
                            if task_result:
                                try: # task_result の処理中に例外が発生する可能性があるため try-except で囲む
                                    # count = task_result['Count']
                                    penalty = task_result['Penalty']
                                    failure = task_result.get('Failure',0)
                                    if task_result['Score'] >= 1:
                                        score = task_result['Score'] // 100
                                        task_data.append(f"{score} ({penalty})" if penalty > 0 else f"{score}")
                                    elif task_result['Score'] == 0:
                                        task_data.append(f"({failure + penalty})")
                                    else:
                                        task_data.append(f"({penalty})")
                                except (KeyError, TypeError) as e: # task_result の処理中に発生する可能性のあるエラーをキャッチ
                                    print(f"Task result 処理中にエラーが発生しました: {e}, task_result: {task_result}")
                                    task_data.append("-") # エラーが発生した場合は "-" を追加
                            else:
                                task_data.append("-")

                        results.append([rank, user_name, total_score] + task_data + [performance, rating_change])
                        dennoh_rank += 1
                    except (KeyError, TypeError) as e: # row の処理中に発生する可能性のあるエラーをキャッチ
                        print(f"行の処理中にエラーが発生しました: {e}, row: {row}")
                        continue # エラーが発生した場合は次の行に進む
            return results
        
    async def generate_contest_result_image(self, contest_id='abc001'):
        """コンテスト結果の画像を生成する"""

        results = await self.get_atcoder_results(contest_id)
        if not results:
            print("なんかバグって数値取得できなかったわ")
            return None

        # スプレッドシートに書き込み
        print("接続中…")
        worksheet,workbook = self.connect_to_spreadsheet()
        await self.write_to_spreadsheet(worksheet, results , workbook)

        # 参加人数を取得
        num_participants = len(results) + 1 # ヘッダー行も含める

        # PDFとして出力 (URLを直接指定, rangeパラメータを動的に変更)
        pdf_url = f'https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=pdf' \
                f'&gid={worksheet.id}' \
                f'&ir=false&ic=false' \
                f'&r1=0&c1=0&r2={num_participants}&c2=12' \
                f'&portrait=false&scale=2&size=B5&fitw=true' \
                f'&horizontal_alignment=CENTER&vertical_alignment=CENTER' \
                f'&right_margin=0.00&left_margin=0.00&bottom_margin=0.00&top_margin=0.00'
        response = requests.get(pdf_url) 
        response.raise_for_status()

        # 保存先フォルダのパス
        output_dir = "pdf_and_png"  # Atcotify_v2 フォルダの中に作成する場合

        # フォルダが存在しない場合に作成
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        pdf_path = os.path.join(output_dir, f'{contest_id}.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(response.content)

        # PDF を PNG に変換
        try:
            print("変換中…")
            images = convert_from_path(pdf_path, poppler_path='/home/yuubinnkyoku/miniconda3/pkgs/poppler-24.04.0-hb6cd0d7_0/bin')
            print("変換完了")
            png_path = f'{contest_id}.png'
            images[0].save(png_path, 'PNG')

        except (PDFInfoNotInstalledError, PDFPageCountError, PDFSyntaxError) as e:
            print(f"PDF変換エラー: {e}")
        
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


    @app_commands.command(name="contest_result", description="コンテスト結果を表示します")
    @app_commands.describe(contest_id="コンテストID (例: abc001)")
    async def contest_result(self, interaction: discord.Interaction, contest_id: str):
        await interaction.response.defer()

        image_path = await self.generate_contest_result_image(contest_id)
        if image_path:
            with open(image_path, 'rb') as f:
                image_file = discord.File(f)
                embed = discord.Embed(title=f"{contest_id} のコンテスト結果", color=discord.Color.orange()) # オレンジ色
            embed.set_image(url=f"attachment://{image_path}")
            await interaction.followup.send(embed=embed, file=image_file)
        else:
            embed = discord.Embed(title="エラー", description="対象のデータが見つかりませんでした。", color=discord.Color.red()) # 赤色
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Contest_result(bot))