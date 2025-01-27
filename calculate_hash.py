import hashlib


def calculate_hash(filename):
    """ファイルのハッシュ値を計算する"""
    with open(filename, "rb") as f:
        file_content = f.read()
    return hashlib.md5(file_content).hexdigest()