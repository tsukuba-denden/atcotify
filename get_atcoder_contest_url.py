import datetime

def get_atcoder_contest_url():
    # 基準日時
    base_datetime = datetime(2024, 6, 15, 22, 40, 0)
    # 現在日時
    now = datetime.now()

    # 基準日時からの経過週数を計算
    weeks_since_base = (now - base_datetime).days // 7

    # コンテスト番号を計算
    contest_number = 359 + weeks_since_base

    # URLを生成
    contest_url = f"https://atcoder.jp/contests/abc{contest_number}"

    return contest_url