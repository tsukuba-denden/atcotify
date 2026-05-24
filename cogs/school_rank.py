from dataclasses import dataclass
import hashlib
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
import zipfile

import discord
import pandas as pd
import requests
import yaml
from discord import app_commands
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

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
AJL_PERSONAL_RANKING_BASE_URL = (
    f"https://img.atcoder.jp/ajl{YEAR}{{}}/grade_{{}}_rankings_{{}}_{{}}.html"
)
CONTEST_TYPES = ("A", "H")
SCHOOL_TYPES = ("junior_high", "high")
MAX_SEARCH_RESULT_EMBEDS = 10
CONTEST_LABELS = {"A": "アルゴリズム", "H": "ヒューリスティック"}
CONTEST_DETAIL_LIMITS = {"A": 6, "H": 4}
META_COLUMNS = {"順位", "ユーザID", "学校名", "都道府県", "学年", "スコア"}
USER_RATING_CACHE: dict[str, int | None] = {}
LINE_SEED_JP_DOWNLOAD_URL = "https://seed.line.me/src/images/fonts/LINE_Seed_JP.zip"
LINE_SEED_JP_FONT_DIR = Path("font_cache/line_seed_jp")
LINE_SEED_JP_FONT_NAMES = (
    "LINESeedJP_OTF_Bd.otf",
    "LINESeedJP_OTF_Rg.otf",
    "LINESeedJP_TTF_Bd.ttf",
    "LINESeedJP_TTF_Rg.ttf",
)
GRAPH_FONT_NAMES_BY_WEIGHT = {
    "bold": (
        "LINESeedJP_OTF_Bd.otf",
        "LINESeedJP_TTF_Bd.ttf",
    ),
    "regular": (
        "LINESeedJP_OTF_Rg.otf",
        "LINESeedJP_TTF_Rg.ttf",
    ),
}
LINE_SEED_JP_DOWNLOAD_ATTEMPTED = False


@dataclass(frozen=True)
class SchoolRankImage:
    filename: str
    data: bytes


@dataclass(frozen=True)
class SchoolRankMessagePart:
    embed: discord.Embed
    image: SchoolRankImage | None = None


@dataclass(frozen=True)
class ContestScore:
    contest_id: str
    score: int
    performance: int | None = None


@dataclass(frozen=True)
class ContributorScore:
    user_id: str
    score: int
    details: list[ContestScore]
    rating: int | None = None


def abbreviate_school_name(school_name: Any) -> Any:
    if isinstance(school_name, str):
        for full_name, abbreviation in school_abbreviations.items():
            if str(full_name).strip() == school_name.strip():
                return abbreviation
        if school_name.endswith("高等専門学校"):
            return school_name[:-6] + "高専"
        if school_name.endswith("高等学校"):
            return school_name[:-4] + "高校"
        if school_name.endswith("中学校"):
            return school_name[:-3]
    return school_name


def school_search_texts(school_name: str) -> set[str]:
    texts = {school_name}
    abbreviated = abbreviate_school_name(school_name)
    if isinstance(abbreviated, str):
        texts.add(abbreviated.strip())

    for full_name, abbreviation in school_abbreviations.items():
        if str(full_name).strip() == school_name:
            texts.add(str(abbreviation).strip())

    return {text for text in texts if text}


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


def grade_numbers(school_type: str) -> range:
    return range(4, 7) if normalize_school_type(school_type) == "high" else range(1, 4)


def grade_slot(grade: int, school_type: str) -> int:
    return grade - 3 if normalize_school_type(school_type) == "high" else grade


def html_file_path(contest_type: str, school_type: str) -> Path:
    return (
        HTML_DIR
        / f"ajl_ranking_{season_suffix()}_{school_grade_range(school_type)}_{contest_type}.html"
    )


def personal_html_file_path(
    contest_type: str,
    grade: int,
    school_type: str,
    score_kind: str = "score",
) -> Path:
    return (
        HTML_DIR
        / (
            f"personal_grade_{grade}_rankings_{contest_type}_"
            f"{season_suffix()}_{normalize_school_type(school_type)}_{score_kind}.html"
        )
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


def fetch_personal_rank_tables(
    school_type: str,
    score_kind: str = "score",
) -> tuple[dict[str, dict[int, pd.DataFrame]], dict[str, bool]]:
    if score_kind not in {"score", "perf"}:
        raise ValueError(f"Unsupported personal ranking kind: {score_kind}")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    school_type = normalize_school_type(school_type)
    frames: dict[str, dict[int, pd.DataFrame]] = {"A": {}, "H": {}}
    html_changed = {"A": False, "H": False}

    for contest_type in CONTEST_TYPES:
        for grade in grade_numbers(school_type):
            if grade_slot(grade, school_type) == 3 and SEASON == "WINTER":
                frames[contest_type][grade] = pd.DataFrame()
                continue

            path = personal_html_file_path(contest_type, grade, school_type, score_kind)
            try:
                previous_hash = calculate_hash.calculate_hash(str(path))
            except FileNotFoundError:
                previous_hash = None

            response = requests.get(
                AJL_PERSONAL_RANKING_BASE_URL.format(
                    season_suffix(), grade, contest_type, score_kind
                )
            )
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
                search_texts = school_search_texts(school_name)

                if query in search_texts:
                    exact_matches.append(school_key)
                elif any(query_lower in text.lower() for text in search_texts):
                    partial_matches.append(school_key)

    return exact_matches or partial_matches


def school_image_filename(school_name: str, school_type: str, contest_type: str) -> str:
    key = f"{normalize_school_type(school_type)}:{school_name}:{contest_type}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"school_rank_{contest_type}_{normalize_school_type(school_type)}_{digest}.png"


def line_seed_jp_font_paths(
    font_names: tuple[str, ...] = LINE_SEED_JP_FONT_NAMES,
) -> list[Path]:
    local_dirs = [
        Path("asset/fonts"),
        LINE_SEED_JP_FONT_DIR,
        Path("C:/Windows/Fonts"),
    ]
    return [directory / font_name for directory in local_dirs for font_name in font_names]


def ensure_line_seed_jp_fonts() -> None:
    global LINE_SEED_JP_DOWNLOAD_ATTEMPTED

    if LINE_SEED_JP_DOWNLOAD_ATTEMPTED:
        return
    if any(path.exists() for path in line_seed_jp_font_paths()):
        return

    LINE_SEED_JP_DOWNLOAD_ATTEMPTED = True
    try:
        response = requests.get(
            LINE_SEED_JP_DOWNLOAD_URL,
            headers={"User-Agent": "atcotify school rank graph"},
            timeout=20,
        )
        response.raise_for_status()

        LINE_SEED_JP_FONT_DIR.mkdir(parents=True, exist_ok=True)
        wanted_names = set(LINE_SEED_JP_FONT_NAMES)
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            for member in archive.infolist():
                font_name = Path(member.filename).name
                if font_name not in wanted_names:
                    continue
                target_path = LINE_SEED_JP_FONT_DIR / font_name
                with archive.open(member) as source, target_path.open("wb") as target:
                    target.write(source.read())
    except Exception as e:
        print(f"Failed to download LINE Seed JP fonts: {e}")


def load_graph_font(
    size: int,
    weight: str = "regular",
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    ensure_line_seed_jp_fonts()
    line_seed_font_paths = line_seed_jp_font_paths(
        GRAPH_FONT_NAMES_BY_WEIGHT.get(weight, GRAPH_FONT_NAMES_BY_WEIGHT["regular"])
    )
    if weight == "bold":
        system_font_paths = [
            Path("C:/Windows/Fonts/meiryob.ttc"),
            Path("C:/Windows/Fonts/YuGothB.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]
    else:
        system_font_paths = [
            Path("C:/Windows/Fonts/meiryo.ttc"),
            Path("C:/Windows/Fonts/YuGothR.ttc"),
            Path("C:/Windows/Fonts/msgothic.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    font_paths = [
        *line_seed_font_paths,
        *system_font_paths,
    ]
    for font_path in font_paths:
        if font_path.exists():
            return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()


def to_int_score(value: Any) -> int:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0).iloc[0]
    return max(0, int(float(numeric)))


def to_optional_int(value: Any) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(float(numeric))


def fetch_user_rating(user_id: str) -> int | None:
    if user_id in USER_RATING_CACHE:
        return USER_RATING_CACHE[user_id]

    try:
        response = requests.get(
            f"https://atcoder.jp/users/{user_id}/history/json",
            headers={"User-Agent": "atcotify school rank graph"},
            timeout=8,
        )
        response.raise_for_status()
        history = response.json()
        rating = None
        if history:
            rating = int(history[-1]["NewRating"])
        USER_RATING_CACHE[user_id] = rating
        return rating
    except Exception as e:
        print(f"Failed to fetch AtCoder rating for {user_id}: {e}")
        USER_RATING_CACHE[user_id] = None
        return None


def rating_text_color(rating: int | None) -> tuple[int, int, int]:
    if rating is None or rating < 400:
        return (128, 128, 128)
    if rating < 800:
        return (128, 64, 0)
    if rating < 1200:
        return (0, 128, 0)
    if rating < 1600:
        return (0, 192, 192)
    if rating < 2000:
        return (0, 0, 255)
    if rating < 2400:
        return (192, 192, 0)
    if rating < 2800:
        return (255, 128, 0)
    return (255, 0, 0)


def soften_color(
    color: tuple[int, int, int],
    ratio: float = 0.82,
) -> tuple[int, int, int]:
    return tuple(int(channel * (1 - ratio) + 255 * ratio) for channel in color)


def performance_background_color(performance: int | None) -> tuple[int, int, int]:
    return soften_color(rating_text_color(performance), ratio=0.68)


def contest_score_columns(df: pd.DataFrame) -> list[Any]:
    columns = list(df.columns)
    if "スコア" in columns:
        return columns[columns.index("スコア") + 1 :]
    return [column for column in columns if str(column).strip() not in META_COLUMNS]


def extract_contributors(
    school_name: str,
    contest_type: str,
    personal_frames: dict[str, dict[int, pd.DataFrame]] | None,
    performance_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
) -> list[ContributorScore]:
    if personal_frames is None:
        return []

    contributors = []
    detail_limit = CONTEST_DETAIL_LIMITS[contest_type]
    for grade, df in personal_frames.get(contest_type, {}).items():
        if df.empty or not {"学校名", "ユーザID", "スコア"}.issubset(df.columns):
            continue

        performance_df = None
        if performance_frames is not None:
            performance_df = performance_frames.get(contest_type, {}).get(grade)
        score_columns = contest_score_columns(df)
        rows = df[(df["学校名"] == school_name) & df["ユーザID"].notna()]
        for _, row in rows.iterrows():
            user_id = str(row["ユーザID"]).strip()
            if not user_id or user_id == "ユーザID":
                continue

            performance_row = None
            if (
                performance_df is not None
                and not performance_df.empty
                and "ユーザID" in performance_df.columns
            ):
                matched_perf_rows = performance_df[performance_df["ユーザID"] == user_id]
                if not matched_perf_rows.empty:
                    performance_row = matched_perf_rows.iloc[0]

            details = []
            for column in score_columns:
                contest_id = str(column).strip()
                if not contest_id or contest_id.startswith("Unnamed"):
                    continue
                score = to_int_score(row[column])
                if score > 0:
                    performance = None
                    if (
                        performance_row is not None
                        and column in performance_row.index
                    ):
                        performance = to_optional_int(performance_row[column])
                    details.append(
                        ContestScore(
                            contest_id=contest_id,
                            score=score,
                            performance=performance,
                        )
                    )

            details.sort(key=lambda item: (-item.score, item.contest_id))
            contributors.append(
                ContributorScore(
                    user_id=user_id,
                    score=to_int_score(row["スコア"]),
                    details=details[:detail_limit],
                    rating=fetch_user_rating(user_id),
                )
            )

    contributors.sort(key=lambda item: (-item.score, item.user_id))
    return contributors


def draw_fit_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    max_width: int,
    font_size: int,
    fill: tuple[int, int, int],
    min_size: int = 10,
    weight: str = "regular",
) -> int:
    for size in range(font_size, min_size - 1, -1):
        font = load_graph_font(size, weight)
        if draw.textlength(text, font=font) <= max_width:
            draw.text(xy, text, font=font, fill=fill)
            return size

    font = load_graph_font(min_size, weight)
    clipped = text
    while clipped and draw.textlength(clipped + "...", font=font) > max_width:
        clipped = clipped[:-1]
    if clipped:
        draw.text(xy, clipped + "...", font=font, fill=fill)
    return min_size


def draw_fit_text_in_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    max_size: int,
    fill: tuple[int, int, int],
    min_size: int = 10,
    align: str = "left",
    weight: str = "regular",
) -> int:
    x0, y0, x1, y1 = box
    max_width = max(1, x1 - x0)
    max_height = max(1, y1 - y0)

    for size in range(max_size, min_size - 1, -1):
        font = load_graph_font(size, weight)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        if text_width <= max_width and text_height <= max_height:
            if align == "center":
                x = x0 + (max_width - text_width) / 2 - bbox[0]
            elif align == "right":
                x = x1 - text_width - bbox[0]
            else:
                x = x0 - bbox[0]
            y = y0 + (max_height - text_height) / 2 - bbox[1]
            draw.text((x, y), text, font=font, fill=fill)
            return size

    font = load_graph_font(min_size, weight)
    clipped = text
    while clipped:
        candidate = clipped + "..."
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            if align == "center":
                x = x0 + (max_width - text_width) / 2 - bbox[0]
            elif align == "right":
                x = x1 - text_width - bbox[0]
            else:
                x = x0 - bbox[0]
            y = y0 + (max_height - text_height) / 2 - bbox[1]
            draw.text((x, y), candidate, font=font, fill=fill)
            return min_size
        clipped = clipped[:-1]
    return min_size


def wrap_detail_text(details: list[ContestScore], max_items: int) -> list[str]:
    return [f"{detail.contest_id}: {detail.score}" for detail in details[:max_items]]


def nice_axis_step(max_value: int, target_ticks: int = 8) -> int:
    if max_value <= 0:
        return 1

    rough_step = max(1, max_value // target_ticks)
    magnitude = 1
    while magnitude * 10 <= rough_step:
        magnitude *= 10

    for multiplier in (1, 2, 5, 10):
        step = multiplier * magnitude
        if step >= rough_step:
            return step
    return 10 * magnitude


def format_axis_label(value: int) -> str:
    if value >= 100000:
        return f"{value // 1000}K"
    if value >= 1000 and value % 1000 == 0:
        return f"{value // 1000}K"
    return f"{value:,}"


def build_contribution_image(
    school_name: str,
    school_type: str,
    contest_type: str,
    rank: int,
    school_score: int,
    above_score: int | None,
    personal_frames: dict[str, dict[int, pd.DataFrame]] | None,
    performance_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
) -> SchoolRankImage | None:
    contributors = extract_contributors(
        school_name,
        contest_type,
        personal_frames,
        performance_frames,
    )
    if not contributors and school_score <= 0:
        return None

    contributor_total = sum(contributor.score for contributor in contributors)
    if contributor_total > school_score and school_score > 0:
        print(
            f"Personal score total exceeds school score for "
            f"{school_name} {contest_type}: {contributor_total} > {school_score}"
        )

    visible_contributors = []
    running_total = 0
    for contributor in contributors:
        if school_score > 0 and running_total + contributor.score > school_score:
            adjusted_score = max(0, school_score - running_total)
            if adjusted_score > 0:
                visible_contributors.append(
                    ContributorScore(
                        user_id=contributor.user_id,
                        score=adjusted_score,
                        details=contributor.details,
                        rating=contributor.rating,
                    )
                )
            running_total = school_score
            break
        visible_contributors.append(contributor)
        running_total += contributor.score

    missing_score = max(0, school_score - running_total)
    diff_score = max(0, (above_score or school_score) - school_score)
    graph_total = max(
        school_score + diff_score,
        contributor_total if school_score <= 0 else 0,
        1,
    )

    width = 1320
    left = 110
    right = 1150
    graph_top = 205
    graph_height = 695
    footer_top = graph_top + graph_height + 20
    height = footer_top + 120
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    title_font = load_graph_font(56, "bold")
    subtitle_font = load_graph_font(23, "regular")
    score_font = load_graph_font(28, "bold")
    axis_font = load_graph_font(30, "regular")
    small_font = load_graph_font(14, "regular")

    season_label = "Winter" if SEASON == "WINTER" else "Summer"
    contest_label = CONTEST_LABELS[contest_type]
    draw.text(
        (left, 36),
        f"AtCoder Junior League {YEAR} {season_label} - {contest_label}部門",
        font=subtitle_font,
        fill=(20, 20, 20),
    )
    title = f"{school_name} ({rank}位)"
    title_width = draw.textlength(title, font=title_font)
    draw.text(((width - title_width) / 2, 78), title, font=title_font, fill=(0, 0, 0))
    score_text = f"{school_score:,}pt"
    score_width = draw.textlength(score_text, font=score_font)
    draw.text(((width - score_width) / 2, 150), score_text, font=score_font, fill=(0, 0, 0))

    name_area_width = 330
    score_area_left = left + name_area_width
    draw.rectangle((left, graph_top, right, graph_top + graph_height), outline=(0, 0, 0), width=2)

    tick_step = nice_axis_step(graph_total)
    max_tick = ((graph_total + tick_step - 1) // tick_step) * tick_step
    if max_tick:
        for tick in range(tick_step, max_tick + 1, tick_step):
            y = graph_top + graph_height - int(graph_height * tick / max_tick)
            draw.line((65, y, width - 55, y), fill=(190, 190, 190), width=1)
            axis_label = format_axis_label(tick)
            label_bbox = draw.textbbox((0, 0), axis_label, font=axis_font)
            label_width = label_bbox[2] - label_bbox[0]
            label_height = label_bbox[3] - label_bbox[1]
            draw.text(
                (left - label_width - 18, y - label_height / 2 - label_bbox[1]),
                axis_label,
                font=axis_font,
                fill=(0, 0, 0),
            )

    current_bottom = graph_top + graph_height
    for contributor in visible_contributors:
        if contributor.score <= 0:
            continue

        segment_height = max(1, int(graph_height * contributor.score / max_tick)) if max_tick else 1
        y0 = max(graph_top, current_bottom - segment_height)
        y1 = current_bottom
        text_fill = rating_text_color(contributor.rating)
        name_background = soften_color(text_fill)
        draw.rectangle((left, y0, score_area_left, y1), fill=name_background, outline=(0, 0, 0), width=1)
        sub_bottom = y1
        sub_total = 0
        for detail in contributor.details:
            if sub_total >= contributor.score:
                break

            score = min(detail.score, contributor.score - sub_total)
            if score <= 0:
                continue

            sub_height = max(1, int(segment_height * score / contributor.score))
            sub_y0 = max(y0, sub_bottom - sub_height)
            fill = performance_background_color(detail.performance)
            draw.rectangle(
                (score_area_left, sub_y0, right, sub_bottom),
                fill=fill,
                outline=(150, 150, 180),
                width=1,
            )
            sub_available_height = sub_bottom - sub_y0
            if sub_available_height >= 2:
                draw_fit_text_in_box(
                    draw,
                    (
                        score_area_left + 8,
                        sub_y0 + 1,
                        right - 8,
                        sub_bottom - 1,
                    ),
                    f"{detail.contest_id}: {score}",
                    min(56, sub_available_height - 1),
                    (0, 0, 0),
                    min_size=1,
                    align="center",
                    weight="regular",
                )
            sub_bottom = sub_y0
            sub_total += score

        if sub_total < contributor.score:
            draw.rectangle(
                (score_area_left, y0, right, sub_bottom),
                fill=(230, 230, 230),
                outline=(150, 150, 180),
                width=1,
            )
            sub_available_height = sub_bottom - y0
            if sub_available_height >= 2:
                draw_fit_text_in_box(
                    draw,
                    (
                        score_area_left + 8,
                        y0 + 1,
                        right - 8,
                        sub_bottom - 1,
                    ),
                    f"その他: {contributor.score - sub_total}",
                    min(56, sub_available_height - 1),
                    (70, 70, 70),
                    min_size=1,
                    align="center",
                    weight="regular",
                )

        draw.rectangle((left, y0, right, y1), outline=(0, 0, 0), width=2)
        draw.line((score_area_left, y0, score_area_left, y1), fill=(0, 0, 0), width=2)

        label_text = f"{contributor.user_id}: {contributor.score}"
        available_height = y1 - y0
        if available_height >= 2:
            draw_fit_text_in_box(
                draw,
                (left + 12, y0 + 2, score_area_left - 12, y1 - 2),
                label_text,
                min(84, available_height - 2),
                text_fill,
                min_size=1,
                align="center",
                weight="bold",
            )
        elif available_height >= 2:
            draw_fit_text_in_box(
                draw,
                (left + 8, y0 + 1, score_area_left - 8, y1 - 1),
                label_text,
                max(1, available_height),
                text_fill,
                min_size=1,
                align="center",
                weight="bold",
            )

        current_bottom = y0

    for label, score, fill, text_fill in [
        ("その他/未掲載", missing_score, (230, 230, 230), (80, 80, 80)),
        ("1つ上の学校との差分", diff_score, (255, 230, 185), (120, 100, 70)),
    ]:
        if score <= 0:
            continue

        segment_height = max(1, int(graph_height * score / max_tick)) if max_tick else 1
        y0 = max(graph_top, current_bottom - segment_height)
        y1 = current_bottom
        draw.rectangle((left, y0, right, y1), fill=fill, outline=(0, 0, 0), width=2)
        label_text = f"{label}: {score}"
        available_height = y1 - y0
        if available_height >= 34:
            draw_fit_text_in_box(
                draw,
                (left + 22, y0 + 4, right - 22, y1 - 4),
                label_text,
                min(48, available_height - 8),
                text_fill,
                min_size=13,
                weight="regular",
            )
        elif available_height >= 14:
            draw.text((left + 8, y0), label_text, font=small_font, fill=text_fill)
        current_bottom = y0

    label_x = left
    label_y = footer_top
    draw.text((label_x, label_y), f"{rank}th", font=score_font, fill=(0, 0, 0))
    draw.text((label_x, label_y + 34), f"{school_name}", font=score_font, fill=(0, 0, 0))
    draw.text((label_x, label_y + 68), f"(n={len(contributors)})", font=score_font, fill=(0, 0, 0))

    details_x = 430
    details_y = footer_top
    performance_legend = [
        ("<400", None),
        ("400", 400),
        ("800", 800),
        ("1200", 1200),
        ("1600", 1600),
        ("2000", 2000),
        ("2400", 2400),
        ("2800", 2800),
    ]
    for index, (label, performance) in enumerate(performance_legend):
        x = details_x + (index % 4) * 185
        y = details_y + (index // 4) * 28
        draw.rectangle(
            (x, y + 4, x + 18, y + 18),
            fill=performance_background_color(performance),
            outline=(130, 130, 130),
            width=1,
        )
        draw_fit_text(
            draw,
            (x + 24, y),
            f"Perf {label}",
            150,
            17,
            (40, 40, 40),
        )

    output = BytesIO()
    image.save(output, format="PNG")
    return SchoolRankImage(
        filename=school_image_filename(school_name, school_type, contest_type),
        data=output.getvalue(),
    )


def build_school_rank_embeds(
    school_name: str,
    school_type: str,
    frames: dict[str, pd.DataFrame],
    html_changed: dict[str, bool],
    history: dict[str, Any],
    personal_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
    performance_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
) -> tuple[list[SchoolRankMessagePart], bool, bool]:
    parts = []
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
            above_score = None
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
        contest_label = CONTEST_LABELS[contest_type]
        embed = discord.Embed(
            title=f"{contest_label}",
            description=description,
            color=discord.Color.blue(),
            url=embed_url,
        )
        embed.set_author(name=format_school_label(school_name, school_type))
        image = build_contribution_image(
            school_name=school_name,
            school_type=school_type,
            contest_type=contest_type,
            rank=current_rank,
            school_score=current_score,
            above_score=above_score,
            personal_frames=personal_frames,
            performance_frames=performance_frames,
        )
        if image is not None:
            embed.set_image(url=f"attachment://{image.filename}")
        parts.append(SchoolRankMessagePart(embed=embed, image=image))

        if html_changed[contest_type]:
            school_history[contest_type]["previous_rank"] = last_rank
            school_history[contest_type]["previous_score"] = last_score
            school_history[contest_type]["last_rank"] = current_rank
            school_history[contest_type]["last_score"] = current_score
            changed = True

    return parts, bool(parts), changed


def message_parts_to_embeds(
    parts: list[SchoolRankMessagePart],
) -> list[discord.Embed]:
    return [part.embed for part in parts]


def message_parts_to_files(
    parts: list[SchoolRankMessagePart],
) -> list[discord.File]:
    files = []
    for part in parts:
        if part.image is None:
            continue
        files.append(
            discord.File(BytesIO(part.image.data), filename=part.image.filename)
        )
    return files


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
        personal_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
        performance_frames: dict[str, dict[int, pd.DataFrame]] | None = None,
        history: dict[str, Any] | None = None,
    ) -> tuple[list[SchoolRankMessagePart], bool]:
        if frames is None or html_changed is None:
            frames, html_changed = fetch_school_rank_tables(school_type)
        if personal_frames is None:
            personal_frames, _ = fetch_personal_rank_tables(school_type)
        if performance_frames is None:
            performance_frames, _ = fetch_personal_rank_tables(school_type, "perf")
        if history is None:
            history = load_school_rank_history()

        parts, found, changed = build_school_rank_embeds(
            school_name,
            school_type,
            frames,
            html_changed,
            history,
            personal_frames,
            performance_frames,
        )
        if changed:
            save_school_rank_history(history)
        if not found:
            return [], changed
        return parts, changed

    async def send_school_rank(
        self,
        interaction: discord.Interaction,
        school_name: str,
        school_type: str,
    ):
        try:
            await interaction.response.defer()
            parts, _ = await self.get_school_rank_data(school_name, school_type)

            if parts:
                await interaction.followup.send(
                    embeds=message_parts_to_embeds(parts),
                    files=message_parts_to_files(parts),
                )
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
            personal_tables_by_type = {
                school_type: fetch_personal_rank_tables(school_type)[0]
                for school_type in sorted({school_type for _, school_type in matches})
            }
            performance_tables_by_type = {
                school_type: fetch_personal_rank_tables(school_type, "perf")[0]
                for school_type in sorted({school_type for _, school_type in matches})
            }

            history = load_school_rank_history()
            parts = []
            changed = False
            omitted_count = 0
            for school_name, school_type in matches:
                frames, html_changed = tables_by_type[school_type]
                school_parts, found, school_changed = build_school_rank_embeds(
                    school_name,
                    school_type,
                    frames,
                    html_changed,
                    history,
                    personal_tables_by_type.get(school_type),
                    performance_tables_by_type.get(school_type),
                )
                if not found:
                    continue
                if len(parts) + len(school_parts) > MAX_SEARCH_RESULT_EMBEDS:
                    omitted_count += 1
                    continue
                parts.extend(school_parts)
                changed = changed or school_changed

            if changed:
                save_school_rank_history(history)

            if not parts:
                await interaction.followup.send(
                    f"「{query}」に一致する学校データが見つかりませんでした。"
                )
                return

            content = None
            if omitted_count:
                content = f"候補が多いため、追加の{omitted_count}校は省略しました。"
            await interaction.followup.send(
                content=content,
                embeds=message_parts_to_embeds(parts),
                files=message_parts_to_files(parts),
            )
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

            personal_tables_by_type = {
                school_type: fetch_personal_rank_tables(school_type)[0]
                for school_type, (_, html_changed) in tables_by_type.items()
                if any(html_changed.values())
            }
            performance_tables_by_type = {
                school_type: fetch_personal_rank_tables(school_type, "perf")[0]
                for school_type, (_, html_changed) in tables_by_type.items()
                if any(html_changed.values())
            }
            parts_by_school = {}
            changed_by_school = {}
            for school_name, school_type in sorted(
                {(school, school_type) for _, _, school, school_type in target_guilds}
            ):
                frames, html_changed = tables_by_type[school_type]
                parts, found, changed = build_school_rank_embeds(
                    school_name,
                    school_type,
                    frames,
                    html_changed,
                    history,
                    personal_tables_by_type.get(school_type),
                    performance_tables_by_type.get(school_type),
                )
                school_key = (school_name, school_type)
                parts_by_school[school_key] = parts if found else []
                changed_by_school[school_key] = changed

            if any(changed_by_school.values()):
                save_school_rank_history(history)

            for guild_id, channel_id, school_name, school_type in target_guilds:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    print(f"Channel with ID {channel_id} not found in guild {guild_id}.")
                    continue

                school_key = (school_name, school_type)
                parts = parts_by_school.get(school_key, [])
                if parts and changed_by_school.get(school_key, False):
                    await channel.send(
                        embeds=message_parts_to_embeds(parts),
                        files=message_parts_to_files(parts),
                    )
                    print(f"School Rank updated and sent to guild {guild_id}.")
                elif not parts:
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
