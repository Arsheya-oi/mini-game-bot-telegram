"""
ربات تلگرامی بازی‌های گروهی - نسخه ۲.۷
شامل: سنگ‌کاغذ‌قیچی + گل یا پوچ + دوز + دوز متحرک + حکم + مافیا + اولین نفر جواب بده + دار بازی + تورنمنت + بلک‌جک + کشتی
رفع باگ‌های دار بازی و دیتابیس مافیا + حفظ اطلاعات استریک
"""

import asyncio
import dataclasses
import json
import logging
import os
import random
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
   InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.error import Forbidden, BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# کاهش لاگ‌های httpx برای تمیزتر شدن خروجی
logging.getLogger("httpx").setLevel(logging.WARNING)

# ==== توکن ربات ====
BOT_TOKEN = "?"

# ==== پنل فعالیت بازی‌ها ====
ACTIVITY_PANEL_HOST = "127.0.0.1"
ACTIVITY_PANEL_PORT = 8088
BOT_START_TIME = time.time()

WINS_NEEDED = 3

RPS_CHOICES = {
    "rock": "🪨 سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی",
}

RPS_BEATS = {
    ("rock", "scissors"): True,
    ("scissors", "paper"): True,
    ("paper", "rock"): True,
}

SIDE_NAMES = {
    "left": "⬅️ دست چپ",
    "right": "➡️ دست راست",
}

XO_SYMBOLS = {"X": "❌", "O": "🟢"}
XO_EMPTY_LABEL = "・"

XO_WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]

MORRIS_PIECES_PER_PLAYER = 3
MORRIS_MOVE_MARK = "🔄"

HOKM_SUITS = ["♠", "♥", "♦", "♣"]
HOKM_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
HOKM_SUIT_NAMES = {"♠": "پیک", "♥": "دل", "♦": "خشت", "♣": "گیشنیز"}
HOKM_SUIT_EMOJI = {"♠": "♠️", "♥": "♥️", "♦": "♦️", "♣": "♣️"}
HOKM_TEAM_COLORS = {0: "🔵", 1: "🔴"}
HOKM_TEAM_NAMES = {0: "آبی", 1: "قرمز"}
HOKM_TURN_SECONDS = 60
HOKM_NAME_DISPLAY_LIMIT = 10
HOKM_HAKEM_PREVIEW_COUNT = 5   # تعداد کارت‌هایی که حاکم قبل از انتخاب حکم می‌بینه

KEYCAP_DIGITS = {
    "0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣",
    "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣",
}

# ==== تشکر از Amiro ====
THANK_YOU = "\n\nتشکر ویژه از Amiro بابت سرور❤️🙏 "


def keycap_number(n: int) -> str:
    return "".join(KEYCAP_DIGITS[d] for d in str(n))


def short_display_name(name: str, limit: int = HOKM_NAME_DISPLAY_LIMIT) -> str:
    name = (name or "").strip()
    if len(name) <= limit:
        return name
    return name[: max(limit - 1, 1)].rstrip() + "…"


@dataclass
class HokmGame:
    target_rounds: int
    rounds_needed: int
    players: list = field(default_factory=list)
    hakem_index: int = 0
    trump: Optional[str] = None
    hands: dict = field(default_factory=dict)
    trick_cards: list = field(default_factory=list)
    trick_num: int = 0
    team_tricks: dict = field(default_factory=lambda: {0: 0, 1: 0})
    round_wins: dict = field(default_factory=lambda: {0: 0, 1: 0})
    turn_index: int = 0
    phase: str = "joining"
    message_id: Optional[int] = None
    turn_job_name: Optional[str] = None
    turn_token: int = 0
    hakem_reveal_limit: Optional[int] = None


hokm_games: dict[str, HokmGame] = {}


@dataclass
class Game:
    game_type: str
    player1_id: int
    player1_name: str
    player2_id: Optional[int] = None
    player2_name: Optional[str] = None
    score1: int = 0
    score2: int = 0
    round_num: int = 1
    choices: dict = field(default_factory=dict)
    hider_id: Optional[int] = None
    guesser_id: Optional[int] = None
    hidden_side: Optional[str] = None
    board: list = field(default_factory=lambda: [""] * 9)
    turn_id: Optional[int] = None
    morris_queue: dict = field(default_factory=dict)


games: dict[str, Game] = {}

# ==========================================================
# ==== دیتابیس برای ذخیره‌سازی استریک‌ها و نام کاربران (Async) ====
# ==========================================================

STATS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.db")


def stats_db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(STATS_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            streak INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


# --- توابع هم‌زمان (بلاک‌کننده) که در Thread اجرا می‌شن ---
def _stats_load_all_sync() -> tuple[dict[int, int], dict[int, str]]:
    win_streaks = {}
    user_names = {}
    try:
        with stats_db_connect() as conn:
            rows = conn.execute("SELECT user_id, name, streak FROM user_stats").fetchall()
        for user_id, name, streak in rows:
            win_streaks[user_id] = streak
            user_names[user_id] = name
        logger.info(f"آمار {len(win_streaks)} کاربر از دیتابیس بارگذاری شد.")
    except Exception as e:
        logger.exception(f"خطا در بارگذاری آمار از دیتابیس: {e}")
    return win_streaks, user_names


def _stats_save_user_sync(user_id: int, name: str, streak: int) -> None:
    try:
        with stats_db_connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_stats (user_id, name, streak) VALUES (?, ?, ?)",
                (user_id, name, streak),
            )
    except Exception as e:
        logger.exception(f"خطا در ذخیره‌سازی آمار کاربر {user_id}: {e}")


def _stats_save_all_sync(win_streaks: dict[int, int], user_names: dict[int, str]) -> None:
    try:
        with stats_db_connect() as conn:
            for user_id, streak in win_streaks.items():
                name = user_names.get(user_id, str(user_id))
                conn.execute(
                    "INSERT OR REPLACE INTO user_stats (user_id, name, streak) VALUES (?, ?, ?)",
                    (user_id, name, streak),
                )
    except Exception as e:
        logger.exception(f"خطا در ذخیره‌سازی کامل آمار: {e}")


# --- توابع غیرهم‌زمان (Async) که از ترد استفاده می‌کنن ---
async def stats_load_all() -> tuple[dict[int, int], dict[int, str]]:
    return await asyncio.to_thread(_stats_load_all_sync)


async def stats_save_user(user_id: int, name: str, streak: int) -> None:
    await asyncio.to_thread(_stats_save_user_sync, user_id, name, streak)


async def stats_save_all(win_streaks: dict[int, int], user_names: dict[int, str]) -> None:
    await asyncio.to_thread(_stats_save_all_sync, win_streaks, user_names)


# بارگذاری اولیه (در post_init انجام می‌شه)
win_streaks, user_names = {}, {}


# ==========================================================
# ==== توابع جدید برای استریک و رتبه‌بندی ====
# ==========================================================

async def send_streak_update(context: ContextTypes.DEFAULT_TYPE, winner_id: int, winner_name: str):
    """ارسال پیام خصوصی به برنده با اطلاعات استریک جدید و رتبه"""
    streak = win_streaks.get(winner_id, 0)
    if streak == 0:
        return  # نباید صفر باشه

    # ذخیره نام در دیکشنری و دیتابیس (به‌صورت غیرهم‌زمان)
    user_names[winner_id] = winner_name
    await stats_save_user(winner_id, winner_name, streak)

    # محاسبه رتبه (چند نفر بالاتر از این کاربر هستند)
    sorted_streaks = sorted(win_streaks.items(), key=lambda x: x[1], reverse=True)
    rank = 1
    for i, (uid, s) in enumerate(sorted_streaks, 1):
        if uid == winner_id:
            rank = i
            break

    total_players = len(win_streaks)
    top_text = ""
    if rank == 1:
        top_text = "🏆 شما در صدر جدول هستید!"
    elif rank <= 3:
        top_text = f"🥇 رتبه شما: {rank} از {total_players} نفر"
    else:
        top_text = f"📍 رتبه شما: {rank} از {total_players} نفر"

    message = (
        f"🎉 تبریک {winner_name}!\n"
        f"شما استریک برد خود را به **{streak}** برد پشت‌سرهم رساندید! 🔥\n"
        f"{top_text}\n\n"
        f"برای مشاهده‌ی لیست کامل، دستور /streak را بفرستید یا از دکمه‌ی موجود در /start استفاده کنید."
    )

    try:
        await context.bot.send_message(chat_id=winner_id, text=message)
    except (Forbidden, BadRequest):
        # کاربر ربات رو بلاک کرده یا پیوی بسته، نادیده می‌گیریم
        pass


async def streak_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /streak - نمایش لیست ۱۰ نفر برتر استریک"""
    user = update.effective_user
    if not user:
        return

    if not win_streaks:
        await update.message.reply_text("هنوز هیچ استریکی ثبت نشده. اولین برنده شما باشید!")
        return

    sorted_users = sorted(win_streaks.items(), key=lambda x: x[1], reverse=True)
    top_ten = sorted_users[:10]

    lines = ["🏅 **جدول استریک برد (۱۰ نفر برتر)**\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, streak) in enumerate(top_ten, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        # دریافت نام از دیکشنری user_names
        name = user_names.get(uid, str(uid))
        lines.append(f"{medal} {name} — استریک: **{streak}**")

    # اگر کاربر در بین ۱۰ نفر نباشد، رتبه‌اش را نمایش دهیم
    user_rank = None
    for i, (uid, _) in enumerate(sorted_users, 1):
        if uid == user.id:
            user_rank = i
            break

    if user_rank is not None and user_rank > 10:
        my_name = user_names.get(user.id, user.first_name or str(user.id))
        lines.append(f"\n📍 رتبه‌ی شما: **{user_rank}** (با استریک {win_streaks[user.id]})")

    text = "\n".join(lines)
    try:
        # ارسال در پیوی
        await context.bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
        if update.message.chat.type != "private":
            await update.message.reply_text("لیست استریک‌ها به پیوی شما ارسال شد 📩")
    except (Forbidden, BadRequest):
        await update.message.reply_text("لطفاً ابتدا به ربات پیام /start بدهید تا بتوانم لیست را برایتان بفرستم.")
    except Exception as e:
        logger.error(f"خطا در دستور /streak: {e}")
        await update.message.reply_text("متأسفانه خطایی در نمایش لیست استریک رخ داد. لطفاً دوباره تلاش کنید.")


# ==========================================================
# ==== توابع قبلی (با ذخیره‌سازی نام در دیتابیس به‌صورت Async) ====
# ==========================================================

def bump_win_streak(winner_id: int, loser_id: int) -> int:
    win_streaks[winner_id] = win_streaks.get(winner_id, 0) + 1
    win_streaks[loser_id] = 0
    # ذخیره در دیتابیس به‌صورت هم‌زمان انجام نمی‌شه (در async انجام می‌شه)
    return win_streaks[winner_id]


def bump_win_streak_group(winner_id: Optional[int], participant_ids: list) -> int:
    for pid in participant_ids:
        if pid != winner_id:
            win_streaks[pid] = 0
    if winner_id is not None:
        win_streaks[winner_id] = win_streaks.get(winner_id, 0) + 1
        return win_streaks[winner_id]
    return 0


def win_streak_line(winner_name: str, streak: int) -> str:
    if streak < 2:
        return ""
    return f"\n🔥 استریک برد {winner_name}: {streak} بازی پشت سر هم!"


# ==========================================================
# ==== توابع کمکی برای لابی (دکمه‌ی انصراف) ====
# ==========================================================

def cancel_join_button() -> InlineKeyboardButton:
    return InlineKeyboardButton("❌ انصراف از پیوستن", callback_data="cancel_join")


# ==========================================================
# ==== بازی‌های دو نفره (rps, golpoch, xo, morris) ====
# ==========================================================

def join_keyboard(game_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎮 قبول چالش", callback_data=f"join_{game_type}")],
            [cancel_join_button()],
        ]
    )


def rps_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🪨 سنگ", callback_data="rps_rock"),
                InlineKeyboardButton("📄 کاغذ", callback_data="rps_paper"),
                InlineKeyboardButton("✂️ قیچی", callback_data="rps_scissors"),
            ]
        ]
    )


def hide_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ دست چپ", callback_data="hide_left"),
                InlineKeyboardButton("➡️ دست راست", callback_data="hide_right"),
            ]
        ]
    )


def guess_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ دست چپ", callback_data="guess_left"),
                InlineKeyboardButton("➡️ دست راست", callback_data="guess_right"),
            ]
        ]
    )


def score_line(game: Game) -> str:
    return f"امتیاز: {game.player1_name} {game.score1} - {game.score2} {game.player2_name}"


def game_title(game_type: str) -> str:
    if game_type == "rps":
        return "سنگ‌کاغذ‌قیچی"
    if game_type == "golpoch":
        return "گل یا پوچ"
    if game_type == "morris":
        return "دوز متحرک"
    return "دوز"


def start_message_text(game_type: str, starter_name: str) -> str:
    if game_type == "xo":
        return (
            f"🎯 {starter_name} یه بازی دوز (❌🟢) راه انداخته!\n"
            "کی حریفشه؟ 👇"
            + THANK_YOU
        )
    if game_type == "morris":
        return (
            f"🎯 {starter_name} یه بازی دوز متحرک (❌🟢) راه انداخته!\n"
            "هر کی فقط ۳ مهره داره؛ بعدش باید قدیمی‌ترین مهره‌تو جابه‌جا کنی — "
            "تا یکی نبره تموم نمی‌شه.\nکی حریفشه؟ 👇"
            + THANK_YOU
        )
    return (
        f"🎯 {starter_name} یه بازی {game_title(game_type)} راه انداخته!\n"
        f"هر کی زودتر {WINS_NEEDED} راند رو ببره، برنده‌ست.\nکی حریفشه؟ 👇"
        + THANK_YOU
    )


def xo_board_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            cell = game.board[idx]
            label = XO_SYMBOLS.get(cell, XO_EMPTY_LABEL)
            row.append(InlineKeyboardButton(label, callback_data=f"xo_{idx}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def xo_winner(board: list) -> Optional[str]:
    for a, b, c in XO_WIN_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def xo_turn_text(game: Game) -> str:
    turn_name = game.player1_name if game.turn_id == game.player1_id else game.player2_name
    turn_symbol = "❌" if game.turn_id == game.player1_id else "🟢"
    return (
        f"⚔️ {game.player1_name} (❌) در مقابل {game.player2_name} (🟢)\n\n"
        f"نوبت {turn_name}ه ({turn_symbol})، یه خونه رو انتخاب کن 👇"
    )


def morris_oldest_idx(game: Game, user_id: int) -> Optional[int]:
    queue = game.morris_queue.get(user_id, [])
    if len(queue) < MORRIS_PIECES_PER_PLAYER:
        return None
    return queue[0]


def morris_board_keyboard(game: Game) -> InlineKeyboardMarkup:
    highlight_idx = morris_oldest_idx(game, game.turn_id)
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            cell = game.board[idx]
            label = XO_SYMBOLS.get(cell, XO_EMPTY_LABEL)
            if idx == highlight_idx:
                label += MORRIS_MOVE_MARK
            row.append(InlineKeyboardButton(label, callback_data=f"morris_{idx}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def morris_turn_text(game: Game) -> str:
    turn_name = game.player1_name if game.turn_id == game.player1_id else game.player2_name
    turn_symbol = "❌" if game.turn_id == game.player1_id else "🟢"
    header = (
        f"⚔️ {game.player1_name} (❌) در مقابل {game.player2_name} (🟢)\n\n"
        f"نوبت {turn_name}ه ({turn_symbol})"
    )
    oldest_idx = morris_oldest_idx(game, game.turn_id)
    if oldest_idx is None:
        return header + "، یه خونه‌ی خالی برای گذاشتن مهره انتخاب کن 👇"
    return (
        header + f" — باید مهره‌ی {MORRIS_MOVE_MARK} رو جابه‌جا کنی؛ "
        "یه خونه‌ی خالی برای مقصدش انتخاب کن 👇"
    )


# ======================== حکم (Hokm) ========================

def hokm_build_deck() -> list:
    return [{"rank": r, "suit": s} for s in HOKM_SUITS for r in HOKM_RANKS]


def hokm_card_label(card: dict) -> str:
    return f"{card['rank']}{card['suit']}"


def hokm_card_strength(card: dict) -> int:
    return HOKM_RANKS.index(card["rank"])


def hokm_sort_key(card: dict):
    return (HOKM_SUITS.index(card["suit"]), HOKM_RANKS.index(card["rank"]))


def hokm_team_label(game: HokmGame, team_idx: int) -> str:
    return f"{game.players[team_idx]['name']} + {game.players[team_idx + 2]['name']}"


def hokm_team_color_label(game: HokmGame, team_idx: int) -> str:
    color = HOKM_TEAM_COLORS[team_idx]
    name = HOKM_TEAM_NAMES[team_idx]
    return f"{color} گروه {name} ({hokm_team_label(game, team_idx)})"


def hokm_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎮 پیوستن به بازی حکم", callback_data="hokm_join")],
            [cancel_join_button()],
        ]
    )


def hokm_join_status_text(game: HokmGame) -> str:
    names = "، ".join(p["name"] for p in game.players)
    return (
        f"🃏 بازی حکم (بهترین از {game.target_rounds} راند)\n"
        f"نفرات فعلی ({len(game.players)}/۴): {names}\n\nبرای پیوستن بزن 👇"
        + THANK_YOU
    )


def hokm_suit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(s, callback_data=f"hokm_suit_{s}") for s in HOKM_SUITS],
            [InlineKeyboardButton("🃏 دیدن دست کارتام", callback_data="hokm_hand")],
        ]
    )


def hokm_trick_slot_buttons(game: HokmGame) -> list:
    played = dict(game.trick_cards)
    buttons = []
    for p in game.players:
        name = short_display_name(p["name"])
        if p["id"] in played:
            label = f"{name}: {hokm_card_label(played[p['id']])}"
        else:
            label = f"{name}: …"
        buttons.append(InlineKeyboardButton(label, callback_data="hokm_noop"))
    return [buttons[0:2], buttons[2:4]]


def hokm_play_keyboard(game: HokmGame, player_id: int) -> InlineKeyboardMarkup:
    hand_size = len(game.hands[player_id])
    rows = []
    if game.trump:
        trump_emoji = HOKM_SUIT_EMOJI.get(game.trump, game.trump)
        trump_name = HOKM_SUIT_NAMES.get(game.trump, "")
        rows.append([InlineKeyboardButton(f"🃏 حکم: {trump_emoji} {trump_name}", callback_data="hokm_noop")])
    current_name = game.players[game.turn_index]["name"]
    rows.append(
        [InlineKeyboardButton(f"👉 نوبت: {current_name} (⏱ {HOKM_TURN_SECONDS} ثانیه)", callback_data="hokm_noop")]
    )
    rows.extend(hokm_trick_slot_buttons(game))
    number_buttons = [
        InlineKeyboardButton(keycap_number(i + 1), callback_data=f"hokm_play_{i}") for i in range(hand_size)
    ]
    rows.extend([number_buttons[i:i + 5] for i in range(0, len(number_buttons), 5)])
    rows.append([InlineKeyboardButton("🃏 دیدن دست کارتام", callback_data="hokm_hand")])
    return InlineKeyboardMarkup(rows)


def hokm_start_round(game: HokmGame) -> None:
    deck = hokm_build_deck()
    random.shuffle(deck)
    game.hands = {}
    for i, p in enumerate(game.players):
        cards = deck[i * 13:(i + 1) * 13]
        cards.sort(key=hokm_sort_key)
        game.hands[p["id"]] = cards
    game.trick_cards = []
    game.trick_num = 0
    game.team_tricks = {0: 0, 1: 0}
    game.trump = None
    # انتخاب تصادفی حاکم
    game.hakem_index = random.randint(0, 3)
    game.turn_index = game.hakem_index
    game.phase = "choosing_hokm"
    game.hakem_reveal_limit = HOKM_HAKEM_PREVIEW_COUNT


def hokm_hand_text(hand: list, limit: Optional[int] = None) -> str:
    if limit is not None and limit > 0:
        hand = hand[:limit]
    lines = []
    for i, card in enumerate(hand):
        suit_emoji = HOKM_SUIT_EMOJI.get(card["suit"], card["suit"])
        lines.append(f"{keycap_number(i+1)} {suit_emoji}{card['rank']}")
    return "\n".join(lines)


def hokm_valid_play_indices(hand: list, trick_cards: list, trump: Optional[str]) -> list:
    if not trick_cards:
        return list(range(len(hand)))
    leading_suit = trick_cards[0][1]["suit"]
    following = [i for i, c in enumerate(hand) if c["suit"] == leading_suit]
    return following if following else list(range(len(hand)))


def hokm_cancel_turn_timer(context: ContextTypes.DEFAULT_TYPE, game: HokmGame) -> None:
    if context.job_queue and game.turn_job_name:
        for job in context.job_queue.get_jobs_by_name(game.turn_job_name):
            job.schedule_removal()
    game.turn_job_name = None


def hokm_schedule_turn_timer(context: ContextTypes.DEFAULT_TYPE, key: str, game: HokmGame) -> None:
    hokm_cancel_turn_timer(context, game)
    if not context.job_queue:
        return
    game.turn_token += 1
    job_name = f"hokm_turn_{key}_{game.turn_token}"
    context.job_queue.run_once(
        hokm_turn_timeout,
        HOKM_TURN_SECONDS,
        data={"key": key, "token": game.turn_token},
        name=job_name,
    )
    game.turn_job_name = job_name


async def hokm_edit_origin(bot, key: str, game: HokmGame, text: str, reply_markup=None) -> None:
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(key), message_id=game.message_id, reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=key, reply_markup=reply_markup)
    except BadRequest:
        pass


def hokm_trick_line(game: HokmGame) -> str:
    def name_of(uid: int) -> str:
        return next(p["name"] for p in game.players if p["id"] == uid)

    return "این دست: " + " | ".join(
        f"{name_of(uid)}: {hokm_card_label(card)}" for uid, card in game.trick_cards
    )


def hokm_determine_trick_winner(game: HokmGame) -> int:
    leading_suit = game.trick_cards[0][1]["suit"]
    trump_plays = [(uid, c) for uid, c in game.trick_cards if c["suit"] == game.trump]
    if trump_plays:
        winner_uid, _ = max(trump_plays, key=lambda t: hokm_card_strength(t[1]))
    else:
        leading_plays = [(uid, c) for uid, c in game.trick_cards if c["suit"] == leading_suit]
        winner_uid, _ = max(leading_plays, key=lambda t: hokm_card_strength(t[1]))
    return winner_uid


def hokm_seating_text(game: HokmGame) -> str:
    h = game.hakem_index
    hakem = game.players[h]["name"]
    partner = game.players[(h + 2) % 4]["name"]
    left_opp = game.players[(h + 1) % 4]["name"]
    right_opp = game.players[(h + 3) % 4]["name"]
    return (
        f"          🤝 {partner}\n"
        f"⚔️ {left_opp}          ⚔️ {right_opp}\n"
        f"          👑 {hakem} (حاکم)"
    )


def hokm_status_text(game: HokmGame) -> str:
    trump_line = (
        f"🃏 حکم: {HOKM_SUIT_EMOJI.get(game.trump, game.trump)} {HOKM_SUIT_NAMES.get(game.trump, '')}"
        if game.trump
        else "🃏 حکم: هنوز انتخاب نشده"
    )
    lines = [
        f"{hokm_team_color_label(game, 0)} — {game.round_wins[0]} راند",
        f"{hokm_team_color_label(game, 1)} — {game.round_wins[1]} راند",
        "",
        trump_line,
        f"این راند: {HOKM_TEAM_COLORS[0]} {game.team_tricks[0]} - {game.team_tricks[1]} {HOKM_TEAM_COLORS[1]}",
        "",
        hokm_seating_text(game),
        "",
        "👇 نوبت و کارت‌های این دست رو تو دکمه‌های پایین ببین؛ با شماره‌ی کارت تو دستت بازی کن",
        f"⏱ هر نوبت {HOKM_TURN_SECONDS} ثانیه وقت داری؛ اگه تموم بشه یه کارت مجاز رندوم به‌جات انداخته می‌شه.",
    ]
    return "\n".join(lines)


async def hokm_process_card_play(context: ContextTypes.DEFAULT_TYPE, key: str, game: HokmGame, user_id: int, idx: int):
    hand = game.hands[user_id]
    card = hand.pop(idx)
    game.trick_cards.append((user_id, card))

    if len(game.trick_cards) < 4:
        game.turn_index = (game.turn_index + 1) % 4
        next_player = game.players[game.turn_index]
        hokm_schedule_turn_timer(context, key, game)
        return hokm_status_text(game), hokm_play_keyboard(game, next_player["id"]), False

    trick_summary = hokm_trick_line(game)
    winner_uid = hokm_determine_trick_winner(game)
    winner_seat = next(i for i, p in enumerate(game.players) if p["id"] == winner_uid)
    team_idx = winner_seat % 2
    game.team_tricks[team_idx] += 1
    game.trick_num += 1
    winner_name = game.players[winner_seat]["name"]

    game.trick_cards = []

    if game.team_tricks[team_idx] >= 7:
        game.round_wins[team_idx] += 1
        round_text = (
            f"{trick_summary}\n🃏 برنده این دست: {winner_name}\n\n"
            f"🏁 راند تموم شد! دست‌های برده: {HOKM_TEAM_COLORS[0]} {game.team_tricks[0]} - {game.team_tricks[1]} {HOKM_TEAM_COLORS[1]}\n"
            f"🏆 برنده راند: {hokm_team_color_label(game, team_idx)}\n\n"
            f"{hokm_team_color_label(game, 0)} — {game.round_wins[0]} راند\n"
            f"{hokm_team_color_label(game, 1)} — {game.round_wins[1]} راند"
        )

        if game.round_wins[team_idx] >= game.rounds_needed:
            loser_team = 1 - team_idx
            winners = [game.players[team_idx], game.players[team_idx + 2]]
            losers = [game.players[loser_team], game.players[loser_team + 2]]
            streak_lines = []
            for w, l in zip(winners, losers):
                streak = bump_win_streak(w["id"], l["id"])
                # ذخیره نام برنده و بازنده (به‌صورت غیرهم‌زمان)
                user_names[w["id"]] = w["name"]
                user_names[l["id"]] = l["name"]
                # ذخیره در دیتابیس
                await stats_save_user(w["id"], w["name"], streak)
                await stats_save_user(l["id"], l["name"], 0)
                line = win_streak_line(w["name"], streak)
                if line:
                    streak_lines.append(line)
                # ارسال پیام استریک برای هر برنده
                await send_streak_update(context, w["id"], w["name"])
            final_text = (
                round_text
                + f"\n\n🏆🏆 برنده کل بازی حکم: {hokm_team_color_label(game, team_idx)} 🏆🏆"
                + "".join(streak_lines)
                + THANK_YOU
            )
            del hokm_games[key]
            return final_text, None, True

        game.hakem_index = (game.hakem_index + 1) % 4
        hokm_start_round(game)
        hakem_name = game.players[game.hakem_index]["name"]
        next_text = (
            round_text
            + f"\n\nراند بعدی شروع شد. حاکم جدید: {hakem_name}\n"
            f"{hakem_name} اول {HOKM_HAKEM_PREVIEW_COUNT} کارت اول دستشو ببینه، بعد حکم رو انتخاب کنه 👇"
        )
        return next_text, hokm_suit_keyboard(), False

    game.turn_index = winner_seat
    text = f"{trick_summary}\n🃏 برنده این دست: {winner_name}\n\n" + hokm_status_text(game)
    hokm_schedule_turn_timer(context, key, game)
    return text, hokm_play_keyboard(game, winner_uid), False


async def hokm_turn_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    key = data["key"]
    game = hokm_games.get(key)
    if not game or game.phase != "playing" or game.turn_token != data["token"]:
        return

    game.turn_job_name = None
    current_player = game.players[game.turn_index]
    hand = game.hands.get(current_player["id"])
    if not hand:
        return

    valid_indices = hokm_valid_play_indices(hand, game.trick_cards, game.trump)
    idx = random.choice(valid_indices)
    card = hand[idx]

    text, markup, _finished = await hokm_process_card_play(context, key, game, current_player["id"], idx)
    notice = f"⌛ وقت {current_player['name']} تموم شد، به‌جاش کارت {hokm_card_label(card)} رندوم انداخته شد!\n\n"
    await hokm_edit_origin(context.bot, key, game, notice + text, markup)

    try:
        await context.bot.send_message(
            current_player["id"],
            f"⌛ وقتت برای بازی حکم تموم شد! به‌جات کارت {hokm_card_label(card)} رندوم انداخته شد.",
        )
    except Forbidden:
        pass


# ======================== تورنمنت ========================

TOURNAMENT_MIN_PLAYERS = 4
TOURNAMENT_MAX_PLAYERS = 16
TOURNAMENT_WINS_NEEDED = 3

tournament_games: dict[str, 'TournamentGame'] = {}


@dataclass
class TournamentMatch:
    player1_id: int
    player1_name: str
    player2_id: int
    player2_name: str
    score1: int = 0
    score2: int = 0
    round_num: int = 1
    choices: dict = field(default_factory=dict)
    finished: bool = False
    winner_id: Optional[int] = None


@dataclass
class TournamentGame:
    key: str
    started_by: int
    message_id: Optional[int] = None
    players: list = field(default_factory=list)
    phase: str = "lobby"
    round_num: int = 0
    matches: list = field(default_factory=list)
    current_match_index: int = 0
    winners: list = field(default_factory=list)
    job_names: list = field(default_factory=list)


def tournament_lobby_text(game: TournamentGame) -> str:
    names = "، ".join(p["name"] for p in game.players)
    return (
        f"🏆 تورنمنت حذفی سنگ‑کاغذ‑قیچی\n"
        f"(حداقل {TOURNAMENT_MIN_PLAYERS}، حداکثر {TOURNAMENT_MAX_PLAYERS} نفر)\n\n"
        f"نفرات فعلی ({len(game.players)} نفر): {names}\n\n"
        f"فقط {game.players[0]['name'] if game.players else ''} (سازنده) می‌تونه شروع کنه 👇"
        + THANK_YOU
    )


def tournament_lobby_keyboard(game: TournamentGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن ({len(game.players)}/{TOURNAMENT_MAX_PLAYERS})",
                              callback_data="tournament_join")],
        [InlineKeyboardButton("🚀 شروع تورنمنت", callback_data="tournament_start")],
        [cancel_join_button()],
    ])


def tournament_inline_result(starter_name: str) -> InlineQueryResultArticle:
    dummy = TournamentGame(key="", started_by=0)
    dummy.players = [{"id": 0, "name": starter_name}]
    return InlineQueryResultArticle(
        id=f"tournament-{uuid.uuid4()}",
        title="🏆 تورنمنت سنگ‑کاغذ‑قیچی",
        description=f"۴ تا {TOURNAMENT_MAX_PLAYERS} نفر، حذفی دو به دو، هر بازی تا {TOURNAMENT_WINS_NEEDED} برد",
        input_message_content=InputTextMessageContent(
            tournament_lobby_text(dummy)
        ),
        reply_markup=tournament_lobby_keyboard(dummy),
    )


def tournament_show_match_text(game: TournamentGame, match: TournamentMatch) -> str:
    lines = [
        f"🏆 دور {game.round_num}   •   مسابقه {game.current_match_index+1}/{len(game.matches)}",
        f"⚔️ {match.player1_name} vs {match.player2_name}",
        f"{match.player1_name}: {match.score1}",
        f"{match.player2_name}: {match.score2}",
        f"(تا {TOURNAMENT_WINS_NEEDED} برد)",
    ]
    if len(match.choices) == 2:
        p1_choice = RPS_CHOICES.get(match.choices.get(match.player1_id), "؟")
        p2_choice = RPS_CHOICES.get(match.choices.get(match.player2_id), "؟")
        lines.append("")
        lines.append(f"{match.player1_name}: {p1_choice}")
        lines.append(f"{match.player2_name}: {p2_choice}")
    lines.append("")
    lines.append(f"راند {match.round_num}: هر دو مخفیانه انتخاب کنید 👇")
    lines.append(THANK_YOU)
    return "\n".join(lines)


def tournament_match_keyboard(match_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🪨 سنگ", callback_data=f"t_rps_{match_idx}_rock"),
            InlineKeyboardButton("📄 کاغذ", callback_data=f"t_rps_{match_idx}_paper"),
            InlineKeyboardButton("✂️ قیچی", callback_data=f"t_rps_{match_idx}_scissors"),
        ]
    ])


def tournament_build_matches(players: list) -> list:
    shuffled = random.sample(players, len(players))
    matches = []
    i = 0
    while i < len(shuffled):
        if i + 1 < len(shuffled):
            p1 = shuffled[i]
            p2 = shuffled[i+1]
            matches.append(TournamentMatch(
                player1_id=p1["id"],
                player1_name=p1["name"],
                player2_id=p2["id"],
                player2_name=p2["name"],
            ))
            i += 2
        else:
            matches.append(TournamentMatch(
                player1_id=shuffled[i]["id"],
                player1_name=shuffled[i]["name"],
                player2_id=0,
                player2_name="(bye)",
                finished=True,
                winner_id=shuffled[i]["id"],
            ))
            i += 1
    return matches


def tournament_generate_bracket(game: TournamentGame) -> str:
    lines = []
    lines.append(f"🏆 جدول مسابقات (دور {game.round_num})")
    lines.append("=" * 20)
    if not game.matches:
        lines.append("هنوز مسابقه‌ای شروع نشده.")
        return "\n".join(lines)
    for idx, m in enumerate(game.matches, 1):
        if m.finished:
            winner = m.player1_name if m.winner_id == m.player1_id else m.player2_name
            status = f"✅ {winner} پیروز"
        else:
            status = f"⚔️ در حال انجام (امتیاز {m.score1}-{m.score2})"
        lines.append(f"{idx}. {m.player1_name} vs {m.player2_name}  — {status}")
    if game.round_num > 1 and game.winners:
        lines.append("\n🏅 برندگان دور قبلی:")
        lines.append("، ".join(p["name"] for p in game.winners))
    return "\n".join(lines)


async def tournament_send_bracket_to_players(game: TournamentGame, context: ContextTypes.DEFAULT_TYPE):
    bracket_text = tournament_generate_bracket(game)
    for p in game.players:
        try:
            await context.bot.send_message(
                chat_id=p["id"],
                text=f"📊 بروزرسانی تورنمنت:\n\n{bracket_text}"
            )
        except (Forbidden, BadRequest):
            pass


async def tournament_edit_origin(bot, game: TournamentGame, text: str, reply_markup=None):
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(game.key), message_id=game.message_id,
                                        reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=game.key, reply_markup=reply_markup)
    except BadRequest:
        pass


async def tournament_resolve_match(game: TournamentGame, match: TournamentMatch, context: ContextTypes.DEFAULT_TYPE):
    c1 = match.choices[match.player1_id]
    c2 = match.choices[match.player2_id]

    p1_choice = RPS_CHOICES.get(c1, "؟")
    p2_choice = RPS_CHOICES.get(c2, "؟")
    display_text = (
        f"⚔️ {match.player1_name} vs {match.player2_name}\n"
        f"{match.player1_name}: {p1_choice}\n"
        f"{match.player2_name}: {p2_choice}"
    )

    round_winner = None
    if c1 != c2:
        if RPS_BEATS.get((c1, c2)):
            match.score1 += 1
            round_winner = match.player1_id
        else:
            match.score2 += 1
            round_winner = match.player2_id

    match.choices = {}

    if match.score1 >= TOURNAMENT_WINS_NEEDED or match.score2 >= TOURNAMENT_WINS_NEEDED:
        match.finished = True
        match.winner_id = match.player1_id if match.score1 >= TOURNAMENT_WINS_NEEDED else match.player2_id
        winner_name = match.player1_name if match.winner_id == match.player1_id else match.player2_name
        loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
        loser_name = match.player2_name if match.winner_id == match.player1_id else match.player1_name

        # ==== ثبت استریک برای برندهٔ این مسابقه ====
        streak = bump_win_streak(match.winner_id, loser_id)
        # ذخیره نام‌ها و دیتابیس
        user_names[match.winner_id] = winner_name
        user_names[loser_id] = loser_name
        await stats_save_user(match.winner_id, winner_name, streak)
        await stats_save_user(loser_id, loser_name, 0)
        await send_streak_update(context, match.winner_id, winner_name)

        result_text = (
            f"{display_text}\n\n"
            f"امتیاز نهایی: {match.score1} - {match.score2}\n"
            f"✅ برنده مسابقه: {winner_name}"
            + win_streak_line(winner_name, streak)
            + THANK_YOU
        )
        await tournament_edit_origin(context.bot, game, result_text, None)
        await tournament_send_bracket_to_players(game, context)
        game.current_match_index += 1
        await tournament_start_next_match(game, context)
        return

    if round_winner:
        winner_name = match.player1_name if round_winner == match.player1_id else match.player2_name
        result_text = (
            f"{display_text}\n\n"
            f"✅ برنده راند: {winner_name}\n"
            f"امتیاز: {match.score1} - {match.score2}"
        )
    else:
        result_text = (
            f"{display_text}\n\n"
            "🤝 این راند مساوی شد!\n"
            f"امتیاز: {match.score1} - {match.score2}"
        )

    match.round_num += 1
    result_text += f"\n\nراند {match.round_num}: هر دو مخفیانه انتخاب کنید 👇" + THANK_YOU
    keyboard = tournament_match_keyboard(game.current_match_index)
    await tournament_edit_origin(context.bot, game, result_text, keyboard)


async def tournament_start_next_match(game: TournamentGame, context: ContextTypes.DEFAULT_TYPE):
    if game.current_match_index >= len(game.matches):
        await tournament_advance_round(game, context)
        return

    match = game.matches[game.current_match_index]
    if match.finished:
        game.current_match_index += 1
        await tournament_start_next_match(game, context)
        return

    text = tournament_show_match_text(game, match)
    keyboard = tournament_match_keyboard(game.current_match_index)
    await tournament_edit_origin(context.bot, game, text, keyboard)


async def tournament_advance_round(game: TournamentGame, context: ContextTypes.DEFAULT_TYPE):
    if not all(m.finished for m in game.matches):
        return

    winners = []
    for m in game.matches:
        if m.winner_id is not None:
            for p in game.players:
                if p["id"] == m.winner_id:
                    winners.append(p)
                    break

    if len(winners) == 1:
        game.phase = "finished"
        champ = winners[0]
        participant_ids = [p["id"] for p in game.players]
        bump_win_streak_group(champ["id"], participant_ids)
        user_names[champ["id"]] = champ["name"]
        await stats_save_user(champ["id"], champ["name"], win_streaks.get(champ["id"], 0))
        await send_streak_update(context, champ["id"], champ["name"])
        final_text = (
            f"🏆🏆 برنده تورنمنت: {champ['name']} 🏆🏆\n"
            f"با شکست {len(game.players)-1} حریف!"
            + THANK_YOU
        )
        await tournament_edit_origin(context.bot, game, final_text, None)
        await tournament_send_bracket_to_players(game, context)
        del tournament_games[game.key]
        return

    game.round_num += 1
    game.matches = tournament_build_matches(winners)
    game.winners = winners
    game.current_match_index = 0
    game.phase = "playing"
    await tournament_start_next_match(game, context)
    await tournament_send_bracket_to_players(game, context)


async def tournament_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE):
    game = tournament_games.get(key)
    if not game:
        await query.answer("تورنمنت پیدا نشد یا تمام شده.", show_alert=True)
        return

    if data == "tournament_join":
        if game.phase != "lobby":
            await query.answer("تورنمنت شروع شده، نمی‌توانید بپیوندید.", show_alert=True)
            return
        if any(p["id"] == user.id for p in game.players):
            await query.answer("قبلاً پیوستی!", show_alert=True)
            return
        if len(game.players) >= TOURNAMENT_MAX_PLAYERS:
            await query.answer(f"حداکثر {TOURNAMENT_MAX_PLAYERS} نفر.", show_alert=True)
            return
        game.players.append({"id": user.id, "name": user.first_name})
        await query.edit_message_text(
            tournament_lobby_text(game),
            reply_markup=tournament_lobby_keyboard(game)
        )
        await query.answer("پیوستی! ✅")
        return

    if data == "tournament_start":
        if game.phase != "lobby":
            await query.answer()
            return
        if user.id != game.started_by:
            await query.answer(f"فقط {game.players[0]['name']} می‌تواند شروع کند.", show_alert=True)
            return
        if len(game.players) < TOURNAMENT_MIN_PLAYERS:
            await query.answer(f"حداقل {TOURNAMENT_MIN_PLAYERS} نفر لازم است.", show_alert=True)
            return

        game.round_num = 1
        game.matches = tournament_build_matches(game.players)
        game.current_match_index = 0
        game.phase = "playing"
        await tournament_send_bracket_to_players(game, context)
        await tournament_start_next_match(game, context)
        await query.answer("تورنمنت شروع شد! 🚀")
        return

    if data.startswith("t_rps_"):
        if game.phase != "playing":
            await query.answer("این مسابقه دیگر فعال نیست.", show_alert=True)
            return

        parts = data.split("_")
        if len(parts) < 4:
            return
        try:
            match_idx = int(parts[2])
            choice = parts[3]
        except (ValueError, IndexError):
            return

        if match_idx >= len(game.matches):
            await query.answer("مسابقه نامعتبر.", show_alert=True)
            return

        match = game.matches[match_idx]
        if match.finished:
            await query.answer("این مسابقه قبلاً تمام شده.", show_alert=True)
            return

        if user.id not in (match.player1_id, match.player2_id):
            await query.answer("شما در این مسابقه نیستید.", show_alert=True)
            return

        if user.id in match.choices:
            await query.answer("قبلاً انتخاب کردی، منتظر حریفت باش.", show_alert=True)
            return

        match.choices[user.id] = choice
        await query.answer(f"انتخاب شد: {RPS_CHOICES[choice]} ✅")

        if len(match.choices) == 2:
            await tournament_resolve_match(game, match, context)
        return


# ======================== مافیا (رفع باگ SQLite) ========================

MAFIA_MIN_PLAYERS = 5
MAFIA_JOIN_SECONDS = 120
MAFIA_NIGHT_SECONDS = 45
MAFIA_VOTE_SECONDS = 60

ROLE_MAFIA = "mafia"
ROLE_DETECTIVE = "detective"
ROLE_DOCTOR = "doctor"
ROLE_CITIZEN = "citizen"

ROLE_LABELS = {
    ROLE_MAFIA: "🔪 مافیا",
    ROLE_DETECTIVE: "🕵️ کارآگاه",
    ROLE_DOCTOR: "💉 دکتر",
    ROLE_CITIZEN: "👤 شهروند ساده",
}


@dataclass
class MafiaPlayer:
    id: int
    name: str
    role: str = ROLE_CITIZEN
    alive: bool = True


@dataclass
class MafiaGame:
    key: str
    started_by: int
    players: list = field(default_factory=list)
    phase: str = "joining"
    day_num: int = 0
    mafia_votes: dict = field(default_factory=dict)
    doctor_save: Optional[int] = None
    detective_checked: bool = False
    day_votes: dict = field(default_factory=dict)
    job_names: list = field(default_factory=list)


mafia_games: dict[str, MafiaGame] = {}

MAFIA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mafia_games.db")


def mafia_db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(MAFIA_DB_PATH)
    # ایجاد جدول با ستون‌های صحیح
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mafia_games (
            game_key TEXT PRIMARY KEY,
            state_json TEXT NOT NULL
        )
        """
    )
    return conn


def mafia_serialize(game: MafiaGame) -> str:
    return json.dumps(dataclasses.asdict(game))


def mafia_deserialize(state_json: str) -> MafiaGame:
    data = json.loads(state_json)
    players_data = data.pop("players", [])
    for dict_field in ("mafia_votes", "day_votes"):
        if data.get(dict_field):
            data[dict_field] = {int(k): v for k, v in data[dict_field].items()}
    game = MafiaGame(**data)
    game.players = [MafiaPlayer(**p) for p in players_data]
    return game


def _mafia_save_sync(game: MafiaGame) -> None:
    try:
        with mafia_db_connect() as conn:
            conn.execute(
                "INSERT INTO mafia_games (game_key, state_json) VALUES (?, ?) "
                "ON CONFLICT(game_key) DO UPDATE SET state_json = excluded.state_json",
                (game.key, mafia_serialize(game)),
            )
    except Exception:
        logger.exception("خطا در ذخیره وضعیت بازی مافیا تو SQLite")


async def mafia_save(game: MafiaGame) -> None:
    await asyncio.to_thread(_mafia_save_sync, game)


def _mafia_delete_saved_sync(key: str) -> None:
    try:
        with mafia_db_connect() as conn:
            conn.execute("DELETE FROM mafia_games WHERE game_key = ?", (key,))
    except Exception:
        logger.exception("خطا در حذف وضعیت بازی مافیا از SQLite")


async def mafia_delete_saved(key: str) -> None:
    await asyncio.to_thread(_mafia_delete_saved_sync, key)


def mafia_load_all() -> dict:
    games: dict[str, MafiaGame] = {}
    try:
        with mafia_db_connect() as conn:
            # بررسی وجود جدول و ستون‌ها
            conn.execute("SELECT game_key, state_json FROM mafia_games LIMIT 1")
            rows = conn.execute("SELECT game_key, state_json FROM mafia_games").fetchall()
        for game_key, state_json in rows:
            try:
                games[game_key] = mafia_deserialize(state_json)
            except Exception:
                logger.exception(f"خطا در بازسازی وضعیت بازی مافیا برای {game_key}")
    except sqlite3.OperationalError as e:
        # اگر جدول یا ستون وجود نداشت، خطا را نادیده می‌گیریم (جدول در اولین ذخیره ساخته می‌شود)
        logger.warning(f"جدول مافیا هنوز ایجاد نشده یا ساختار آن صحیح نیست: {e}")
    except Exception:
        logger.exception("خطا در خوندن وضعیت‌های بازی مافیا از SQLite")
    return games


async def mafia_edit_origin(bot, key: str, text: str, reply_markup=None) -> None:
    try:
        await bot.edit_message_text(text, inline_message_id=key, reply_markup=reply_markup)
    except BadRequest:
        pass


async def mafia_restore_games(app: Application) -> None:
    restored = mafia_load_all()
    if not restored:
        return

    mafia_games.update(restored)
    for key, game in restored.items():
        game.job_names = []

        if app.job_queue:
            if game.phase == "joining":
                job_name = f"mafia_autobegin_{key}"
                app.job_queue.run_once(mafia_join_timeout, MAFIA_JOIN_SECONDS, data={"key": key}, name=job_name)
                game.job_names.append(job_name)
            elif game.phase == "night":
                job_name = f"mafia_night_{key}_{game.day_num}"
                app.job_queue.run_once(
                    mafia_night_timeout,
                    MAFIA_NIGHT_SECONDS,
                    data={"key": key, "day_num": game.day_num},
                    name=job_name,
                )
                game.job_names.append(job_name)
            elif game.phase == "day_vote":
                job_name = f"mafia_vote_{key}_{game.day_num}"
                app.job_queue.run_once(
                    mafia_vote_timeout,
                    MAFIA_VOTE_SECONDS,
                    data={"key": key, "day_num": game.day_num},
                    name=job_name,
                )
                game.job_names.append(job_name)

        await mafia_save(game)
        await mafia_edit_origin(
            app.bot, key, "🔄 ربات ری‌استارت شد؛ بازی مافیای این گروه از همون فازی که بود ادامه پیدا می‌کنه."
        )

    logger.info(f"{len(restored)} بازی مافیای نیمه‌تموم از SQLite بازیابی شد.")


def mafia_role_counts(n: int) -> dict:
    mafia_count = max(1, n // 4)
    detective_count = 1 if n >= 5 else 0
    doctor_count = 1 if n >= 6 else 0
    citizen_count = n - mafia_count - detective_count - doctor_count
    return {
        ROLE_MAFIA: mafia_count,
        ROLE_DETECTIVE: detective_count,
        ROLE_DOCTOR: doctor_count,
        ROLE_CITIZEN: citizen_count,
    }


def mafia_alive(game: MafiaGame) -> list:
    return [p for p in game.players if p.alive]


def mafia_alive_by_role(game: MafiaGame, role: str) -> list:
    return [p for p in game.players if p.alive and p.role == role]


def mafia_find(game: MafiaGame, uid: int) -> Optional[MafiaPlayer]:
    return next((p for p in game.players if p.id == uid), None)


def mafia_check_win(game: MafiaGame) -> Optional[str]:
    alive_mafia = len(mafia_alive_by_role(game, ROLE_MAFIA))
    alive_others = len(mafia_alive(game)) - alive_mafia
    if alive_mafia == 0:
        return "citizens"
    if alive_mafia >= alive_others:
        return "mafia"
    return None


def mafia_cancel_jobs(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.job_queue:
        return
    for name in game.job_names:
        for job in context.job_queue.get_jobs_by_name(name):
            job.schedule_removal()
    game.job_names = []


def mafia_lobby_placeholder_text(starter_name: str) -> str:
    return (
        "🕵️ بازی مافیا — لابی باز شد!\n"
        f"نفرات فعلی (۱ نفر، حداقل {MAFIA_MIN_PLAYERS} نفر لازمه): {starter_name}\n\n"
        "برای پیوستن دکمه رو بزن 👇"
        + THANK_YOU
    )


def mafia_lobby_text(game: MafiaGame) -> str:
    names = "، ".join(p.name for p in game.players)
    return (
        "🕵️ بازی مافیا — لابی باز شد!\n"
        f"نفرات فعلی ({len(game.players)} نفر، حداقل {MAFIA_MIN_PLAYERS} نفر لازمه): {names}\n\n"
        "برای پیوستن دکمه رو بزن 👇\n"
        "شروع‌کننده هر وقت نفرات کافی بود می‌تونه با دکمه «🚀 شروع بازی» زودتر شروع کنه."
        + THANK_YOU
    )


def mafia_lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data="mafia_join")],
            [
                InlineKeyboardButton("🚀 شروع بازی", callback_data="mafia_forcebegin"),
                InlineKeyboardButton("❌ لغو", callback_data="mafia_cancel"),
            ],
            [cancel_join_button()],
        ]
    )


def mafia_targets_keyboard(role_tag: str, key: str, targets: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(p.name, callback_data=f"mafia_act|{role_tag}|{key}|{p.id}")] for p in targets]
    )


def mafia_vote_keyboard(game: MafiaGame) -> InlineKeyboardMarkup:
    rows = []
    for p in mafia_alive(game):
        count = sum(1 for t in game.day_votes.values() if t == p.id)
        label = f"🗳 {p.name}" + (f" ({count})" if count else "")
        rows.append([InlineKeyboardButton(label, callback_data=f"mafia_vote|{p.id}")])
    skip_count = sum(1 for t in game.day_votes.values() if t == "skip")
    skip_label = "🤷 رأی سفید" + (f" ({skip_count})" if skip_count else "")
    rows.append([InlineKeyboardButton(skip_label, callback_data="mafia_vote|skip")])
    return InlineKeyboardMarkup(rows)


async def mafia_join_timeout(context: ContextTypes.DEFAULT_TYPE):
    key = context.job.data["key"]
    game = mafia_games.get(key)
    if not game or game.phase != "joining":
        return
    await mafia_try_begin(key, context, auto=True)


async def mafia_try_begin(key: str, context: ContextTypes.DEFAULT_TYPE, auto: bool) -> None:
    game = mafia_games.get(key)
    if not game or game.phase != "joining":
        return

    if len(game.players) < MAFIA_MIN_PLAYERS:
        if auto:
            del mafia_games[key]
            await mafia_delete_saved(key)
            await mafia_edit_origin(
                context.bot, key, f"نفرات کافی جمع نشد (حداقل {MAFIA_MIN_PLAYERS} نفر لازمه). بازی مافیا لغو شد."
            )
        else:
            await mafia_edit_origin(
                context.bot,
                key,
                mafia_lobby_text(game) + f"\n\n⏳ حداقل {MAFIA_MIN_PLAYERS} نفر لازمه، فعلاً {len(game.players)} نفرین.",
                reply_markup=mafia_lobby_keyboard(),
            )
        return

    mafia_cancel_jobs(game, context)

    unreachable = []
    for p in game.players:
        try:
            await context.bot.send_chat_action(chat_id=p.id, action="typing")
        except (Forbidden, BadRequest):
            unreachable.append(p.name)

    if unreachable:
        names = "، ".join(unreachable)
        await mafia_edit_origin(
            context.bot,
            key,
            mafia_lobby_text(game)
            + f"\n\n⚠️ این بازیکن‌ها باید اول یه بار به ربات پیام /start بزنن تا بشه نقششون رو خصوصی فرستاد: {names}\n"
            "بعدش دوباره دکمه «🚀 شروع بازی» رو بزنید.",
            reply_markup=mafia_lobby_keyboard(),
        )
        return

    roles = mafia_role_counts(len(game.players))
    pool = (
        [ROLE_MAFIA] * roles[ROLE_MAFIA]
        + [ROLE_DETECTIVE] * roles[ROLE_DETECTIVE]
        + [ROLE_DOCTOR] * roles[ROLE_DOCTOR]
        + [ROLE_CITIZEN] * roles[ROLE_CITIZEN]
    )
    random.shuffle(pool)
    for p, role in zip(game.players, pool):
        p.role = role
    await mafia_save(game)

    mafia_team_names = [p.name for p in game.players if p.role == ROLE_MAFIA]
    for p in game.players:
        text = f"نقش تو تو این بازی مافیا: {ROLE_LABELS[p.role]}"
        if p.role == ROLE_MAFIA:
            others = [n for n in mafia_team_names if n != p.name]
            text += (
                f"\nهم‌تیمی‌های مافیای تو: {'، '.join(others)}"
                if others
                else "\nتنها مافیای بازی‌ای، مراقب باش!"
            )
        try:
            await context.bot.send_message(p.id, text)
        except (Forbidden, BadRequest):
            pass

    start_msg = (
        f"✅ نقش‌ها برای هر {len(game.players)} نفر به‌صورت خصوصی فرستاده شد.\n🌙 شب اول شروع می‌شه..."
        + THANK_YOU
    )
    await mafia_edit_origin(context.bot, key, start_msg)
    await mafia_start_night(game, context)


async def mafia_start_night(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = game.key
    game.phase = "night"
    game.day_num += 1
    game.mafia_votes = {}
    game.doctor_save = None
    game.detective_checked = False

    await mafia_edit_origin(
        context.bot,
        key,
        f"🌙 شب {game.day_num} — همه بخوابید. نقش‌های خاص کارشونو تو پیوی انجام می‌دن...\n"
        f"زنده‌ها ({len(mafia_alive(game))} نفر): {'، '.join(p.name for p in mafia_alive(game))}",
    )

    mafias = mafia_alive_by_role(game, ROLE_MAFIA)
    non_mafia_alive = [p for p in mafia_alive(game) if p.role != ROLE_MAFIA]
    for m in mafias:
        if non_mafia_alive:
            await context.bot.send_message(
                m.id,
                "🔪 امشب کی رو انتخاب می‌کنی؟",
                reply_markup=mafia_targets_keyboard("mafia", key, non_mafia_alive),
            )

    for d in mafia_alive_by_role(game, ROLE_DOCTOR):
        await context.bot.send_message(
            d.id,
            "💉 امشب کی رو نجات می‌دی؟",
            reply_markup=mafia_targets_keyboard("doctor", key, mafia_alive(game)),
        )

    for det in mafia_alive_by_role(game, ROLE_DETECTIVE):
        others = [p for p in mafia_alive(game) if p.id != det.id]
        if others:
            await context.bot.send_message(
                det.id,
                "🕵️ کی رو می‌خوای استعلام بگیری؟",
                reply_markup=mafia_targets_keyboard("detective", key, others),
            )

    if context.job_queue:
        job_name = f"mafia_night_{key}_{game.day_num}"
        context.job_queue.run_once(
            mafia_night_timeout,
            MAFIA_NIGHT_SECONDS,
            data={"key": key, "day_num": game.day_num},
            name=job_name,
        )
        game.job_names.append(job_name)

    await mafia_save(game)


async def mafia_night_timeout(context: ContextTypes.DEFAULT_TYPE):
    key = context.job.data["key"]
    game = mafia_games.get(key)
    if not game or game.phase != "night" or context.job.data.get("day_num") != game.day_num:
        return
    await mafia_resolve_night(game, context, key)


async def mafia_maybe_resolve_night(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    mafias = mafia_alive_by_role(game, ROLE_MAFIA)
    doctors = mafia_alive_by_role(game, ROLE_DOCTOR)
    detectives = mafia_alive_by_role(game, ROLE_DETECTIVE)

    mafia_done = (all(m.id in game.mafia_votes for m in mafias)) if mafias else True
    doctor_done = (game.doctor_save is not None) if doctors else True
    detective_done = game.detective_checked if detectives else True

    if mafia_done and doctor_done and detective_done:
        mafia_cancel_jobs(game, context)
        await mafia_resolve_night(game, context, key)


async def mafia_resolve_night(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    if game.phase != "night":
        return
    game.phase = "day_reveal"

    victim = None
    if game.mafia_votes:
        tally: dict = {}
        for target_id in game.mafia_votes.values():
            tally[target_id] = tally.get(target_id, 0) + 1
        top = max(tally.values())
        candidates = [tid for tid, c in tally.items() if c == top]
        victim = mafia_find(game, random.choice(candidates))

    lines = [f"☀️ روز {game.day_num} شد."]
    if victim and victim.id != game.doctor_save:
        victim.alive = False
        lines.append(f"😱 دیشب {victim.name} کشته شد. نقشش بود: {ROLE_LABELS[victim.role]}")
    else:
        lines.append("🎉 دیشب کسی کشته نشد.")

    await mafia_save(game)
    await mafia_edit_origin(context.bot, key, "\n".join(lines))

    winner = mafia_check_win(game)
    if winner:
        await mafia_end_game(game, context, key, winner)
        return

    await mafia_start_day_vote(game, context, key)


async def mafia_start_day_vote(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    game.phase = "day_vote"
    game.day_votes = {}

    text = (
        f"🗳 رأی‌گیری روز {game.day_num} — کی رو می‌خواید اخراج کنید؟\n"
        "بحث رو تو همین گروه انجام بدید، بعد رأی خودتون رو با دکمه‌ها ثبت کنید 👇"
    )
    await mafia_edit_origin(context.bot, key, text, reply_markup=mafia_vote_keyboard(game))

    if context.job_queue:
        job_name = f"mafia_vote_{key}_{game.day_num}"
        context.job_queue.run_once(
            mafia_vote_timeout,
            MAFIA_VOTE_SECONDS,
            data={"key": key, "day_num": game.day_num},
            name=job_name,
        )
        game.job_names.append(job_name)

    await mafia_save(game)


async def mafia_vote_timeout(context: ContextTypes.DEFAULT_TYPE):
    key = context.job.data["key"]
    game = mafia_games.get(key)
    if not game or game.phase != "day_vote" or context.job.data.get("day_num") != game.day_num:
        return
    await mafia_resolve_day_vote(game, context, key)


async def mafia_resolve_day_vote(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE, key: str) -> None:
    if game.phase != "day_vote":
        return
    game.phase = "night_pending"

    tally: dict = {}
    for target in game.day_votes.values():
        if target == "skip":
            continue
        tally[target] = tally.get(target, 0) + 1

    if not tally:
        text = "🤷 امروز کسی اخراج نشد (رأی کافی نبود)."
    else:
        top = max(tally.values())
        candidates = [tid for tid, c in tally.items() if c == top]
        if len(candidates) > 1:
            text = "🤝 رأی‌ها مساوی شد، امروز کسی اخراج نشد."
        else:
            eliminated = mafia_find(game, candidates[0])
            eliminated.alive = False
            text = f"⚖️ {eliminated.name} با رأی جمع اخراج شد. نقشش بود: {ROLE_LABELS[eliminated.role]}"

    await mafia_save(game)
    await mafia_edit_origin(context.bot, key, text)

    winner = mafia_check_win(game)
    if winner:
        await mafia_end_game(game, context, key, winner)
        return

    await mafia_edit_origin(context.bot, key, text + "\n\n🌙 شب بعدی شروع می‌شه...")
    await mafia_start_night(game, context)


async def mafia_end_game(game: MafiaGame, context: ContextTypes.DEFAULT_TYPE, key: str, winner: str) -> None:
    mafia_cancel_jobs(game, context)
    reveal = "\n".join(f"{p.name}: {ROLE_LABELS[p.role]}" for p in game.players)
    winner_label = "🔪 مافیا" if winner == "mafia" else "👨‍🌾 شهروندان"
    await mafia_edit_origin(
        context.bot,
        key,
        f"🏁 بازی مافیا تموم شد! برنده: {winner_label} 🎉\n\nنقش همه:\n{reveal}"
        + THANK_YOU,
    )
    del mafia_games[key]
    await mafia_delete_saved(key)


async def mafia_handle_night_action(
    query, user, role_tag: str, key: str, target_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    game = mafia_games.get(key)
    if not game or game.phase != "night":
        await query.answer("الان شب نیست، این دکمه دیگه اعتبار نداره.", show_alert=True)
        return

    actor = mafia_find(game, user.id)
    if not actor or not actor.alive:
        await query.answer("تو تو این بازی نیستی یا حذف شدی.", show_alert=True)
        return

    target = mafia_find(game, target_id)
    if not target or not target.alive:
        await query.answer("این بازیکن دیگه تو بازی نیست.", show_alert=True)
        return

    if role_tag == "mafia":
        if actor.role != ROLE_MAFIA:
            await query.answer("این دکمه مال تو نیست.", show_alert=True)
            return
        game.mafia_votes[actor.id] = target.id
        await query.answer(f"رأیت ثبت شد: {target.name} ✅")

    elif role_tag == "doctor":
        if actor.role != ROLE_DOCTOR:
            await query.answer("این دکمه مال تو نیست.", show_alert=True)
            return
        game.doctor_save = target.id
        await query.answer(f"تصمیمت ثبت شد: نجات {target.name} ✅")

    elif role_tag == "detective":
        if actor.role != ROLE_DETECTIVE:
            await query.answer("این دکمه مال تو نیست.", show_alert=True)
            return
        game.detective_checked = True
        result = "مافیا هست! 🔪" if target.role == ROLE_MAFIA else "مافیا نیست ✅"
        await query.answer(f"نتیجه استعلام {target.name}: {result}", show_alert=True)

    else:
        return

    await mafia_save(game)
    await mafia_maybe_resolve_night(game, context, key)


async def mafia_handle_vote(
    query, user, target_raw: str, key: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    game = mafia_games.get(key)
    if not game or game.phase != "day_vote":
        await query.answer("الان وقت رأی‌گیری نیست.", show_alert=True)
        return

    voter = mafia_find(game, user.id)
    if not voter or not voter.alive:
        await query.answer("تو نمی‌تونی رأی بدی (تو بازی نیستی یا حذف شدی).", show_alert=True)
        return

    if target_raw == "skip":
        game.day_votes[voter.id] = "skip"
    else:
        target = mafia_find(game, int(target_raw))
        if not target or not target.alive:
            await query.answer("این بازیکن دیگه تو بازی نیست.", show_alert=True)
            return
        game.day_votes[voter.id] = target.id

    await mafia_save(game)
    await query.answer("رأیت ثبت شد ✅")

    try:
        await query.edit_message_reply_markup(reply_markup=mafia_vote_keyboard(game))
    except BadRequest:
        pass

    if len(game.day_votes) >= len(mafia_alive(game)):
        mafia_cancel_jobs(game, context)
        await mafia_resolve_day_vote(game, context, key)


async def mafia_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    if data == "mafia_join":
        game = mafia_games.get(key)
        if not game or game.phase != "joining":
            await query.answer("بازی مافیایی برای پیوستن پیدا نشد.", show_alert=True)
            return
        if any(p.id == user.id for p in game.players):
            await query.answer("قبلاً پیوستی، صبر کن بقیه هم بیان.", show_alert=True)
            return
        game.players.append(MafiaPlayer(id=user.id, name=user.first_name))
        await mafia_save(game)
        await query.edit_message_text(mafia_lobby_text(game), reply_markup=mafia_lobby_keyboard())
        await query.answer("وارد بازی شدی! ✅")
        return

    if data == "mafia_forcebegin":
        game = mafia_games.get(key)
        if not game or game.phase != "joining":
            await query.answer("بازی مافیایی در حال جمع‌آوری بازیکن پیدا نشد.", show_alert=True)
            return
        if user.id != game.started_by:
            await query.answer("فقط کسی که بازی رو شروع کرده می‌تونه زودتر شروعش کنه.", show_alert=True)
            return
        if len(game.players) < MAFIA_MIN_PLAYERS:
            await query.answer(
                f"حداقل {MAFIA_MIN_PLAYERS} نفر لازمه، فعلاً {len(game.players)} نفرین.", show_alert=True
            )
            return
        await query.answer("بازی شروع می‌شه ✅")
        await mafia_try_begin(key, context, auto=False)
        return

    if data == "mafia_cancel":
        game = mafia_games.get(key)
        if not game:
            await query.answer("بازی مافیایی پیدا نشد.", show_alert=True)
            return
        if user.id != game.started_by:
            await query.answer("فقط کسی که بازی رو شروع کرده می‌تونه لغوش کنه.", show_alert=True)
            return
        mafia_cancel_jobs(game, context)
        del mafia_games[key]
        await mafia_delete_saved(key)
        await query.edit_message_text("بازی مافیا لغو شد.")
        await query.answer("لغو شد.")
        return

    if data.startswith("mafia_act|"):
        _, role_tag, act_key, target_id_str = data.split("|", 3)
        await mafia_handle_night_action(query, user, role_tag, act_key, int(target_id_str), context)
        return

    if data.startswith("mafia_vote|"):
        _, target_raw = data.split("|", 1)
        await mafia_handle_vote(query, user, target_raw, key, context)
        return


# ======================== کوییز ========================

QUIZ_ROUNDS = 10
QUIZ_ROUND_SECONDS = 8
QUIZ_MIN_PLAYERS = 2
QUIZ_MAX_PLAYERS = 10
QUIZ_DELAY_SECONDS = 5

# سوالات عمومی (ترجمه شده و اصلاح شده)
QUIZ_TRIVIA = [
    {"q": "پایتخت ژاپن کجاست؟", "options": ["توکیو", "پکن", "سئول", "بانکوک"], "correct": 0},
    {"q": "بزرگ‌ترین اقیانوس جهان کدومه؟", "options": ["اطلس", "آرام", "هند", "منجمد شمالی"], "correct": 1},
    {"q": "سریع‌ترین حیوان خشکی‌زی کدومه؟", "options": ["شیر", "یوزپلنگ", "اسب", "گورخر"], "correct": 1},
    {"q": "مولکول آب از چند اتم هیدروژن تشکیل شده؟", "options": ["یک", "دو", "سه", "چهار"], "correct": 1},
    {"q": "نزدیک‌ترین سیاره به خورشید کدومه؟", "options": ["زهره", "زمین", "عطارد", "مریخ"], "correct": 2},
    {"q": "بلندترین رودخانه جهان کدومه؟", "options": ["آمازون", "نیل", "میسیسیپی", "یانگ‌تسه"], "correct": 1},
    {"q": "واحد پول ژاپن چیه؟", "options": ["وون", "ین", "یوان", "دلار"], "correct": 1},
    {"q": "چند تا قاره تو دنیا داریم؟", "options": ["پنج", "شش", "هفت", "هشت"], "correct": 2},
    {"q": "بزرگ‌ترین کشور جهان از نظر مساحت کدومه؟", "options": ["چین", "کانادا", "آمریکا", "روسیه"], "correct": 3},
    {"q": "المپیک تابستانی هر چند سال یک‌بار برگزار می‌شه؟", "options": ["۲ سال", "۳ سال", "۴ سال", "۵ سال"], "correct": 2},
    {"q": "قلب انسان چند تا حفره داره؟", "options": ["دو", "سه", "چهار", "پنج"], "correct": 2},
    {"q": "برج ایفل تو کدوم شهره؟", "options": ["لندن", "رم", "پاریس", "برلین"], "correct": 2},
    {"q": "کدوم تیم قهرمان جام جهانی ۲۰۱۸ شد؟", "options": ["برزیل", "آلمان", "فرانسه", "کرواسی"], "correct": 2},
    {"q": "بهترین گلزن تاریخ فوتبال (با احتساب بازی‌های رسمی) کیه؟", "options": ["پله", "مسی", "رونالدو", "مارادونا"], "correct": 2},
    {"q": "کدوم بازی ویدیویی بیشترین فروش تاریخ رو داره؟", "options": ["Minecraft", "GTA V", "Tetris", "PUBG"], "correct": 0},
    {"q": "بازی The Witcher 3 توسط کدوم شرکت ساخته شده؟", "options": ["CD Projekt Red", "Rockstar", "Ubisoft", "Bethesda"], "correct": 0},
    {"q": "کدوم فیلم برندهٔ اسکار بهترین فیلم در سال ۲۰۲۰ شد؟", "options": ["1917", "Joker", "Parasite", "Once Upon a Time in Hollywood"], "correct": 2},
    {"q": "کدوم بازیکن بیشترین توپ طلا رو برده؟", "options": ["مسی", "رونالدو", "پلاتینی", "بکام"], "correct": 0},
    {"q": "محبوب‌ترین بازی موبایل سال ۲۰۲۲ کدوم بود؟", "options": ["Candy Crush", "PUBG Mobile", "Genshin Impact", "Roblox"], "correct": 2},
    {"q": "کشور میزبان جام جهانی ۲۰۲۲ کجا بود؟", "options": ["روسیه", "قطر", "برزیل", "آلمان"], "correct": 1},
    {"q": "سریال محبوب Game of Thrones بر اساس کتاب‌های کدوم نویسنده ساخته شده؟", "options": ["J.R.R. Tolkien", "George R.R. Martin", "J.K. Rowling", "Stephen King"], "correct": 1},
    {"q": "کدوم شرکت سازندهٔ کنسول PlayStation است؟", "options": ["Microsoft", "Sony", "Nintendo", "Sega"], "correct": 1},
]

# سوالات ایموجی (پرچم‌ها و ترکیب‌های تصویری)
QUIZ_EMOJI = [
    {"q": "این پرچم مال کدوم کشوره؟ 🇯🇵", "options": ["چین", "ژاپن", "کره جنوبی", "ویتنام"], "correct": 1},
    {"q": "این پرچم مال کدوم کشوره؟ 🇧🇷", "options": ["آرژانتین", "پرتغال", "برزیل", "مکزیک"], "correct": 2},
    {"q": "این پرچم مال کدوم کشوره؟ 🇮🇹", "options": ["اسپانیا", "ایتالیا", "فرانسه", "ایرلند"], "correct": 1},
    {"q": "این پرچم مال کدوم کشوره؟ 🇨🇦", "options": ["آمریکا", "کانادا", "استرالیا", "انگلیس"], "correct": 1},
    {"q": "این پرچم مال کدوم کشوره؟ 🇩🇪", "options": ["اتریش", "بلژیک", "آلمان", "هلند"], "correct": 2},
    {"q": "این ایموجی‌ها کدوم داستانو نشون می‌ده؟ 🦁👑", "options": ["شیر شاه", "مادگاسکار", "زوتوپیا", "جنگل کتاب"], "correct": 0},
    {"q": "این ایموجی‌ها کدوم شخصیتو نشون می‌ده؟ 🕷️👨", "options": ["بتمن", "مرد عنکبوتی", "سوپرمن", "آیرون‌من"], "correct": 1},
    {"q": "این ایموجی‌ها کدوم ورزشو نشون می‌ده؟ ⚽🥅", "options": ["بسکتبال", "فوتبال", "والیبال", "تنیس"], "correct": 1},
    {"q": "این ایموجی‌ها کدوم میوه‌رو نشون می‌ده؟ 🍌🐒", "options": ["سیب", "پرتقال", "موز", "انگور"], "correct": 2},
    {"q": "این پرچم مال کدوم کشوره؟ 🇪🇸", "options": ["ایتالیا", "پرتغال", "اسپانیا", "یونان"], "correct": 2},
    {"q": "این پرچم مال کدوم کشوره؟ 🇫🇷", "options": ["ایتالیا", "فرانسه", "آلمان", "بلژیک"], "correct": 1},
    {"q": "این ایموجی‌ها کدوم بازی رو نشون می‌ده؟ 🎮🕹️", "options": ["بازی کامپیوتری", "بازی رومیزی", "بازی ورق", "بازی فکری"], "correct": 0},
    {"q": "این ایموجی‌ها کدوم فیلم رو یادآوری می‌کنه؟ 🚀🌌", "options": ["پیشتازان فضا", "جنگ ستارگان", "مریخی", "بیگانه"], "correct": 1},
    {"q": "این پرچم مال کدوم کشوره؟ 🇬🇧", "options": ["انگلیس", "اسکاتلند", "ولز", "ایرلند"], "correct": 0},
    {"q": "این ایموجی‌ها کدوم شخصیت کارتونی‌اند؟ 🐭👖", "options": ["میکی ماوس", "باب اسفنجی", "تام و جری", "دورا"], "correct": 1},
]


@dataclass
class QuizGame:
    key: str
    starter_id: int
    players: list = field(default_factory=list)
    phase: str = "lobby"
    round_num: int = 0
    total_rounds: int = QUIZ_ROUNDS
    question_text: str = ""
    options: list = field(default_factory=list)
    correct_index: int = -1
    round_active: bool = False
    answered_correctly: bool = False
    winner_id: Optional[int] = None
    wrong_users: set = field(default_factory=set)
    used_trivia: set = field(default_factory=set)
    used_emoji: set = field(default_factory=set)
    message_id: Optional[int] = None
    timeout_job_name: Optional[str] = None
    delay_job_name: Optional[str] = None

    def get_player_score(self, uid: int) -> int:
        for p in self.players:
            if p["id"] == uid:
                return p.get("score", 0)
        return 0

    def add_score(self, uid: int, delta: int = 1) -> None:
        for p in self.players:
            if p["id"] == uid:
                p["score"] = p.get("score", 0) + delta
                break


quiz_games: dict[str, QuizGame] = {}


def quiz_lobby_text(game: QuizGame) -> str:
    names = "، ".join(p["name"] for p in game.players)
    return (
        f"🧠 بازی «اولین نفر جواب بده»\n"
        f"(حداقل {QUIZ_MIN_PLAYERS}، حداکثر {QUIZ_MAX_PLAYERS} نفر)\n\n"
        f"نفرات فعلی ({len(game.players)} نفر): {names}\n\n"
        f"فقط {game.players[0]['name'] if game.players else ''} (سازنده) می‌تونه شروع کنه 👇"
        + THANK_YOU
    )


def quiz_lobby_keyboard(game: QuizGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن ({len(game.players)}/{QUIZ_MAX_PLAYERS})",
                              callback_data="quiz_join")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="quiz_start")],
        [cancel_join_button()],
    ])


def quiz_inline_result() -> InlineQueryResultArticle:
    dummy = QuizGame(key="", starter_id=0)
    dummy.players = [{"id": 0, "name": "کاربر", "score": 0}]
    return InlineQueryResultArticle(
        id=f"quiz-{uuid.uuid4()}",
        title="🧠 اولین نفر جواب بده",
        description=f"{QUIZ_MIN_PLAYERS} تا {QUIZ_MAX_PLAYERS} نفر — هر کی زودتر جواب درست بده امتیاز می‌گیره",
        input_message_content=InputTextMessageContent(quiz_lobby_text(dummy)),
        reply_markup=quiz_lobby_keyboard(dummy),
    )


def quiz_pick_bank_item(bank: list, used: set) -> dict:
    if len(used) >= len(bank):
        used.clear()
    available = [i for i in range(len(bank)) if i not in used]
    idx = random.choice(available)
    used.add(idx)
    return bank[idx]


def quiz_pick_question(game: QuizGame) -> None:
    category = random.choice(["math", "trivia", "emoji"])
    if category == "math":
        op = random.choice(["+", "-", "×"])
        if op == "+":
            a, b = random.randint(2, 50), random.randint(2, 50)
            correct = a + b
        elif op == "-":
            a, b = random.randint(2, 50), random.randint(2, 50)
            a, b = max(a, b), min(a, b)
            correct = a - b
        else:
            a, b = random.randint(2, 12), random.randint(2, 12)
            correct = a * b

        options = {correct}
        while len(options) < 4:
            candidate = correct + random.choice([d for d in range(-10, 11) if d != 0])
            if candidate >= 0:
                options.add(candidate)

        options_list = list(options)
        correct_index = options_list.index(correct)
        game.question_text = f"[🔢 ریاضی] حاصل {a} {op} {b} چند می‌شه؟"
        game.options = [str(o) for o in options_list]
        game.correct_index = correct_index
    elif category == "trivia":
        item = quiz_pick_bank_item(QUIZ_TRIVIA, game.used_trivia)
        game.question_text = f"[🧠 عمومی] {item['q']}"
        game.options = item["options"]
        game.correct_index = item["correct"]
    else:
        item = quiz_pick_bank_item(QUIZ_EMOJI, game.used_emoji)
        game.question_text = f"[🖼 تصویری] {item['q']}"
        game.options = item["options"]
        game.correct_index = item["correct"]

    correct_answer_text = game.options[game.correct_index]
    shuffled_options = game.options[:]
    random.shuffle(shuffled_options)
    game.options = shuffled_options
    game.correct_index = game.options.index(correct_answer_text)


def quiz_answer_keyboard(options: list) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(opt, callback_data=f"quiz_ans_{i}") for i, opt in enumerate(options)]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def quiz_round_text(game: QuizGame, show_result: bool = False) -> str:
    lines = [
        f"🧠 اولین نفر جواب بده! (دور {game.round_num}/{game.total_rounds})",
        "⚡ هر کی زودتر گزینه‌ی درست رو بزنه، امتیاز می‌گیره!",
        "",
        game.question_text,
    ]
    if game.players:
        scores_lines = []
        for p in game.players:
            scores_lines.append(f"  {p['name']}: {p.get('score', 0)}")
        lines.append("")
        lines.append("🏅 امتیازها:")
        lines.extend(scores_lines)
    if show_result:
        lines.append("")
        if game.answered_correctly and game.winner_id is not None:
            winner_name = next((p["name"] for p in game.players if p["id"] == game.winner_id), "؟")
            lines.append(f"✅ {winner_name} زودتر از همه درست جواب داد!")
            lines.append(f"جواب درست: {game.options[game.correct_index]}")
        else:
            lines.append(f"⌛ وقت تموم شد! جواب درست: {game.options[game.correct_index]}")
    lines.append(THANK_YOU)
    return "\n".join(lines)


def quiz_final_text(game: QuizGame) -> str:
    if not game.players:
        return "🏁 بازی «اولین نفر جواب بده» تموم شد! متأسفانه کسی بازی نکرد." + THANK_YOU
    sorted_players = sorted(game.players, key=lambda p: p.get("score", 0), reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏁 بازی «اولین نفر جواب بده» تموم شد! نتیجه نهایی:"]
    for i, p in enumerate(sorted_players):
        medal = medals[i] if i < 3 else "🔹"
        lines.append(f"{medal} {p['name']}: {p.get('score', 0)} امتیاز")
    if sorted_players:
        lines.append(f"\n🏆 برنده: {sorted_players[0]['name']} 🎉")
    return "\n".join(lines) + THANK_YOU


async def quiz_edit_origin(bot, game: QuizGame, text: str, reply_markup=None) -> None:
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(game.key), message_id=game.message_id,
                                        reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=game.key, reply_markup=reply_markup)
    except BadRequest:
        pass


async def quiz_start_round(game: QuizGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    if game.phase != "playing" or game.round_num > game.total_rounds:
        return

    quiz_pick_question(game)
    game.round_active = True
    game.answered_correctly = False
    game.winner_id = None
    game.wrong_users = set()

    text = quiz_round_text(game, show_result=False)
    markup = quiz_answer_keyboard(game.options)
    await quiz_edit_origin(context.bot, game, text, markup)

    if context.job_queue:
        if game.timeout_job_name:
            for job in context.job_queue.get_jobs_by_name(game.timeout_job_name):
                job.schedule_removal()
            game.timeout_job_name = None
        job_name = f"quiz_timeout_{game.key}_{game.round_num}"
        context.job_queue.run_once(
            quiz_round_timeout,
            QUIZ_ROUND_SECONDS,
            data={"key": game.key, "round_num": game.round_num},
            name=job_name,
        )
        game.timeout_job_name = job_name


async def quiz_advance(game: QuizGame, context: ContextTypes.DEFAULT_TYPE, prefix_text: str = "") -> None:
    if game.timeout_job_name:
        for job in context.job_queue.get_jobs_by_name(game.timeout_job_name):
            job.schedule_removal()
        game.timeout_job_name = None

    if not game.answered_correctly and game.winner_id is None:
        text = quiz_round_text(game, show_result=True)
        await quiz_edit_origin(context.bot, game, text, reply_markup=None)

    if game.round_num < game.total_rounds:
        if context.job_queue:
            if game.delay_job_name:
                for job in context.job_queue.get_jobs_by_name(game.delay_job_name):
                    job.schedule_removal()
                game.delay_job_name = None
            job_name = f"quiz_delay_{game.key}"
            context.job_queue.run_once(
                quiz_delay_callback,
                QUIZ_DELAY_SECONDS,
                data={"key": game.key},
                name=job_name,
            )
            game.delay_job_name = job_name
    else:
        game.phase = "finished"
        text = quiz_final_text(game)
        await quiz_edit_origin(context.bot, game, text, reply_markup=None)
        quiz_games.pop(game.key, None)


async def quiz_delay_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    game = quiz_games.get(data["key"])
    if not game or game.phase != "playing":
        return
    game.delay_job_name = None
    game.round_num += 1
    await quiz_start_round(game, context)


async def quiz_round_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    game = quiz_games.get(data["key"])
    if not game or game.round_num != data["round_num"] or not game.round_active:
        return
    game.round_active = False
    game.answered_correctly = False
    game.winner_id = None
    text = quiz_round_text(game, show_result=True)
    await quiz_edit_origin(context.bot, game, text, reply_markup=None)
    await quiz_advance(game, context)


async def quiz_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    game = quiz_games.get(key)
    if not game:
        await query.answer("این بازی «اولین نفر جواب بده» پیدا نشد یا تموم شده.", show_alert=True)
        return

    if data == "quiz_join":
        if game.phase != "lobby":
            await query.answer("بازی شروع شده، نمی‌تونی بپیوندی.", show_alert=True)
            return
        if any(p["id"] == user.id for p in game.players):
            await query.answer("قبلاً پیوستی!", show_alert=True)
            return
        if len(game.players) >= QUIZ_MAX_PLAYERS:
            await query.answer(f"حداکثر {QUIZ_MAX_PLAYERS} نفر.", show_alert=True)
            return
        game.players.append({"id": user.id, "name": user.first_name, "score": 0})
        await query.edit_message_text(
            quiz_lobby_text(game),
            reply_markup=quiz_lobby_keyboard(game)
        )
        await query.answer("پیوستی! ✅")
        return

    if data == "quiz_start":
        if game.phase != "lobby":
            await query.answer()
            return
        if user.id != game.starter_id:
            await query.answer(f"فقط {game.players[0]['name']} می‌تواند شروع کند.", show_alert=True)
            return
        if len(game.players) < QUIZ_MIN_PLAYERS:
            await query.answer(f"حداقل {QUIZ_MIN_PLAYERS} نفر لازم است.", show_alert=True)
            return
        game.phase = "playing"
        game.round_num = 1
        for p in game.players:
            p["score"] = 0
        await query.answer("بازی شروع شد! 🚀")
        await quiz_start_round(game, context)
        return

    if not data.startswith("quiz_ans_"):
        await query.answer()
        return

    if game.phase != "playing":
        await query.answer("بازی تمام شده یا هنوز شروع نشده.", show_alert=True)
        return

    if not game.round_active:
        await query.answer("این دور قبلاً تموم شده، منتظر سوال بعدی باش.", show_alert=True)
        return

    if user.id not in [p["id"] for p in game.players]:
        await query.answer("تو تو این بازی نیستی!", show_alert=True)
        return

    if game.answered_correctly:
        await query.answer("این دور قبلاً پاسخ درست داده شده!", show_alert=True)
        return

    if user.id in game.wrong_users:
        await query.answer("قبلاً رو این سوال اشتباه زدی، بمون تا سوال بعدی بیاد.", show_alert=True)
        return

    idx = int(data.split("_", 2)[2])
    if idx != game.correct_index:
        game.wrong_users.add(user.id)
        await query.answer("❌ جواب اشتباه بود، دیگه رو این سوال نمی‌تونی امتحان کنی.", show_alert=True)
        return

    game.answered_correctly = True
    game.winner_id = user.id
    game.round_active = False
    for p in game.players:
        if p["id"] == user.id:
            p["score"] = p.get("score", 0) + 1
            break
    await query.answer("✅ آفرین، درست جواب دادی! منتظر سوال بعدی باش.")

    text = quiz_round_text(game, show_result=True)
    await quiz_edit_origin(context.bot, game, text, reply_markup=None)
    await quiz_advance(game, context)


# ======================== دار بازی (رفع باگ شده) ========================

HANGMAN_MAX_WRONG = 6
HANGMAN_MIN_PLAYERS = 2
HANGMAN_MAX_PLAYERS = 8

HANGMAN_ALPHABET = list("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

HANGMAN_WORDS = {
    "🐾 حیوانات": ["گربه", "سگ", "شیر", "پلنگ", "روباه", "خرگوش", "فیل", "زرافه", "کبوتر", "گاو", "اسب", "گوسفند", "ببر", "میمون"],
    "🌍 کشورها": ["ایران", "ترکیه", "فرانسه", "ژاپن", "برزیل", "کانادا", "مصر", "یونان", "هند", "چین", "روسیه"],
    "🍽 خوراکی": ["پیتزا", "ساندویچ", "کباب", "برنج", "ماست", "پنیر", "نان", "سیب", "موز", "انگور", "هندوانه", "خیار"],
    "📦 وسایل": ["کتاب", "قلم", "میز", "صندلی", "تلفن", "ساعت", "دوچرخه", "کیف", "چتر", "عینک"],
    "💼 شغل‌ها": ["پزشک", "معلم", "نجار", "خلبان", "نویسنده", "نقاش", "مهندس", "وکیل", "پرستار"],
}


@dataclass
class HangmanGame:
    key: str
    starter_id: int
    starter_name: str
    message_id: Optional[int] = None
    players: list = field(default_factory=list)
    turn_index: int = 0
    phase: str = "lobby"
    category: str = ""
    word: str = ""
    guessed: set = field(default_factory=set)
    wrong: list = field(default_factory=list)


hangman_games: dict[str, HangmanGame] = {}
pending_hangman_guess: dict[int, str] = {}


def hangman_pick_word(game: HangmanGame) -> None:
    category = random.choice(list(HANGMAN_WORDS.keys()))
    game.category = category
    game.word = random.choice(HANGMAN_WORDS[category])
    game.guessed = set()
    game.wrong = []
    game.turn_index = 0
    game.phase = "playing"


def hangman_current_player(game: HangmanGame) -> dict:
    return game.players[game.turn_index]


def hangman_advance_turn(game: HangmanGame) -> None:
    game.turn_index = (game.turn_index + 1) % len(game.players)


def hangman_masked_word(game: HangmanGame) -> str:
    return "  ".join(ch if ch in game.guessed else "▫️" for ch in game.word)


def hangman_lives_line(game: HangmanGame) -> str:
    remaining = max(0, HANGMAN_MAX_WRONG - len(game.wrong))
    return "❤️" * remaining + "🖤" * len(game.wrong)


def hangman_lobby_placeholder_text(starter_name: str) -> str:
    return (
        f"🎯 {starter_name} می‌خواد بازی «دار بازی» رو شروع کنه ({HANGMAN_MIN_PLAYERS} تا {HANGMAN_MAX_PLAYERS} نفره)!\n"
        "یه کلمه‌ی مخفی هست که باید نوبتی حرف‌به‌حرف یا با تایپ کل کلمه حدسش بزنید.\n\n"
        f"نفرات فعلی (۱ نفر، حداقل {HANGMAN_MIN_PLAYERS} نفر لازمه): {starter_name}\n\n"
        "بقیه می‌تونن با دکمه‌ی پایین بپیوندن 👇"
        + THANK_YOU
    )


def hangman_lobby_text(game: HangmanGame) -> str:
    names = "، ".join(p["name"] for p in game.players)
    return (
        f"🎯 {game.starter_name} می‌خواد بازی «دار بازی» رو شروع کنه ({HANGMAN_MIN_PLAYERS} تا {HANGMAN_MAX_PLAYERS} نفره)!\n"
        "یه کلمه‌ی مخفی هست که باید نوبتی حرف‌به‌حرف یا با تایپ کل کلمه حدسش بزنید.\n\n"
        f"نفرات فعلی ({len(game.players)} نفر، حداقل {HANGMAN_MIN_PLAYERS} نفر لازمه): {names}\n\n"
        f"بقیه می‌تونن با دکمه‌ی پایین بپیوندن؛ فقط {game.starter_name} می‌تونه بازی رو شروع کنه 👇"
        + THANK_YOU
    )


def hangman_status_text(game: HangmanGame) -> str:
    current = hangman_current_player(game)
    lines = [
        f"🎯 دار بازی   •   دسته: {game.category}",
        hangman_lives_line(game),
        "",
        hangman_masked_word(game),
        "",
        f"🔸 نوبت: {current['name']}",
    ]
    if game.wrong:
        lines += ["", "حرف/حدس‌های اشتباه: " + " ، ".join(str(w) for w in game.wrong)]
    return "\n".join(lines)


def hangman_final_text(game: HangmanGame, winner_name: Optional[str], streak: int = 0) -> str:
    if winner_name:
        text = (
            f"🎉 آفرین {winner_name}! کلمه رو درست حدس زدی.\n\n"
            f"کلمه: «{game.word}»   (دسته: {game.category})"
        )
        text += win_streak_line(winner_name, streak)
        text += "\n\nدوست دارید یه بار دیگه بازی کنید؟ 👇"
        return text + THANK_YOU
    return (
        "💔 جون‌ها تموم شد، این دور کسی نبرد.\n\n"
        f"کلمه‌ی درست: «{game.word}»   (دسته: {game.category})\n\n"
        "دوست دارید دوباره امتحان کنید؟ 👇"
        + THANK_YOU
    )


def hangman_lobby_keyboard(game: HangmanGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن ({len(game.players)}/{HANGMAN_MAX_PLAYERS})", callback_data="hangman_join")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="hangman_start")],
        [cancel_join_button()],
    ])


def hangman_lobby_keyboard_placeholder() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن (1/{HANGMAN_MAX_PLAYERS})", callback_data="hangman_join")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="hangman_start")],
        [cancel_join_button()],
    ])


def hangman_again_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔁 بازی دوباره", callback_data="hangman_again")]])


def hangman_letters_keyboard(game: HangmanGame) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, letter in enumerate(HANGMAN_ALPHABET):
        if letter in game.guessed:
            row.append(InlineKeyboardButton(f"✅{letter}", callback_data="hangman_used"))
        elif letter in game.wrong:
            row.append(InlineKeyboardButton(f"❌{letter}", callback_data="hangman_used"))
        else:
            row.append(InlineKeyboardButton(letter, callback_data=f"hangman_letter_{i:02d}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✍️ حدس کل کلمه", callback_data="hangman_guess_prompt")])
    return InlineKeyboardMarkup(rows)


def hangman_inline_result(starter_name: str) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=f"hangman-{uuid.uuid4()}",
        title="🎯 دار بازی",
        description=f"{HANGMAN_MIN_PLAYERS} تا {HANGMAN_MAX_PLAYERS} نفره — نوبتی حرف یا کل کلمه رو حدس بزنید",
        input_message_content=InputTextMessageContent(hangman_lobby_placeholder_text(starter_name)),
        reply_markup=hangman_lobby_keyboard_placeholder(),
    )


async def hangman_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    key = str(chat_id)
    
    if key in hangman_games:
        await update.message.reply_text("⚠️ در حال حاضر یک بازی دار بازی در این چت در جریان است.")
        return
        
    game = HangmanGame(key=key, starter_id=user.id, starter_name=user.first_name)
    game.players = [{"id": user.id, "name": user.first_name}]
    hangman_games[key] = game
    sent = await update.message.reply_text(
        hangman_lobby_text(game),
        reply_markup=hangman_lobby_keyboard(game),
    )
    game.message_id = sent.message_id


async def hangman_edit_origin(bot, game: HangmanGame, text: str, reply_markup=None) -> None:
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(game.key), message_id=game.message_id, reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=game.key, reply_markup=reply_markup)
    except BadRequest as e:
        logger.warning(f"خطا در ویرایش پیام دار بازی: {e}")


async def hangman_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    game = hangman_games.get(key)
    if not game:
        await query.answer("این بازی «دار بازی» پیدا نشد یا تموم شده.", show_alert=True)
        return

    try:
        if data == "hangman_used":
            await query.answer("این حرف رو قبلاً امتحان کردین.", show_alert=True)
            return

        if data == "hangman_join":
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، دیگه نمی‌شه پیوست.", show_alert=True)
                return
            if any(p["id"] == user.id for p in game.players):
                await query.answer("قبلاً پیوستی!", show_alert=True)
                return
            if len(game.players) >= HANGMAN_MAX_PLAYERS:
                await query.answer(f"لابی پره (حداکثر {HANGMAN_MAX_PLAYERS} نفر).", show_alert=True)
                return
            game.players.append({"id": user.id, "name": user.first_name})
            await query.edit_message_text(hangman_lobby_text(game), reply_markup=hangman_lobby_keyboard(game))
            await query.answer("پیوستی! ✅")
            return

        if data == "hangman_start":
            if game.phase != "lobby":
                await query.answer()
                return
            if user.id != game.starter_id:
                await query.answer(f"فقط {game.starter_name} می‌تونه بازی رو شروع کنه.", show_alert=True)
                return
            if len(game.players) < HANGMAN_MIN_PLAYERS:
                await query.answer(
                    f"حداقل {HANGMAN_MIN_PLAYERS} نفر لازمه، فعلاً {len(game.players)} نفرین.", show_alert=True
                )
                return
            hangman_pick_word(game)
            await query.edit_message_text(hangman_status_text(game), reply_markup=hangman_letters_keyboard(game))
            await query.answer("بازی شروع شد! 🎯")
            return

        if data == "hangman_again":
            if user.id != game.starter_id:
                await query.answer(f"فقط {game.starter_name} می‌تونه بازی جدید بسازه.", show_alert=True)
                return
            game.players = [{"id": game.starter_id, "name": game.starter_name}]
            game.turn_index = 0
            game.category = ""
            game.word = ""
            game.guessed = set()
            game.wrong = []
            game.phase = "lobby"
            await query.edit_message_text(hangman_lobby_text(game), reply_markup=hangman_lobby_keyboard(game))
            await query.answer("لابی جدید ساخته شد، بقیه رو دعوت کن! 🔁")
            return

        if data == "hangman_guess_prompt":
            if game.phase != "playing":
                await query.answer("بازی در حال اجرا نیست.", show_alert=True)
                return
            current = hangman_current_player(game)
            if user.id != current["id"]:
                await query.answer(f"الان نوبت {current['name']}ه، صبر کن نوبتت بشه.", show_alert=True)
                return
            pending_hangman_guess[user.id] = key
            try:
                await context.bot.send_message(
                    user.id,
                    f"✍️ نوبت توئه! کلمه رو حدس بزن (دسته: {game.category}) و همینجا برام تایپ کن و بفرست:",
                )
                await query.answer("به پیوی ربات نگاه کن و کلمه رو بفرست ✍️", show_alert=True)
            except Forbidden:
                pending_hangman_guess.pop(user.id, None)
                await query.answer("اول باید یه بار به ربات تو پیوی /start بزنی، بعد دوباره امتحان کن.", show_alert=True)
            return

        if data.startswith("hangman_letter_"):
            if game.phase != "playing":
                await query.answer("بازی در حال اجرا نیست.", show_alert=True)
                return

            current = hangman_current_player(game)
            if user.id != current["id"]:
                await query.answer(f"الان نوبت {current['name']}ه، صبر کن نوبتت بشه.", show_alert=True)
                return

            idx = int(data.split("_", 2)[2])
            if idx >= len(HANGMAN_ALPHABET):
                await query.answer("حرف نامعتبر.", show_alert=True)
                return
                
            letter = HANGMAN_ALPHABET[idx]
            hit = letter in game.word

            if hit:
                game.guessed.add(letter)
            else:
                game.wrong.append(letter)

            if all(ch in game.guessed for ch in game.word):
                game.phase = "finished"
                participant_ids = [p["id"] for p in game.players]
                streak = bump_win_streak_group(current["id"], participant_ids)
                user_names[current["id"]] = current["name"]
                await stats_save_user(current["id"], current["name"], streak)
                await send_streak_update(context, current["id"], current["name"])
                await query.answer(f"آفرین «{letter}»! کلمه کامل شد 🎉" if hit else f"«{letter}» تو کلمه نبود ❌")
                await query.edit_message_text(
                    hangman_final_text(game, winner_name=current["name"], streak=streak),
                    reply_markup=hangman_again_keyboard(),
                )
                return

            if len(game.wrong) >= HANGMAN_MAX_WRONG:
                game.phase = "finished"
                participant_ids = [p["id"] for p in game.players]
                bump_win_streak_group(None, participant_ids)
                await query.answer("جون‌ها تموم شد ❌")
                await query.edit_message_text(
                    hangman_final_text(game, winner_name=None), reply_markup=hangman_again_keyboard()
                )
                return

            await query.answer(f"آفرین «{letter}»! ✅ نوبت رد شد" if hit else f"«{letter}» تو کلمه نبود، نوبت رد شد ❌")
            hangman_advance_turn(game)
            await query.edit_message_text(hangman_status_text(game), reply_markup=hangman_letters_keyboard(game))
            return

        await query.answer("دکمه نامعتبر.", show_alert=True)

    except Exception as e:
        logger.error(f"خطا در hangman_button_handler: {e}")
        await query.answer("خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)


async def hangman_guess_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
        
    key = pending_hangman_guess.pop(user.id, None)
    if not key:
        return

    game = hangman_games.get(key)
    if not game or game.phase != "playing":
        await update.message.reply_text("این بازی «دار بازی» دیگه فعال نیست.")
        return

    current = hangman_current_player(game)
    if user.id != current["id"]:
        await update.message.reply_text("نوبتت گذشته، الان نوبت یکی دیگه‌ست.")
        return

    guess = (update.message.text or "").strip()
    if not guess:
        await update.message.reply_text("لطفاً یک کلمه وارد کنید.")
        return

    if guess == game.word:
        game.phase = "finished"
        participant_ids = [p["id"] for p in game.players]
        streak = bump_win_streak_group(current["id"], participant_ids)
        user_names[current["id"]] = current["name"]
        await stats_save_user(current["id"], current["name"], streak)
        await send_streak_update(context, current["id"], current["name"])
        await update.message.reply_text(f"🎉 آفرین! درست حدس زدی: «{game.word}»")
        await hangman_edit_origin(
            context.bot,
            game,
            hangman_final_text(game, winner_name=current["name"], streak=streak),
            hangman_again_keyboard(),
        )
        return

    game.wrong.append(guess if guess else "؟")

    if len(game.wrong) >= HANGMAN_MAX_WRONG:
        game.phase = "finished"
        participant_ids = [p["id"] for p in game.players]
        bump_win_streak_group(None, participant_ids)
        await update.message.reply_text("❌ غلط بود و جون‌ها هم تموم شد.")
        await hangman_edit_origin(
            context.bot, game, hangman_final_text(game, winner_name=None), hangman_again_keyboard()
        )
        return

    await update.message.reply_text("❌ غلط بود، یه جون کم شد و نوبتت رد شد.")
    hangman_advance_turn(game)
    await hangman_edit_origin(context.bot, game, hangman_status_text(game), hangman_letters_keyboard(game))


# ======================== بلک‌جک ========================

BLACKJACK_MIN_PLAYERS = 2
BLACKJACK_MAX_PLAYERS = 6

blackjack_games: dict[str, 'BlackjackGame'] = {}

SUITS_BJ = ["♠", "♥", "♦", "♣"]
RANKS_BJ = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
CARD_VALUES_BJ = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "J": 10, "Q": 10, "K": 10, "A": 11
}


@dataclass
class BlackjackPlayer:
    id: int
    name: str
    cards: list = field(default_factory=list)
    bust: bool = False
    finished: bool = False


@dataclass
class BlackjackGame:
    key: str
    started_by: int
    players: list = field(default_factory=list)
    deck: list = field(default_factory=list)
    phase: str = "lobby"
    turn_index: int = 0
    dealer_cards: list = field(default_factory=list)
    dealer_finished: bool = False
    message_id: Optional[int] = None


def blackjack_build_deck() -> list:
    return [{"rank": r, "suit": s} for s in SUITS_BJ for r in RANKS_BJ]


def blackjack_card_label(card: dict) -> str:
    return f"{card['rank']}{card['suit']}"


def blackjack_hand_value(cards: list) -> int:
    total = 0
    aces = 0
    for card in cards:
        if card["rank"] == "A":
            aces += 1
            total += 11
        else:
            total += CARD_VALUES_BJ[card["rank"]]
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def blackjack_hand_display(cards: list) -> str:
    return " ".join(blackjack_card_label(c) for c in cards)


def blackjack_lobby_text(game: BlackjackGame) -> str:
    names = "، ".join(p.name for p in game.players)
    return (
        f"🃏 بازی ۲۱ با پاسور (بلک‌جک)\n"
        f"(حداقل {BLACKJACK_MIN_PLAYERS}، حداکثر {BLACKJACK_MAX_PLAYERS} نفر)\n\n"
        f"نفرات فعلی ({len(game.players)} نفر): {names}\n\n"
        f"فقط {game.players[0].name if game.players else ''} (سازنده) می‌تونه شروع کنه 👇"
        + THANK_YOU
    )


def blackjack_lobby_keyboard(game: BlackjackGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن ({len(game.players)}/{BLACKJACK_MAX_PLAYERS})",
                              callback_data="bj_join")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="bj_start")],
        [cancel_join_button()],
    ])


def blackjack_inline_result(starter_name: str) -> InlineQueryResultArticle:
    dummy = BlackjackGame(key="", started_by=0)
    dummy.players = [BlackjackPlayer(id=0, name=starter_name)]
    return InlineQueryResultArticle(
        id=f"blackjack-{uuid.uuid4()}",
        title="🃏 ۲۱ با پاسور",
        description=f"{BLACKJACK_MIN_PLAYERS} تا {BLACKJACK_MAX_PLAYERS} نفر — بلک‌جک کلاسیک",
        input_message_content=InputTextMessageContent(blackjack_lobby_text(dummy)),
        reply_markup=blackjack_lobby_keyboard(dummy),
    )


def blackjack_game_status(game: BlackjackGame) -> str:
    lines = ["🃏 بازی ۲۱ (بلک‌جک)\n"]
    
    all_finished = all(p.finished or p.bust for p in game.players)
    
    for i, p in enumerate(game.players):
        status = "✅ ایستاده" if p.finished else ("💥 بست" if p.bust else "🔄 در حال بازی")
        if all_finished:
            if p.bust:
                score_display = "بست!"
            else:
                score_display = str(blackjack_hand_value(p.cards))
        else:
            if p.bust:
                score_display = "بست!"
            else:
                score_display = "??"
        lines.append(f"{i+1}. {p.name} — جمع: {score_display} | {status}")
    
    if game.dealer_finished:
        dealer_score = blackjack_hand_value(game.dealer_cards)
        dealer_display = blackjack_hand_display(game.dealer_cards)
        lines.append(f"\n🎩 دیلر: {dealer_display} (جمع: {dealer_score})")
    else:
        if game.dealer_cards:
            lines.append(f"\n🎩 دیلر: {blackjack_card_label(game.dealer_cards[0])} + ?")
    
    if game.phase == "playing" and game.turn_index < len(game.players):
        current = game.players[game.turn_index]
        lines.append(f"\n👉 نوبت: {current.name}")
    return "\n".join(lines)


def blackjack_play_keyboard(game: BlackjackGame) -> Optional[InlineKeyboardMarkup]:
    if game.turn_index >= len(game.players) or game.phase != "playing":
        return None
    current = game.players[game.turn_index]
    if current.finished or current.bust:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 کارت بگیر", callback_data="bj_hit")],
        [InlineKeyboardButton("✋ بایست", callback_data="bj_stand")],
        [InlineKeyboardButton("👀 کارتام رو ببین", callback_data="bj_view")],
    ])


async def blackjack_edit_origin(bot, game: BlackjackGame, text: str, reply_markup=None):
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(game.key), message_id=game.message_id,
                                        reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=game.key, reply_markup=reply_markup)
    except BadRequest:
        pass


async def blackjack_deal_initial_cards(game: BlackjackGame, context: ContextTypes.DEFAULT_TYPE):
    game.deck = blackjack_build_deck()
    random.shuffle(game.deck)
    for p in game.players:
        p.cards = [game.deck.pop(), game.deck.pop()]
        p.bust = False
        p.finished = False
    game.dealer_cards = [game.deck.pop(), game.deck.pop()]
    game.dealer_finished = False
    game.phase = "playing"
    game.turn_index = 0
    text = blackjack_game_status(game) + THANK_YOU
    markup = blackjack_play_keyboard(game)
    await blackjack_edit_origin(context.bot, game, text, markup)


async def blackjack_next_turn(game: BlackjackGame, context: ContextTypes.DEFAULT_TYPE):
    next_idx = game.turn_index + 1
    while next_idx < len(game.players):
        p = game.players[next_idx]
        if not p.finished and not p.bust:
            game.turn_index = next_idx
            text = blackjack_game_status(game)
            markup = blackjack_play_keyboard(game)
            await blackjack_edit_origin(context.bot, game, text, markup)
            return
        next_idx += 1
    await blackjack_dealer_turn(game, context)


async def blackjack_dealer_turn(game: BlackjackGame, context: ContextTypes.DEFAULT_TYPE):
    game.dealer_finished = True
    while blackjack_hand_value(game.dealer_cards) < 17:
        game.dealer_cards.append(game.deck.pop())
    await blackjack_finish_game(game, context)


async def blackjack_finish_game(game: BlackjackGame, context: ContextTypes.DEFAULT_TYPE):
    dealer_score = blackjack_hand_value(game.dealer_cards)
    dealer_bust = dealer_score > 21

    player_lines = []
    best_player = None
    best_score = -1

    for p in game.players:
        if p.bust:
            player_lines.append(f"جمع کارت های {p.name} = بست!")
        else:
            sc = blackjack_hand_value(p.cards)
            player_lines.append(f"جمع کارت های {p.name} = {sc}")
            if sc > best_score:
                best_score = sc
                best_player = p

    winner_name = None
    if dealer_bust:
        if best_player:
            winner_name = best_player.name
    else:
        if best_player and best_score > dealer_score:
            winner_name = best_player.name
        elif best_player and best_score == dealer_score:
            winner_name = None
        else:
            winner_name = None

    final_lines = player_lines
    final_lines.append("")
    if winner_name:
        final_lines.append(f"🏆 برنده: {winner_name} 🏆")
    else:
        if dealer_bust:
            final_lines.append("همه بازیکنان بست شدند! 🤷")
        else:
            if best_player and best_score == dealer_score:
                final_lines.append("🤝 مساوی با دیلر!")
            else:
                final_lines.append("🎩 دیلر برنده شد!")

    if winner_name:
        winner_id = next((p.id for p in game.players if p.name == winner_name), None)
        if winner_id:
            participant_ids = [p.id for p in game.players]
            bump_win_streak_group(winner_id, participant_ids)
            user_names[winner_id] = winner_name
            await stats_save_user(winner_id, winner_name, win_streaks.get(winner_id, 0))
            await send_streak_update(context, winner_id, winner_name)

    final_text = "\n".join(final_lines) + THANK_YOU
    await blackjack_edit_origin(context.bot, game, final_text, None)
    del blackjack_games[game.key]


async def blackjack_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE):
    game = blackjack_games.get(key)
    if not game:
        await query.answer("بازی پیدا نشد یا تمام شده.", show_alert=True)
        return

    if data == "bj_join":
        if game.phase != "lobby":
            await query.answer("بازی شروع شده!", show_alert=True)
            return
        if any(p.id == user.id for p in game.players):
            await query.answer("قبلاً پیوستی!", show_alert=True)
            return
        if len(game.players) >= BLACKJACK_MAX_PLAYERS:
            await query.answer("لابی پره!", show_alert=True)
            return
        game.players.append(BlackjackPlayer(id=user.id, name=user.first_name))
        await query.edit_message_text(
            blackjack_lobby_text(game),
            reply_markup=blackjack_lobby_keyboard(game)
        )
        await query.answer("پیوستی! ✅")
        return

    if data == "bj_start":
        if game.phase != "lobby":
            await query.answer()
            return
        if user.id != game.started_by:
            await query.answer(f"فقط {game.players[0].name} می‌تواند شروع کند.", show_alert=True)
            return
        if len(game.players) < BLACKJACK_MIN_PLAYERS:
            await query.answer(f"حداقل {BLACKJACK_MIN_PLAYERS} نفر لازم است.", show_alert=True)
            return
        await query.answer("بازی شروع شد! 🃏")
        await blackjack_deal_initial_cards(game, context)
        return

    if data == "bj_view":
        player = next((p for p in game.players if p.id == user.id), None)
        if not player:
            await query.answer("تو در این بازی نیستی!", show_alert=True)
            return
        cards = blackjack_hand_display(player.cards)
        score = blackjack_hand_value(player.cards)
        await query.answer(
            f"🃏 کارت‌های شما: {cards}\nجمع: {score}",
            show_alert=True
        )
        return

    if data == "bj_hit":
        if game.phase != "playing":
            await query.answer("بازی تمام شده!", show_alert=True)
            return
        if game.turn_index >= len(game.players):
            await query.answer("نوبت دیلر است!", show_alert=True)
            return
        current = game.players[game.turn_index]
        if user.id != current.id:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return
        if current.finished or current.bust:
            await query.answer("نوبتت تمام شده!", show_alert=True)
            return
        new_card = game.deck.pop()
        current.cards.append(new_card)
        score = blackjack_hand_value(current.cards)
        if score > 21:
            current.bust = True
            await query.answer(f"💥 بست شدی! امتیاز نهایی: {score}", show_alert=True)
        else:
            await query.answer(f"🃏 کارت گرفتی! امتیاز فعلی: {score}", show_alert=True)
        text = blackjack_game_status(game)
        if current.bust:
            await blackjack_next_turn(game, context)
        else:
            markup = blackjack_play_keyboard(game)
            await blackjack_edit_origin(context.bot, game, text, markup)
        return

    if data == "bj_stand":
        if game.phase != "playing":
            await query.answer("بازی تمام شده!", show_alert=True)
            return
        if game.turn_index >= len(game.players):
            await query.answer("نوبت دیلر است!", show_alert=True)
            return
        current = game.players[game.turn_index]
        if user.id != current.id:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return
        if current.finished or current.bust:
            await query.answer("نوبتت تمام شده!", show_alert=True)
            return
        current.finished = True
        score = blackjack_hand_value(current.cards)
        await query.answer(f"✋ ایستادی! امتیاز نهایی: {score}", show_alert=True)
        await blackjack_next_turn(game, context)
        return


# ======================== بازی کشتی ========================

BATTLESHIP_MIN_PLAYERS = 2
BATTLESHIP_MAX_PLAYERS = 2
BATTLESHIP_HP = 100
BATTLESHIP_SHIP_COSTS = [30, 60, 90]
BATTLESHIP_SHIP_DAMAGES = [30, 60, 90]

BATTLESHIP_QUESTIONS = [
    {"q": "پایتخت فرانسه کجاست؟", "options": ["پاریس", "لندن", "رم", "برلین"], "correct": 0, "type": "normal"},
    {"q": "چند تا انگشت در یک دست داریم؟", "options": ["پنج", "چهار", "شش", "سه"], "correct": 0, "type": "normal"},
    {"q": "خورشید از کدام جهت طلوع می‌کند؟", "options": ["شرق", "غرب", "شمال", "جنوب"], "correct": 0, "type": "normal"},
    {"q": "یخ از انجماد چه چیزی به‌وجود می‌آید؟", "options": ["آب", "روغن", "شیر", "سرکه"], "correct": 0, "type": "normal"},
    {"q": "زنبورعسل چه چیزی تولید می‌کند؟", "options": ["عسل", "شیر", "پشم", "ابریشم"], "correct": 0, "type": "normal"},
    {"q": "ماه دور کدام سیاره می‌چرخد؟", "options": ["زمین", "خورشید", "مریخ", "زهره"], "correct": 0, "type": "normal"},
    {"q": "کدام فصل بعد از تابستان می‌آید؟", "options": ["پاییز", "زمستان", "بهار", "تابستان"], "correct": 0, "type": "normal"},
    {"q": "اسب چند تا پا دارد؟", "options": ["چهار", "دو", "سه", "شش"], "correct": 0, "type": "normal"},
    {"q": "پایتخت انگلستان کجاست؟", "options": ["لندن", "پاریس", "برلین", "رم"], "correct": 0, "type": "normal"},
    {"q": "کدام رنگ‌ها با هم رنگ سبز می‌سازند؟", "options": ["آبی و زرد", "قرمز و آبی", "زرد و قرمز", "سفید و سیاه"], "correct": 0, "type": "normal"},
    {"q": "بلندترین قله جهان کدام است؟", "options": ["اورست", "کی۲", "کانگچنجونگا", "لوتسه"], "correct": 0, "type": "hard"},
    {"q": "کدام کشور بیشترین قهرمانی جام جهانی فوتبال را دارد؟", "options": ["برزیل", "آلمان", "ایتالیا", "آرژانتین"], "correct": 0, "type": "hard"},
    {"q": "نماد شیمیایی سدیم چیست؟", "options": ["Na", "S", "Sd", "So"], "correct": 0, "type": "hard"},
    {"q": "سریع‌ترین حیوان خشکی‌زی کدام است؟", "options": ["یوزپلنگ", "شیر", "اسب", "گورخر"], "correct": 0, "type": "hard"},
    {"q": "کوچک‌ترین کشور جهان از نظر مساحت کدام است؟", "options": ["واتیکان", "موناکو", "سان مارینو", "لیختن‌اشتاین"], "correct": 0, "type": "hard"},
    {"q": "اولین انسانی که به فضا رفت که بود؟", "options": ["یوری گاگارین", "نیل آرمسترانگ", "بوز آلدرین", "والنتینا ترشکووا"], "correct": 0, "type": "hard"},
    {"q": "نویسنده رمان «جنگ و صلح» کیست؟", "options": ["لئو تولستوی", "داستایفسکی", "چخوف", "پوشکین"], "correct": 0, "type": "hard"},
    {"q": "کدام اقیانوس بین آمریکا و اروپا قرار دارد؟", "options": ["اطلس", "آرام", "هند", "منجمد شمالی"], "correct": 0, "type": "hard"},
    {"q": "واحد پول ژاپن چیست؟", "options": ["ین", "وون", "یوان", "دلار"], "correct": 0, "type": "hard"},
    {"q": "مخترع تلفن چه کسی بود؟", "options": ["الکساندر گراهام بل", "توماس ادیسون", "نیکولا تسلا", "مارکنی"], "correct": 0, "type": "hard"},
    {"q": "بزرگ‌ترین صحرای گرم جهان کدام است؟", "options": ["سحارا", "گبی", "کالاهاری", "صحرای عربستان"], "correct": 0, "type": "hard"},
    {"q": "کدام سیاره به «سیاره سرخ» معروف است؟", "options": ["مریخ", "زهره", "مشتری", "زحل"], "correct": 0, "type": "hard"},
    {"q": "تعداد استخوان‌های بدن انسان بالغ چند عدد است؟", "options": ["۲۰۶", "۱۹۰", "۲۱۵", "۲۲۰"], "correct": 0, "type": "hard"},
    {"q": "دیوار بزرگ در کدام کشور قرار دارد؟", "options": ["چین", "ژاپن", "مغولستان", "کره"], "correct": 0, "type": "hard"},
    {"q": "بازی‌های المپیک باستان اولین بار در کدام کشور برگزار شد؟", "options": ["یونان", "روم", "مصر", "ایران"], "correct": 0, "type": "hard"},
    {"q": "سریع‌ترین پرنده جهان کدام است؟", "options": ["شاهین", "عقاب", "کرکس", "باز"], "correct": 0, "type": "hard"},
    {"q": "بزرگ‌ترین جانور روی زمین کدام است؟", "options": ["نهنگ آبی", "فیل آفریقایی", "زرافه", "کرگدن"], "correct": 0, "type": "hard"},
    {"q": "کدام کشور بزرگ‌ترین تولیدکننده قهوه جهان است؟", "options": ["برزیل", "کلمبیا", "ویتنام", "اتیوپی"], "correct": 0, "type": "hard"},
    {"q": "رودخانه آمازون در کدام قاره جریان دارد؟", "options": ["آمریکای جنوبی", "آفریقا", "آسیا", "اروپا"], "correct": 0, "type": "hard"},
    {"q": "مخترع لامپ برق چه کسی بود؟", "options": ["توماس ادیسون", "نیکولا تسلا", "بنجامین فرانکلین", "گراهام بل"], "correct": 0, "type": "hard"},
    {"q": "بزرگ‌ترین هرم مصر کدام است؟", "options": ["هرم خوفو (جیزه)", "هرم زوسر", "هرم خفرع", "هرم منقوره"], "correct": 0, "type": "hard"},
    {"q": "اولین المپیک مدرن در کدام شهر برگزار شد؟", "options": ["آتن", "پاریس", "لندن", "رم"], "correct": 0, "type": "hard"},
    {"q": "زبان رسمی برزیل چیست؟", "options": ["پرتغالی", "اسپانیایی", "انگلیسی", "فرانسوی"], "correct": 0, "type": "hard"},
    {"q": "کدام سیاره حلقه‌های معروفی دارد؟", "options": ["زحل", "مشتری", "اورانوس", "نپتون"], "correct": 0, "type": "hard"},
    {"q": "اختراع چاپ متحرک به چه کسی نسبت داده می‌شود؟", "options": ["یوهان گوتنبرگ", "لئوناردو داوینچی", "گالیله", "نیوتن"], "correct": 0, "type": "hard"},
    {"q": "کدام پستاندار توانایی پرواز واقعی دارد؟", "options": ["خفاش", "سنجاب پرنده", "موش", "عقاب"], "correct": 0, "type": "hard"},
    {"q": "بلندترین رودخانه اروپا کدام است؟", "options": ["ولگا", "دانوب", "راین", "سن"], "correct": 0, "type": "hard"},
    {"q": "کدام کشور میزبان جام جهانی فوتبال ۲۰۲۲ بود؟", "options": ["قطر", "روسیه", "برزیل", "امارات"], "correct": 0, "type": "hard"},
    {"q": "تعداد قاره‌های جهان چند عدد است؟", "options": ["۷", "۵", "۶", "۸"], "correct": 0, "type": "hard"},
    {"q": "کدام فلز در دمای اتاق به‌صورت مایع است؟", "options": ["جیوه", "سرب", "روی", "قلع"], "correct": 0, "type": "hard"},
    {"q": "کاشف قاره آمریکا (از دید تاریخ اروپایی) چه کسی بود؟", "options": ["کریستف کلمب", "ماژلان", "وسپوچی", "کاپیتان کوک"], "correct": 0, "type": "hard"},
    {"q": "بزرگ‌ترین دریاچه جهان کدام است؟", "options": ["دریای خزر", "دریاچه سوپریور", "دریاچه ویکتوریا", "دریاچه بایکال"], "correct": 0, "type": "hard"},
    {"q": "کدام کشور بیشترین تعداد آتشفشان فعال جهان را دارد؟", "options": ["اندونزی", "ژاپن", "ایسلند", "آمریکا"], "correct": 0, "type": "hard"},
    {"q": "نویسنده مجموعه کتاب‌های «هری پاتر» کیست؟", "options": ["جی.کی. رولینگ", "تالکین", "سی.اس. لوئیس", "راجر مور"], "correct": 0, "type": "hard"},
    {"q": "سریع‌ترین قطار مسافربری تجاری جهان در کدام کشور فعال است؟", "options": ["چین", "ژاپن", "فرانسه", "آلمان"], "correct": 0, "type": "hard"},
    {"q": "به کدام ورزش لقب «ورزش پادشاهان» داده‌اند؟", "options": ["اسب‌سواری", "تنیس", "گلف", "شمشیربازی"], "correct": 0, "type": "hard"},
    {"q": "طولانی‌ترین دیوار ساخته‌شده توسط انسان کدام است؟", "options": ["دیوار بزرگ چین", "دیوار برلین", "دیوار هادریان", "دیوار حائل"], "correct": 0, "type": "hard"},
    {"q": "نماد شیمیایی پتاسیم چیست؟", "options": ["K", "P", "Pt", "Po"], "correct": 0, "type": "hard"},
    {"q": "پایتخت استرالیا کدام شهر است؟", "options": ["کانبرا", "سیدنی", "ملبورن", "پرت"], "correct": 0, "type": "hard"},
    {"q": "وب جهان‌گستر (www) توسط چه کسی اختراع شد؟", "options": ["تیم برنرز-لی", "بیل گیتس", "استیو جابز", "مارک زاکربرگ"], "correct": 0, "type": "hard"},
]


@dataclass
class BattleshipGame:
    key: str
    starter_id: int
    player1_id: int
    player1_name: str
    player2_id: Optional[int] = None
    player2_name: Optional[str] = None
    phase: str = "lobby"
    hp: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)
    current_question: Optional[dict] = None
    question_asked: bool = False
    answered_users: set = field(default_factory=set)
    last_attack_time: dict = field(default_factory=dict)
    message_id: Optional[int] = None
    turn_id: Optional[int] = None
    db_key: Optional[str] = None


battleship_games: dict[str, BattleshipGame] = {}
BATTLESHIP_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battleship_games.db")


def battleship_db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(BATTLESHIP_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS battleship_games (
            game_key TEXT PRIMARY KEY,
            state_json TEXT NOT NULL
        )
        """
    )
    return conn


def battleship_serialize(game: BattleshipGame) -> str:
    return json.dumps(dataclasses.asdict(game))


def battleship_deserialize(state_json: str) -> BattleshipGame:
    data = json.loads(state_json)
    for key in ("hp", "score", "last_attack_time"):
        if data.get(key):
            data[key] = {int(k): v for k, v in data[key].items()}
    if data.get("answered_users"):
        data["answered_users"] = set(data["answered_users"])
    return BattleshipGame(**data)


def _battleship_save_sync(game: BattleshipGame) -> None:
    try:
        with battleship_db_connect() as conn:
            conn.execute(
                "INSERT INTO battleship_games (game_key, state_json) VALUES (?, ?) "
                "ON CONFLICT(game_key) DO UPDATE SET state_json = excluded.state_json",
                (game.key, battleship_serialize(game)),
            )
    except Exception:
        logger.exception("خطا در ذخیره وضعیت بازی کشتی در SQLite")


async def battleship_save(game: BattleshipGame) -> None:
    await asyncio.to_thread(_battleship_save_sync, game)


def _battleship_delete_saved_sync(key: str) -> None:
    try:
        with battleship_db_connect() as conn:
            conn.execute("DELETE FROM battleship_games WHERE game_key = ?", (key,))
    except Exception:
        logger.exception("خطا در حذف وضعیت بازی کشتی از SQLite")


async def battleship_delete_saved(key: str) -> None:
    await asyncio.to_thread(_battleship_delete_saved_sync, key)


def battleship_load_all() -> dict:
    games: dict[str, BattleshipGame] = {}
    try:
        with battleship_db_connect() as conn:
            rows = conn.execute("SELECT game_key, state_json FROM battleship_games").fetchall()
        for game_key, state_json in rows:
            try:
                games[game_key] = battleship_deserialize(state_json)
            except Exception:
                logger.exception(f"خطا در بازسازی وضعیت بازی کشتی برای {game_key}")
    except Exception:
        logger.exception("خطا در خوندن وضعیت‌های بازی کشتی از SQLite")
    return games


async def battleship_restore_games(app: Application) -> None:
    restored = battleship_load_all()
    if not restored:
        return
    battleship_games.update(restored)
    logger.info(f"{len(restored)} بازی کشتی از SQLite بازیابی شد.")


def battleship_lobby_text(game: BattleshipGame) -> str:
    players = [game.player1_name]
    if game.player2_name:
        players.append(game.player2_name)
    names = "، ".join(players)
    return (
        f"🤼 کشتی (PvP)\n"
        f"هر بازیکن {BATTLESHIP_HP} جان (HP) دارد.\n"
        f"با پاسخ به سوالات امتیاز جمع کنید و هر وقت امتیاز کافی داشتید با فن‌ها به حریف حمله کنید.\n\n"
        f"نفرات فعلی ({len(players)}/{BATTLESHIP_MAX_PLAYERS}): {names}\n\n"
        f"فقط {game.player1_name} (سازنده) می‌تونه شروع کنه 👇"
        + THANK_YOU
    )


def battleship_lobby_keyboard(game: BattleshipGame) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🙋 پیوستن ({len([p for p in [game.player1_id, game.player2_id] if p])}/{BATTLESHIP_MAX_PLAYERS})",
                              callback_data="bship_join")],
        [InlineKeyboardButton("🚀 شروع نبرد", callback_data="bship_start")],
        [cancel_join_button()],
    ])


def battleship_inline_result(starter_name: str) -> InlineQueryResultArticle:
    dummy = BattleshipGame(key="", starter_id=0, player1_id=0, player1_name=starter_name)
    return InlineQueryResultArticle(
        id=f"bship-{uuid.uuid4()}",
        title="🤼 کشتی",
        description=f"PvP دو نفره — با پاسخ به سوالات به حریف حمله کن!",
        input_message_content=InputTextMessageContent(battleship_lobby_text(dummy)),
        reply_markup=battleship_lobby_keyboard(dummy),
    )


def battleship_ship_buttons() -> list:
    buttons = []
    for i, cost in enumerate(BATTLESHIP_SHIP_COSTS):
        damage = BATTLESHIP_SHIP_DAMAGES[i]
        label = f"🥋 فن {i+1} (هزینه {cost} - آسیب {damage})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"bship_attack_{i}")])
    return buttons


def battleship_full_keyboard(game: BattleshipGame) -> InlineKeyboardMarkup:
    buttons = []
    if game.current_question and game.question_asked:
        for i, opt in enumerate(game.current_question["options"]):
            buttons.append([InlineKeyboardButton(opt, callback_data=f"bship_ans_{i}")])
    buttons.extend(battleship_ship_buttons())
    return InlineKeyboardMarkup(buttons)


def battleship_status_text(game: BattleshipGame) -> str:
    if game.phase != "playing":
        return "بازی در حال پایان است."
    lines = [
        f"🤼 کشتی — وضعیت بازی",
        f"❤️ {game.player1_name}: {game.hp.get(game.player1_id, 0)} HP  |  ⭐ امتیاز: {game.score.get(game.player1_id, 0)}",
        f"❤️ {game.player2_name}: {game.hp.get(game.player2_id, 0)} HP  |  ⭐ امتیاز: {game.score.get(game.player2_id, 0)}",
    ]
    if game.current_question and game.question_asked:
        q = game.current_question
        lines.append("")
        lines.append(f"❓ {q['q']}")
        for i, opt in enumerate(q["options"]):
            lines.append(f"{i+1}. {opt}")
        lines.append("")
        lines.append("با انتخاب گزینه‌ی درست امتیاز بگیرید، یا هر وقت امتیاز کافی داشتید با یکی از فن‌ها حمله کنید.")
    else:
        lines.append("")
        lines.append("⏳ در حال آماده‌سازی سوال بعدی...")
    return "\n".join(lines)


async def battleship_edit_origin(bot, game: BattleshipGame, text: str, reply_markup=None) -> None:
    try:
        if game.message_id is not None:
            await bot.edit_message_text(text, chat_id=int(game.key), message_id=game.message_id,
                                        reply_markup=reply_markup)
        else:
            await bot.edit_message_text(text, inline_message_id=game.key, reply_markup=reply_markup)
    except BadRequest:
        pass


async def battleship_refresh_display(game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = battleship_status_text(game)
    markup = battleship_full_keyboard(game) if game.phase == "playing" else None
    await battleship_edit_origin(context.bot, game, text, markup)


async def battleship_ask_question(game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = random.choice(BATTLESHIP_QUESTIONS)
    game.current_question = q
    game.question_asked = True
    game.answered_users = set()
    text = battleship_status_text(game)
    markup = battleship_full_keyboard(game)
    await battleship_edit_origin(context.bot, game, text, markup)


async def battleship_start_game(game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE) -> None:
    game.phase = "playing"
    game.hp[game.player1_id] = BATTLESHIP_HP
    game.hp[game.player2_id] = BATTLESHIP_HP
    game.score[game.player1_id] = 0
    game.score[game.player2_id] = 0
    game.last_attack_time = {}
    await battleship_ask_question(game, context)


async def battleship_handle_answer(query, user, game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE, idx: int) -> None:
    if game.phase != "playing" or not game.question_asked:
        await query.answer("در حال حاضر سوالی مطرح نیست.", show_alert=True)
        return
    if user.id not in (game.player1_id, game.player2_id):
        await query.answer("شما در این بازی نیستید!", show_alert=True)
        return
    if user.id in game.answered_users:
        await query.answer("شما قبلاً به این سوال پاسخ داده‌اید.", show_alert=True)
        return

    q = game.current_question
    if idx == q["correct"]:
        points = 10 if q["type"] == "normal" else 30
        game.score[user.id] = game.score.get(user.id, 0) + points
        await query.answer(f"✅ پاسخ درست! {points} امتیاز گرفتید.", show_alert=True)
    else:
        await query.answer("❌ پاسخ اشتباه بود.", show_alert=True)

    game.answered_users.add(user.id)

    if len(game.answered_users) >= 2:
        if await battleship_check_game_over(game, context):
            return
        await battleship_ask_question(game, context)
    else:
        await battleship_refresh_display(game, context)


async def battleship_handle_attack(query, user, game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE, ship_index: int) -> None:
    if game.phase != "playing":
        await query.answer("بازی تمام شده است.", show_alert=True)
        return
    if user.id not in (game.player1_id, game.player2_id):
        await query.answer("شما در این بازی نیستید!", show_alert=True)
        return

    cost = BATTLESHIP_SHIP_COSTS[ship_index]
    damage = BATTLESHIP_SHIP_DAMAGES[ship_index]
    if game.score.get(user.id, 0) < cost:
        await query.answer(f"امتیاز شما کافی نیست! نیاز به {cost} امتیاز دارید.", show_alert=True)
        return

    game.score[user.id] -= cost

    opponent_id = game.player2_id if user.id == game.player1_id else game.player1_id
    opponent_name = game.player2_name if user.id == game.player1_id else game.player1_name
    game.hp[opponent_id] = max(0, game.hp.get(opponent_id, 0) - damage)

    attacker_name = user.first_name or "کاربر"
    attack_msg = f"⚔️ به {opponent_name} حمله کردید! (-{damage} HP)"

    if await battleship_check_game_over(game, context):
        await query.answer("نبرد تمام شد! برنده مشخص شد.", show_alert=True)
        return

    await battleship_refresh_display(game, context)
    await query.answer(attack_msg, show_alert=True)


async def battleship_check_game_over(game: BattleshipGame, context: ContextTypes.DEFAULT_TYPE) -> bool:
    hp1 = game.hp.get(game.player1_id, 0)
    hp2 = game.hp.get(game.player2_id, 0)
    if hp1 <= 0 or hp2 <= 0:
        game.phase = "finished"
        winner_id = game.player1_id if hp2 <= 0 else game.player2_id
        winner_name = game.player1_name if hp2 <= 0 else game.player2_name
        loser_id = game.player2_id if hp2 <= 0 else game.player1_id
        loser_name = game.player2_name if hp2 <= 0 else game.player1_name

        streak = bump_win_streak(winner_id, loser_id)
        user_names[winner_id] = winner_name
        user_names[loser_id] = loser_name
        await stats_save_user(winner_id, winner_name, streak)
        await stats_save_user(loser_id, loser_name, 0)
        await send_streak_update(context, winner_id, winner_name)

        text = (
            f"🏁 کشتی به پایان رسید!\n"
            f"🏆 برنده: {winner_name} 🏆\n"
            f"💔 بازنده: {loser_name}\n"
            + win_streak_line(winner_name, streak)
            + THANK_YOU
        )
        await battleship_edit_origin(context.bot, game, text, None)
        battleship_games.pop(game.key, None)
        await battleship_delete_saved(game.key)
        return True
    return False


async def battleship_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    game = battleship_games.get(key)
    if not game:
        await query.answer("بازی کشتی پیدا نشد یا تمام شده.", show_alert=True)
        return

    if data == "bship_join":
        if game.phase != "lobby":
            await query.answer("بازی شروع شده، نمی‌توانید بپیوندید.", show_alert=True)
            return
        if user.id == game.player1_id:
            await query.answer("شما سازنده بازی هستید!", show_alert=True)
            return
        if game.player2_id is not None:
            await query.answer("بازی پر شده است!", show_alert=True)
            return
        game.player2_id = user.id
        game.player2_name = user.first_name
        await query.edit_message_text(
            battleship_lobby_text(game),
            reply_markup=battleship_lobby_keyboard(game)
        )
        await query.answer("به نبرد پیوستید! ✅")
        return

    if data == "bship_start":
        if game.phase != "lobby":
            await query.answer()
            return
        if user.id != game.starter_id:
            await query.answer(f"فقط {game.player1_name} می‌تواند بازی را شروع کند.", show_alert=True)
            return
        if game.player2_id is None:
            await query.answer("حداقل ۲ نفر نیاز است.", show_alert=True)
            return
        await query.answer("نبرد شروع شد! 🤼")
        await battleship_start_game(game, context)
        return

    if data.startswith("bship_ans_"):
        idx = int(data.split("_")[2])
        await battleship_handle_answer(query, user, game, context, idx)
        return

    if data.startswith("bship_attack_"):
        ship_idx = int(data.split("_")[2])
        await battleship_handle_attack(query, user, game, context, ship_idx)
        return


# ======================== دستورات گروهی ========================

async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE, game_type: str):
    chat_id = update.effective_chat.id
    user = update.effective_user
    key = str(chat_id)

    if key in games:
        await update.message.reply_text("⚠️ در حال حاضر یک بازی در این چت در جریان است. لطفاً آن را به پایان برسانید یا از دکمه‌های موجود استفاده کنید.")
        return

    games[key] = Game(game_type=game_type, player1_id=user.id, player1_name=user.first_name)
    await update.message.reply_text(
        start_message_text(game_type, user.first_name),
        reply_markup=join_keyboard(game_type),
    )


async def rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_game_command(update, context, "rps")


async def golpoch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_game_command(update, context, "golpoch")


async def xo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_game_command(update, context, "xo")


async def morris_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_game_command(update, context, "morris")


async def start_hokm_command(update: Update, context: ContextTypes.DEFAULT_TYPE, target_rounds: int):
    chat_id = update.effective_chat.id
    user = update.effective_user
    key = str(chat_id)

    if key in hokm_games:
        await update.message.reply_text("⚠️ در حال حاضر یک بازی حکم در این چت در جریان است. لطفاً آن را به پایان برسانید.")
        return

    rounds_needed = target_rounds // 2 + 1
    hokm_games[key] = HokmGame(
        target_rounds=target_rounds,
        rounds_needed=rounds_needed,
        players=[{"id": user.id, "name": user.first_name}],
    )
    sent = await update.message.reply_text(
        hokm_join_status_text(hokm_games[key]),
        reply_markup=hokm_join_keyboard(),
    )
    hokm_games[key].message_id = sent.message_id


async def hokm1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_hokm_command(update, context, 1)


async def hokm3_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_hokm_command(update, context, 3)


async def hokm5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_hokm_command(update, context, 5)


# ======================== هندلر دکمه‌های انصراف (مشترک) ========================

async def cancel_join_handler(query, user, key: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # بازی‌های دو نفره
        if key in games:
            game = games[key]
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return

            if user.id == game.player1_id:
                del games[key]
                await query.edit_message_text("بازی لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.player2_id:
                game.player2_id = None
                game.player2_name = None
                await query.edit_message_text(
                    start_message_text(game.game_type, game.player1_name),
                    reply_markup=join_keyboard(game.game_type),
                )
                await query.answer("شما از بازی خارج شدید.")
                return
            await query.answer("شما در این بازی نیستید.", show_alert=True)
            return

        # حکم
        if key in hokm_games:
            game = hokm_games[key]
            if game.phase != "joining":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p["id"] == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این بازی نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del hokm_games[key]
                await query.edit_message_text("بازی حکم لغو شد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.players[0]["id"]:
                del hokm_games[key]
                await query.edit_message_text("بازی حکم لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            await query.edit_message_text(
                hokm_join_status_text(game),
                reply_markup=hokm_join_keyboard(),
            )
            await query.answer("شما از بازی خارج شدید.")
            return

        # مافیا
        if key in mafia_games:
            game = mafia_games[key]
            if game.phase != "joining":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p.id == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این بازی نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del mafia_games[key]
                await mafia_delete_saved(key)
                await query.edit_message_text("بازی مافیا لغو شد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.started_by:
                del mafia_games[key]
                await mafia_delete_saved(key)
                await query.edit_message_text("بازی مافیا لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            await mafia_save(game)
            await query.edit_message_text(
                mafia_lobby_text(game),
                reply_markup=mafia_lobby_keyboard(),
            )
            await query.answer("شما از بازی خارج شدید.")
            return

        # کوییز
        if key in quiz_games:
            game = quiz_games[key]
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p["id"] == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این بازی نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del quiz_games[key]
                await query.edit_message_text("بازی کوییز لغو شد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.starter_id:
                del quiz_games[key]
                await query.edit_message_text("بازی کوییز لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            await query.edit_message_text(
                quiz_lobby_text(game),
                reply_markup=quiz_lobby_keyboard(game),
            )
            await query.answer("شما از بازی خارج شدید.")
            return

        # دار بازی
        if key in hangman_games:
            game = hangman_games[key]
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p["id"] == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این بازی نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del hangman_games[key]
                await query.edit_message_text("بازی دار بازی لغو شد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.starter_id:
                del hangman_games[key]
                await query.edit_message_text("بازی دار بازی لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            await query.edit_message_text(
                hangman_lobby_text(game),
                reply_markup=hangman_lobby_keyboard(game),
            )
            await query.answer("شما از بازی خارج شدید.")
            return

        # تورنمنت
        if key in tournament_games:
            game = tournament_games[key]
            if game.phase != "lobby":
                await query.answer("تورنمنت شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p["id"] == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این تورنمنت نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del tournament_games[key]
                await query.edit_message_text("تورنمنت لغو شد.")
                await query.answer("تورنمنت لغو شد.")
                return
            if user.id == game.started_by:
                del tournament_games[key]
                await query.edit_message_text("تورنمنت لغو شد زیرا سازنده انصراف داد.")
                await query.answer("تورنمنت لغو شد.")
                return
            await query.edit_message_text(
                tournament_lobby_text(game),
                reply_markup=tournament_lobby_keyboard(game),
            )
            await query.answer("شما از تورنمنت خارج شدید.")
            return

        # بلک‌جک
        if key in blackjack_games:
            game = blackjack_games[key]
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            removed = False
            for p in game.players[:]:
                if p.id == user.id:
                    game.players.remove(p)
                    removed = True
                    break
            if not removed:
                await query.answer("شما در این بازی نیستید.", show_alert=True)
                return
            if len(game.players) == 0:
                del blackjack_games[key]
                await query.edit_message_text("بازی بلک‌جک لغو شد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.started_by:
                del blackjack_games[key]
                await query.edit_message_text("بازی بلک‌جک لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            await query.edit_message_text(
                blackjack_lobby_text(game),
                reply_markup=blackjack_lobby_keyboard(game),
            )
            await query.answer("شما از بازی خارج شدید.")
            return

        # کشتی
        if key in battleship_games:
            game = battleship_games[key]
            if game.phase != "lobby":
                await query.answer("بازی شروع شده، امکان انصراف وجود ندارد.", show_alert=True)
                return
            if user.id == game.player1_id:
                del battleship_games[key]
                await battleship_delete_saved(key)
                await query.edit_message_text("بازی کشتی لغو شد زیرا سازنده انصراف داد.")
                await query.answer("بازی لغو شد.")
                return
            if user.id == game.player2_id:
                game.player2_id = None
                game.player2_name = None
                await query.edit_message_text(
                    battleship_lobby_text(game),
                    reply_markup=battleship_lobby_keyboard(game),
                )
                await query.answer("شما از بازی خارج شدید.")
                return
            await query.answer("شما در این بازی نیستید.", show_alert=True)
            return

        await query.answer("بازی مورد نظر پیدا نشد.", show_alert=True)

    except Exception as e:
        logger.error(f"خطا در cancel_join_handler: {e}")
        await query.answer("خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)


# ======================== هندلر دکمه‌های جدید استارت ========================

async def start_buttons_handler(query, user, data: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هندلر دکمه‌های ارسال‌شده در پیام /start"""
    if data == "show_streak":
        await query.answer("در حال دریافت جدول استریک...")
        if not win_streaks:
            await context.bot.send_message(
                chat_id=user.id,
                text="هنوز هیچ استریکی ثبت نشده. اولین برنده شما باشید!"
            )
            return

        sorted_users = sorted(win_streaks.items(), key=lambda x: x[1], reverse=True)
        top_ten = sorted_users[:10]

        lines = ["🏅 **جدول استریک برد (۱۰ نفر برتر)**\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, streak) in enumerate(top_ten, 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            name = user_names.get(uid, str(uid))
            lines.append(f"{medal} {name} — استریک: **{streak}**")

        user_rank = None
        for i, (uid, _) in enumerate(sorted_users, 1):
            if uid == user.id:
                user_rank = i
                break

        if user_rank is not None and user_rank > 10:
            my_name = user_names.get(user.id, user.first_name or str(user.id))
            lines.append(f"\n📍 رتبه‌ی شما: **{user_rank}** (با استریک {win_streaks[user.id]})")

        text = "\n".join(lines)
        try:
            await context.bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
            await query.answer("لیست استریک به پیوی شما ارسال شد 📩")
        except (Forbidden, BadRequest):
            await query.answer("لطفاً ابتدا به ربات پیام /start بدهید تا بتوانم لیست را برایتان بفرستم.", show_alert=True)

    elif data == "help_games":
        help_text = (
            "📖 **راهنمای کامل بازی‌ها**\n\n"
            "✅ **بازی‌های دو نفره:**\n"
            "• /rps — سنگ‌کاغذ‌قیچی (بهترین از ۳ برد)\n"
            "• /golpoch — گل یا پوچ (یکی مخفی می‌کنه، یکی حدس می‌زنه)\n"
            "• /xo — دوز کلاسیک (۳×۳)\n"
            "• /morris — دوز متحرک (هر کس ۳ مهره داره و بعدش جابه‌جا می‌کنه)\n\n"
            "✅ **بازی‌های گروهی:**\n"
            "• /hokm1 — حکم تک‌راند (۴ نفره)\n"
            "• /hokm3 — حکم بهترین از ۳ راند (۴ نفره)\n"
            "• /hokm5 — حکم بهترین از ۵ راند (۴ نفره)\n"
            "• /hangman — دار بازی (۲ تا ۸ نفره، نوبتی حدس کلمه)\n"
            "• /mafia — مافیا (۵ تا ۱۰ نفر، از طریق منوی Inline)\n"
            "• /tournament — تورنمنت سنگ‌کاغذ‌قیچی (از طریق منوی Inline)\n"
            "• /blackjack — بلک‌جک (۲ تا ۶ نفر، از طریق منوی Inline)\n"
            "• /quiz — اولین نفر جواب بده (از طریق منوی Inline)\n"
            "• /wrestling — کشتی (۲ نفره، از طریق منوی Inline)\n\n"
            "🔹 **سایر دستورات:**\n"
            "• /streak — مشاهده جدول استریک برد\n"
            "• /start — نمایش این پیام\n\n"
            "💡 برای استفاده از بازی‌های Inline، در هر چتی @username_robot را تایپ کنید و گزینه‌ی مورد نظر را انتخاب کنید."
        )
        try:
            await context.bot.send_message(chat_id=user.id, text=help_text, parse_mode="Markdown")
            await query.answer("راهنمای کامل به پیوی شما ارسال شد 📚")
        except (Forbidden, BadRequest):
            await query.answer("لطفاً ابتدا به ربات پیام /start بدهید.", show_alert=True)


# ======================== هندلر دکمه‌های اصلی ========================

async def hokm_button_handler(query, user, data: str, key: str, context: ContextTypes.DEFAULT_TYPE):
    if data == "hokm_noop":
        await query.answer()
        return

    game = hokm_games.get(key)
    if not game:
        await query.answer("بازی حکم پیدا نشد یا تموم شده. یه بازی جدید بساز.", show_alert=True)
        return

    if data == "hokm_join":
        if any(p["id"] == user.id for p in game.players):
            await query.answer("قبلاً پیوستی، صبر کن بقیه هم بیان.", show_alert=True)
            return
        if len(game.players) >= 4:
            await query.answer("بازی پره!", show_alert=True)
            return

        game.players.append({"id": user.id, "name": user.first_name})

        if len(game.players) < 4:
            await query.edit_message_text(hokm_join_status_text(game), reply_markup=hokm_join_keyboard())
            await query.answer("وارد بازی شدی! منتظر بقیه بمون.")
            return

        hokm_start_round(game)
        hakem_name = game.players[game.hakem_index]["name"]
        text = (
            f"🃏 بازی حکم کامل شد!\n"
            f"{hokm_team_color_label(game, 0)}\n"
            f"{hokm_team_color_label(game, 1)}\n\n"
            f"کارت‌ها پخش شد ✅ حاکم این راند: {hakem_name}\n"
            f"{hakem_name} اول {HOKM_HAKEM_PREVIEW_COUNT} کارت اول دستشو ببینه، بعد حکم (خال برتر) رو انتخاب کنه 👇\n\n"
            "بقیه هم می‌تونن با همون دکمه دستشونو ببینن (ولی فقط حاکم می‌تونه حکم انتخاب کنه)."
            + THANK_YOU
        )
        await query.edit_message_text(text, reply_markup=hokm_suit_keyboard())
        await query.answer("بازی شروع شد! ✅")
        return

    if data == "hokm_hand":
        hand = game.hands.get(user.id)
        if hand is None:
            await query.answer("تو تو این بازی نیستی یا هنوز کارت پخش نشده.", show_alert=True)
            return
        if not hand:
            await query.answer("کارتی برات نمونده.", show_alert=True)
            return
        limit = None
        if game.phase == "choosing_hokm":
            if user.id == game.players[game.hakem_index]["id"] and game.hakem_reveal_limit is not None:
                limit = game.hakem_reveal_limit
        await query.answer(hokm_hand_text(hand, limit), show_alert=True)
        return

    if data.startswith("hokm_suit_"):
        if game.phase != "choosing_hokm":
            await query.answer("الان وقت انتخاب حکم نیست.", show_alert=True)
            return
        if user.id != game.players[game.hakem_index]["id"]:
            await query.answer("فقط حاکم می‌تونه حکم رو انتخاب کنه!", show_alert=True)
            return

        suit = data.split("_", 2)[2]
        game.trump = suit
        game.phase = "playing"
        game.hakem_reveal_limit = None
        game.turn_index = game.hakem_index
        current_player = game.players[game.turn_index]
        hokm_schedule_turn_timer(context, key, game)
        await query.edit_message_text(
            hokm_status_text(game),
            reply_markup=hokm_play_keyboard(game, current_player["id"]),
        )
        await query.answer(f"حکم انتخاب شد: {suit} ✅")
        return

    if data.startswith("hokm_play_"):
        if game.phase != "playing":
            await query.answer("الان وقتش نیست.", show_alert=True)
            return
        current_player = game.players[game.turn_index]
        if user.id != current_player["id"]:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return

        hand = game.hands[user.id]
        idx = int(data.split("_", 2)[2])
        if idx >= len(hand):
            await query.answer("این شماره دیگه معتبر نیست، دوباره نگاه کن.", show_alert=True)
            return

        valid_indices = hokm_valid_play_indices(hand, game.trick_cards, game.trump)
        if idx not in valid_indices:
            leading_suit = game.trick_cards[0][1]["suit"]
            await query.answer(
                f"باید هم‌خال بازی کنی ({leading_suit})، این کارت رو نمی‌تونی بندازی.",
                show_alert=True,
            )
            return

        card = hand[idx]
        hokm_cancel_turn_timer(context, game)
        text, markup, finished = await hokm_process_card_play(context, key, game, user.id, idx)
        await query.answer(f"انداختی: {hokm_card_label(card)} ✅")
        if finished:
            await query.edit_message_text(text)
        else:
            await query.edit_message_text(text, reply_markup=markup)
        return


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data
    key = query.inline_message_id or str(query.message.chat_id)

    # دکمه‌های جدید استارت
    if data in ("show_streak", "help_games"):
        await start_buttons_handler(query, user, data, context)
        return

    # دکمه‌ی انصراف از پیوستن
    if data == "cancel_join":
        await cancel_join_handler(query, user, key, context)
        return

    # اولویت با بازی کشتی
    if data.startswith("bship_"):
        await battleship_button_handler(query, user, data, key, context)
        return

    if data.startswith("bj_"):
        await blackjack_button_handler(query, user, data, key, context)
        return

    if data == "tournament_join" or data.startswith("tournament_") or data.startswith("t_rps_"):
        await tournament_button_handler(query, user, data, key, context)
        return

    if data == "hokm_join" or data.startswith("hokm_"):
        await hokm_button_handler(query, user, data, key, context)
        return

    if data == "mafia_join" or data.startswith("mafia_"):
        await mafia_button_handler(query, user, data, key, context)
        return

    if data.startswith("quiz_"):
        await quiz_button_handler(query, user, data, key, context)
        return

    if data.startswith("hangman_"):
        await hangman_button_handler(query, user, data, key, context)
        return

    game = games.get(key)

    if not game:
        await query.answer("بازی پیدا نشد یا تموم شده. یه بازی جدید بساز.", show_alert=True)
        return

    if data.startswith("join_"):
        if user.id == game.player1_id:
            await query.answer("نمی‌تونی با خودت بازی کنی 😅", show_alert=True)
            return
        if game.player2_id is not None:
            await query.answer("بازی پره، صبر کن دور بعدی!", show_alert=True)
            return

        game.player2_id = user.id
        game.player2_name = user.first_name

        if game.game_type == "rps":
            await query.edit_message_text(
                f"⚔️ {game.player1_name} در مقابل {game.player2_name}\n"
                f"هر کی زودتر {WINS_NEEDED} راند رو ببره، برنده‌ست.\n\n"
                f"راند {game.round_num}: هر دو نفر مخفیانه انتخابتون رو بزنید 👇"
                + THANK_YOU,
                reply_markup=rps_choice_keyboard(),
            )
        elif game.game_type == "golpoch":
            game.hider_id = game.player1_id
            game.guesser_id = game.player2_id
            await query.edit_message_text(
                f"⚔️ {game.player1_name} در مقابل {game.player2_name}\n"
                f"هر کی زودتر {WINS_NEEDED} راند رو ببره، برنده‌ست.\n\n"
                f"راند {game.round_num}: نوبت {game.player1_name}ه — "
                "مخفیانه یه دست رو انتخاب کن 🤲"
                + THANK_YOU,
                reply_markup=hide_keyboard(),
            )
        elif game.game_type == "xo":
            game.turn_id = game.player1_id
            await query.edit_message_text(xo_turn_text(game) + THANK_YOU, reply_markup=xo_board_keyboard(game))
        else:  # morris
            game.turn_id = game.player1_id
            game.morris_queue = {game.player1_id: [], game.player2_id: []}
            await query.edit_message_text(morris_turn_text(game) + THANK_YOU, reply_markup=morris_board_keyboard(game))
        await query.answer("وارد بازی شدی! ✅")
        return

    if data.startswith("rps_"):
        if game.game_type != "rps":
            return
        if user.id not in (game.player1_id, game.player2_id):
            await query.answer("تو تو این بازی نیستی!", show_alert=True)
            return
        if game.player2_id is None:
            await query.answer("هنوز حریف دوم نیومده!", show_alert=True)
            return
        if user.id in game.choices:
            await query.answer("قبلاً انتخاب کردی، صبر کن حریفت هم انتخاب کنه.", show_alert=True)
            return

        choice = data.split("_", 1)[1]
        game.choices[user.id] = choice
        await query.answer(f"انتخاب شد: {RPS_CHOICES[choice]} ✅")

        if len(game.choices) < 2:
            return

        c1 = game.choices[game.player1_id]
        c2 = game.choices[game.player2_id]

        round_winner_name = None
        if c1 != c2:
            if RPS_BEATS.get((c1, c2)):
                game.score1 += 1
                round_winner_name = game.player1_name
            else:
                game.score2 += 1
                round_winner_name = game.player2_name

        text = (
            f"راند {game.round_num}:\n"
            f"{game.player1_name}: {RPS_CHOICES[c1]}\n"
            f"{game.player2_name}: {RPS_CHOICES[c2]}\n\n"
        )
        text += "🤝 این راند مساوی شد!\n\n" if round_winner_name is None else f"✅ برنده راند: {round_winner_name}\n\n"
        text += score_line(game)

        if game.score1 >= WINS_NEEDED or game.score2 >= WINS_NEEDED:
            p1_won = game.score1 >= WINS_NEEDED
            overall_winner = game.player1_name if p1_won else game.player2_name
            winner_id = game.player1_id if p1_won else game.player2_id
            loser_id = game.player2_id if p1_won else game.player1_id
            streak = bump_win_streak(winner_id, loser_id)
            user_names[winner_id] = overall_winner
            user_names[loser_id] = game.player2_name if p1_won else game.player1_name
            await stats_save_user(winner_id, overall_winner, streak)
            await stats_save_user(loser_id, game.player2_name if p1_won else game.player1_name, 0)
            await send_streak_update(context, winner_id, overall_winner)
            text += f"\n\n🏆🏆 برنده کل بازی: {overall_winner} 🏆🏆"
            text += win_streak_line(overall_winner, streak)
            text += THANK_YOU
            await query.edit_message_text(text)
            del games[key]
            return

        game.choices = {}
        game.round_num += 1
        text += f"\n\nراند {game.round_num}: دوباره انتخاب کنید 👇"
        await query.edit_message_text(text, reply_markup=rps_choice_keyboard())
        return

    if data.startswith("hide_"):
        if game.game_type != "golpoch":
            return
        if user.id != game.hider_id:
            await query.answer("نوبت تو نیست، صبر کن حریفت مخفی کنه.", show_alert=True)
            return
        if game.hidden_side is not None:
            await query.answer("قبلاً مخفی کردی!", show_alert=True)
            return

        game.hidden_side = data.split("_", 1)[1]
        hider_name = game.player1_name if game.hider_id == game.player1_id else game.player2_name
        guesser_name = game.player2_name if game.hider_id == game.player1_id else game.player1_name

        await query.edit_message_text(
            f"راند {game.round_num}:\n"
            f"🤲 {hider_name} یه دست رو مخفیانه انتخاب کرد.\n\n"
            f"نوبت {guesser_name}ه: حدس بزن تو کدوم دسته؟ 👇",
            reply_markup=guess_keyboard(),
        )
        await query.answer("انتخابت ثبت شد ✅ (مخفی موند)")
        return

    if data.startswith("guess_"):
        if game.game_type != "golpoch":
            return
        if user.id != game.guesser_id:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return

        guess = data.split("_", 1)[1]
        correct = guess == game.hidden_side

        hider_name = game.player1_name if game.hider_id == game.player1_id else game.player2_name
        guesser_name = game.player2_name if game.hider_id == game.player1_id else game.player1_name

        if correct:
            if game.guesser_id == game.player1_id:
                game.score1 += 1
            else:
                game.score2 += 1
            round_winner_name = guesser_name
        else:
            if game.hider_id == game.player1_id:
                game.score1 += 1
            else:
                game.score2 += 1
            round_winner_name = hider_name

        text = (
            f"راند {game.round_num}:\n"
            f"گل تو {SIDE_NAMES[game.hidden_side]} بود.\n"
            f"حدس {guesser_name}: {SIDE_NAMES[guess]}\n\n"
            f"{'✅ حدس درست بود!' if correct else '❌ حدس اشتباه بود!'}\n"
            f"برنده راند: {round_winner_name}\n\n"
        )
        text += score_line(game)

        if game.score1 >= WINS_NEEDED or game.score2 >= WINS_NEEDED:
            p1_won = game.score1 >= WINS_NEEDED
            overall_winner = game.player1_name if p1_won else game.player2_name
            winner_id = game.player1_id if p1_won else game.player2_id
            loser_id = game.player2_id if p1_won else game.player1_id
            streak = bump_win_streak(winner_id, loser_id)
            user_names[winner_id] = overall_winner
            user_names[loser_id] = game.player2_name if p1_won else game.player1_name
            await stats_save_user(winner_id, overall_winner, streak)
            await stats_save_user(loser_id, game.player2_name if p1_won else game.player1_name, 0)
            await send_streak_update(context, winner_id, overall_winner)
            text += f"\n\n🏆🏆 برنده کل بازی: {overall_winner} 🏆🏆"
            text += win_streak_line(overall_winner, streak)
            text += THANK_YOU
            await query.edit_message_text(text)
            del games[key]
            return

        game.hider_id, game.guesser_id = game.guesser_id, game.hider_id
        game.hidden_side = None
        game.round_num += 1
        next_hider_name = game.player1_name if game.hider_id == game.player1_id else game.player2_name
        text += f"\n\nراند {game.round_num}: نوبت {next_hider_name}ه — مخفیانه یه دست رو انتخاب کن 🤲"
        await query.edit_message_text(text, reply_markup=hide_keyboard())
        return

    if data.startswith("xo_"):
        if game.game_type != "xo":
            return
        if user.id not in (game.player1_id, game.player2_id):
            await query.answer("تو تو این بازی نیستی!", show_alert=True)
            return
        if game.player2_id is None:
            await query.answer("هنوز حریف دوم نیومده!", show_alert=True)
            return
        if user.id != game.turn_id:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return

        idx = int(data.split("_", 1)[1])
        if game.board[idx]:
            await query.answer("این خونه پره، یکی دیگه رو انتخاب کن.", show_alert=True)
            return

        symbol = "X" if user.id == game.player1_id else "O"
        game.board[idx] = symbol
        await query.answer(f"گذاشتی: {XO_SYMBOLS[symbol]} ✅")

        winner_symbol = xo_winner(game.board)
        is_draw = winner_symbol is None and all(game.board)

        if winner_symbol:
            winner_name = game.player1_name if winner_symbol == "X" else game.player2_name
            winner_id = game.player1_id if winner_symbol == "X" else game.player2_id
            loser_id = game.player2_id if winner_symbol == "X" else game.player1_id
            streak = bump_win_streak(winner_id, loser_id)
            user_names[winner_id] = winner_name
            user_names[loser_id] = game.player2_name if winner_symbol == "X" else game.player1_name
            await stats_save_user(winner_id, winner_name, streak)
            await stats_save_user(loser_id, game.player2_name if winner_symbol == "X" else game.player1_name, 0)
            await send_streak_update(context, winner_id, winner_name)
            text = (
                f"{game.player1_name} (❌) در مقابل {game.player2_name} (🟢)\n\n"
                f"🏆🏆 برنده: {winner_name} ({XO_SYMBOLS[winner_symbol]}) 🏆🏆"
            )
            text += win_streak_line(winner_name, streak)
            text += THANK_YOU
            await query.edit_message_text(text, reply_markup=xo_board_keyboard(game))
            del games[key]
            return

        if is_draw:
            text = (
                f"{game.player1_name} (❌) در مقابل {game.player2_name} (🟢)\n\n"
                "🤝 مساوی شد! صفحه پر شد و کسی نبرد."
                + THANK_YOU
            )
            await query.edit_message_text(text, reply_markup=xo_board_keyboard(game))
            del games[key]
            return

        game.turn_id = game.player2_id if user.id == game.player1_id else game.player1_id
        await query.edit_message_text(xo_turn_text(game), reply_markup=xo_board_keyboard(game))
        return

    if data.startswith("morris_"):
        if game.game_type != "morris":
            return
        if user.id not in (game.player1_id, game.player2_id):
            await query.answer("تو تو این بازی نیستی!", show_alert=True)
            return
        if game.player2_id is None:
            await query.answer("هنوز حریف دوم نیومده!", show_alert=True)
            return
        if user.id != game.turn_id:
            await query.answer("نوبت تو نیست!", show_alert=True)
            return

        idx = int(data.split("_", 1)[1])
        if game.board[idx]:
            await query.answer("این خونه پره، یکی دیگه رو انتخاب کن.", show_alert=True)
            return

        symbol = "X" if user.id == game.player1_id else "O"
        queue = game.morris_queue.setdefault(user.id, [])

        if len(queue) < MORRIS_PIECES_PER_PLAYER:
            game.board[idx] = symbol
            queue.append(idx)
            await query.answer(f"گذاشتی: {XO_SYMBOLS[symbol]} ✅")
        else:
            oldest = queue.pop(0)
            game.board[oldest] = ""
            game.board[idx] = symbol
            queue.append(idx)
            await query.answer(f"مهره‌تو جابه‌جا کردی: {XO_SYMBOLS[symbol]} ✅")

        winner_symbol = xo_winner(game.board)

        if winner_symbol:
            winner_name = game.player1_name if winner_symbol == "X" else game.player2_name
            winner_id = game.player1_id if winner_symbol == "X" else game.player2_id
            loser_id = game.player2_id if winner_symbol == "X" else game.player1_id
            streak = bump_win_streak(winner_id, loser_id)
            user_names[winner_id] = winner_name
            user_names[loser_id] = game.player2_name if winner_symbol == "X" else game.player1_name
            await stats_save_user(winner_id, winner_name, streak)
            await stats_save_user(loser_id, game.player2_name if winner_symbol == "X" else game.player1_name, 0)
            await send_streak_update(context, winner_id, winner_name)
            text = (
                f"{game.player1_name} (❌) در مقابل {game.player2_name} (🟢)\n\n"
                f"🏆🏆 برنده: {winner_name} ({XO_SYMBOLS[winner_symbol]}) 🏆🏆"
            )
            text += win_streak_line(winner_name, streak)
            text += THANK_YOU
            await query.edit_message_text(text, reply_markup=morris_board_keyboard(game))
            del games[key]
            return

        game.turn_id = game.player2_id if user.id == game.player1_id else game.player1_id
        await query.edit_message_text(morris_turn_text(game), reply_markup=morris_board_keyboard(game))
        return


# ======================== Inline Query Handler ========================

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    results = [
        InlineQueryResultArticle(
            id=f"rps-{uuid.uuid4()}",
            title="🪨📄✂️ سنگ کاغذ قیچی",
            description="بهترین از چند راند، هرکی زودتر ۳ برد بگیره می‌بره",
            input_message_content=InputTextMessageContent(
                start_message_text("rps", user.first_name)
            ),
            reply_markup=join_keyboard("rps"),
        ),
        InlineQueryResultArticle(
            id=f"golpoch-{uuid.uuid4()}",
            title="🤲 گل یا پوچ",
            description="یکی مخفی می‌کنه، یکی حدس می‌زنه — هرکی زودتر ۳ برد بگیره می‌بره",
            input_message_content=InputTextMessageContent(
                start_message_text("golpoch", user.first_name)
            ),
            reply_markup=join_keyboard("golpoch"),
        ),
        InlineQueryResultArticle(
            id=f"xo-{uuid.uuid4()}",
            title="❌🟢 دوز",
            description="بازی دوز کلاسیک روی صفحه ۳در۳",
            input_message_content=InputTextMessageContent(
                start_message_text("xo", user.first_name)
            ),
            reply_markup=join_keyboard("xo"),
        ),
        InlineQueryResultArticle(
            id=f"morris-{uuid.uuid4()}",
            title="🔄 دوز متحرک (۳ مهره‌ای)",
            description="هر کی ۳ مهره داره، بعدش باید قدیمی‌ترینشو جابه‌جا کنه — تا یکی نبره تموم نمی‌شه",
            input_message_content=InputTextMessageContent(
                start_message_text("morris", user.first_name)
            ),
            reply_markup=join_keyboard("morris"),
        ),
        InlineQueryResultArticle(
            id=f"hokm1-{uuid.uuid4()}",
            title="🃏 حکم — تک راند (۴ نفره)",
            description="یه راند و تمام، هر تیم که ۷ از ۱۳ دست رو ببره برنده‌ست",
            input_message_content=InputTextMessageContent(
                hokm_join_status_text(HokmGame(target_rounds=1, rounds_needed=1, players=[{"id": user.id, "name": user.first_name}]))
            ),
            reply_markup=hokm_join_keyboard(),
        ),
        InlineQueryResultArticle(
            id=f"hokm3-{uuid.uuid4()}",
            title="🃏 حکم — بهترین از ۳ راند (۴ نفره)",
            description="هر تیم زودتر ۲ راند رو ببره برنده‌ی کل بازیه",
            input_message_content=InputTextMessageContent(
                hokm_join_status_text(HokmGame(target_rounds=3, rounds_needed=2, players=[{"id": user.id, "name": user.first_name}]))
            ),
            reply_markup=hokm_join_keyboard(),
        ),
        InlineQueryResultArticle(
            id=f"hokm5-{uuid.uuid4()}",
            title="🃏 حکم — بهترین از ۵ راند (۴ نفره)",
            description="هر تیم زودتر ۳ راند رو ببره برنده‌ی کل بازیه",
            input_message_content=InputTextMessageContent(
                hokm_join_status_text(HokmGame(target_rounds=5, rounds_needed=3, players=[{"id": user.id, "name": user.first_name}]))
            ),
            reply_markup=hokm_join_keyboard(),
        ),
        InlineQueryResultArticle(
            id=f"mafia-{uuid.uuid4()}",
            title="🕵️ مافیا",
            description=f"بازی گروهی نقش‌محور، حداقل {MAFIA_MIN_PLAYERS} نفر — نقش‌ها تو پیوی اعلام می‌شه",
            input_message_content=InputTextMessageContent(mafia_lobby_placeholder_text(user.first_name)),
            reply_markup=mafia_lobby_keyboard(),
        ),
        quiz_inline_result(),
        hangman_inline_result(user.first_name),
        tournament_inline_result(user.first_name),
        blackjack_inline_result(user.first_name),
        battleship_inline_result(user.first_name),
    ]
    await update.inline_query.answer(results, cache_time=0, is_personal=True)


# ======================== Chosen Inline Result Handler ========================

async def chosen_result_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chosen = update.chosen_inline_result
    user = chosen.from_user
    key = chosen.inline_message_id
    if not key:
        return
    result_id = chosen.result_id
    if result_id.startswith("rps-"):
        games[key] = Game(game_type="rps", player1_id=user.id, player1_name=user.first_name)
    elif result_id.startswith("golpoch-"):
        games[key] = Game(game_type="golpoch", player1_id=user.id, player1_name=user.first_name)
    elif result_id.startswith("xo-"):
        games[key] = Game(game_type="xo", player1_id=user.id, player1_name=user.first_name)
    elif result_id.startswith("morris-"):
        games[key] = Game(game_type="morris", player1_id=user.id, player1_name=user.first_name)
    elif result_id.startswith("hokm1-"):
        hokm_games[key] = HokmGame(target_rounds=1, rounds_needed=1, players=[{"id": user.id, "name": user.first_name}])
    elif result_id.startswith("hokm3-"):
        hokm_games[key] = HokmGame(target_rounds=3, rounds_needed=2, players=[{"id": user.id, "name": user.first_name}])
    elif result_id.startswith("hokm5-"):
        hokm_games[key] = HokmGame(target_rounds=5, rounds_needed=3, players=[{"id": user.id, "name": user.first_name}])
    elif result_id.startswith("mafia-"):
        game = MafiaGame(key=key, started_by=user.id)
        game.players.append(MafiaPlayer(id=user.id, name=user.first_name))
        mafia_games[key] = game
        await mafia_save(game)
        if context.job_queue:
            job_name = f"mafia_autobegin_{key}"
            context.job_queue.run_once(mafia_join_timeout, MAFIA_JOIN_SECONDS, data={"key": key}, name=job_name)
            game.job_names.append(job_name)
            await mafia_save(game)
    elif result_id.startswith("hangman-"):
        game = HangmanGame(key=key, starter_id=user.id, starter_name=user.first_name)
        game.players = [{"id": user.id, "name": user.first_name}]
        hangman_games[key] = game
    elif result_id.startswith("quiz-"):
        game = QuizGame(key=key, starter_id=user.id)
        game.players = [{"id": user.id, "name": user.first_name, "score": 0}]
        quiz_games[key] = game
    elif result_id.startswith("tournament-"):
        game = TournamentGame(key=key, started_by=user.id)
        game.players = [{"id": user.id, "name": user.first_name}]
        tournament_games[key] = game
    elif result_id.startswith("blackjack-"):
        game = BlackjackGame(key=key, started_by=user.id)
        game.players = [BlackjackPlayer(id=user.id, name=user.first_name)]
        blackjack_games[key] = game
    elif result_id.startswith("bship-"):
        game = BattleshipGame(
            key=key,
            starter_id=user.id,
            player1_id=user.id,
            player1_name=user.first_name,
        )
        battleship_games[key] = game
        await battleship_save(game)


# ======================== هندلر Mini App (WebApp) ========================

async def mini_app_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.web_app_data:
        return
    
    try:
        data = json.loads(update.message.web_app_data.data)
        user = update.effective_user
        action = data.get('action')
        game_type = data.get('game')
        
        if action == 'start':
            response = await mini_app_start_game(user, game_type, context)
        elif action == 'hit' and game_type == 'blackjack':
            response = await mini_app_blackjack_action(user, 'hit', context)
        elif action == 'stand' and game_type == 'blackjack':
            response = await mini_app_blackjack_action(user, 'stand', context)
        elif action == 'view' and game_type == 'blackjack':
            response = await mini_app_blackjack_view(user, context)
        else:
            response = {'error': 'درخواست نامعتبر'}
        
        await update.message.reply_text(json.dumps(response))
        
    except Exception as e:
        await update.message.reply_text(json.dumps({'error': str(e)}))


async def mini_app_start_game(user, game_type: str, context: ContextTypes.DEFAULT_TYPE) -> dict:
    return {
        'status': 'started',
        'game': game_type,
        'message': f'بازی {game_type} شروع شد!',
        'players': [{'id': user.id, 'name': user.first_name}],
        'phase': 'playing',
        'turn_index': 0
    }


async def mini_app_blackjack_action(user, action: str, context: ContextTypes.DEFAULT_TYPE) -> dict:
    return {
        'status': 'ok',
        'action': action,
        'message': f'اقدام {action} انجام شد'
    }


async def mini_app_blackjack_view(user, context: ContextTypes.DEFAULT_TYPE) -> dict:
    return {
        'cards': [],
        'score': 0,
        'message': 'کارت‌های شما'
    }


# ======================== پنل فعالیت ========================

ACTIVITY_PAGE_TEMPLATE = """
<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>پنل فعالیت بازی‌ها</title>
<link rel="icon" type="image/png" href="/static/1.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #10131a; --surface: #171b24; --border: #2a3040;
    --text: #eceef3; --text-muted: #8991a6; --text-dim: #565d70;
    --jade: #5fd9a6; --blue: #7c9bff; --amber: #e8b34f;
    --font-body: 'Vazirmatn', Tahoma, sans-serif;
    --font-mono: 'JetBrains Mono', Consolas, monospace;
  }
  * { box-sizing: border-box; }
  body {
    font-family: var(--font-body); background: var(--bg); color: var(--text);
    margin: 0; padding: 28px 20px 50px; line-height: 1.6;
  }
  .wrap { max-width: 760px; margin: 0 auto; }
  header { border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 20px; }
  .eyebrow { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.14em; color: var(--text-dim); text-transform: uppercase; }
  h1 { font-size: 20px; font-weight: 800; margin: 4px 0 0; }
  .sub { color: var(--text-muted); font-size: 12.5px; margin-top: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 18px; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .stat .n { font-family: var(--font-mono); font-size: 24px; font-weight: 700; color: var(--jade); }
  .stat .l { font-size: 12.5px; color: var(--text-muted); margin-top: 4px; }
  .total { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-top: 14px; display: flex; align-items: center; justify-content: space-between; }
  .total .n { font-family: var(--font-mono); font-size: 28px; font-weight: 800; color: var(--blue); }
  footer { margin-top: 24px; text-align: center; font-family: var(--font-mono); font-size: 10.5px; color: var(--text-dim); letter-spacing: 0.06em; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">rps‑bot · activity</div>
    <h1>📊 پنل فعالیت بازی‌ها</h1>
    <div class="sub">آپ‌تایم بات: <span id="uptime">—</span></div>
  </header>

  <div class="total">
    <span>🎮 مجموع بازی‌های در حال انجام</span>
    <span class="n" id="total_games">—</span>
  </div>

  <div class="grid" id="grid"></div>

  <footer>127.0.0.1:8088</footer>
</div>

<script>
const LABELS = {
  rps: "🪨 سنگ‌کاغذ‌قیچی", golpoch: "🤲 گل یا پوچ", xo: "❌ دوز",
  morris: "🔄 دوز متحرک", hokm: "🃏 حکم", mafia: "🕵️ مافیا",
  quiz: "❓ کوییز", hangman: "🪢 دار بازی", tournament: "🏆 تورنمنت",
  blackjack: "🂡 بلک‌جک", bship: "🤼 کشتی",
};
async function refresh() {
  try {
    const res = await fetch('/status.json');
    const data = await res.json();
    document.getElementById('uptime').textContent = data.uptime;
    document.getElementById('total_games').textContent = data.total;
    const grid = document.getElementById('grid');
    grid.innerHTML = '';
    for (const [key, label] of Object.entries(LABELS)) {
      const count = data.counts[key] ?? 0;
      const div = document.createElement('div');
      div.className = 'stat';
      div.innerHTML = '<div class="n">' + count + '</div><div class="l">' + label + '</div>';
      grid.appendChild(div);
    }
  } catch (e) { /* ignore */ }
}
refresh();
setInterval(refresh, 3000);
</script>
<script src="/static/pet-bg.js"></script>
</body>
</html>
"""


def _activity_uptime_display() -> str:
    seconds = int(time.time() - BOT_START_TIME)
    if seconds < 60:
        return f"{seconds} ثانیه"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقیقه"
    hours = minutes // 60
    return f"{hours} ساعت و {minutes % 60} دقیقه"


def _activity_counts() -> dict:
    counts = {"rps": 0, "golpoch": 0, "xo": 0, "morris": 0}
    for g in games.values():
        if g.game_type in counts:
            counts[g.game_type] += 1
    counts["hokm"] = len(hokm_games)
    counts["mafia"] = len(mafia_games)
    counts["quiz"] = len(quiz_games)
    counts["hangman"] = len(hangman_games)
    counts["tournament"] = len(tournament_games)
    counts["blackjack"] = len(blackjack_games)
    counts["bship"] = len(battleship_games)
    return counts


def start_activity_dashboard_async():
    try:
        from flask import Flask, jsonify, render_template_string
    except ImportError:
        logger.warning("پکیج flask نصب نیست؛ پنل فعالیت بازی‌ها بالا نمیاد (خودِ بات عادی کار می‌کنه).")
        return

    dash = Flask(__name__)
    dash.logger.disabled = True
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    @dash.route("/")
    def _activity_dashboard():
        return render_template_string(ACTIVITY_PAGE_TEMPLATE)

    @dash.route("/status.json")
    def _activity_status():
        return jsonify({
            "uptime": _activity_uptime_display(),
            "counts": _activity_counts(),
            "total": sum(_activity_counts().values()),
        })

    threading.Thread(target=lambda: dash.run(host=ACTIVITY_PANEL_HOST, port=ACTIVITY_PANEL_PORT, threaded=True, use_reloader=False), daemon=True).start()


# ======================== دستور /start (نسخه ۲.۷) ========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    welcome_text = (
        f"🎮 سلام {user.first_name} عزیز! به ربات بازی‌های گروهی نسخه ۲.۷ خوش آمدید.\n\n"
        "🤖 این ربات شامل بازی‌های زیر است:\n"
        "• 🪨 سنگ‌کاغذ‌قیچی (حالت مسابقه)\n"
        "• 🤲 گل یا پوچ\n"
        "• ❌🟢 دوز (کلاسیک)\n"
        "• 🔄 دوز متحرک (۳ مهره‌ای)\n"
        "• 🃏 حکم (تک‌راند، ۳‌راند، ۵‌راند)\n"
        "• 🕵️ مافیا (نقش‌محور)\n"
        "• 🧠 اولین نفر جواب بده (کوییز گروهی)\n"
        "• 🎯 دار بازی (حدس کلمه)\n"
        "• 🏆 تورنمنت سنگ‌کاغذ‌قیچی (حذفی)\n"
        "• 🃏 ۲۱ با پاسور (بلک‌جک)\n"
        "• 🤼 کشتی (PvP با سوال و فن‌های جدید)\n\n"
        "📌 دستورات شروع بازی:\n"
        "/rps - سنگ‌کاغذ‌قیچی\n"
        "/golpoch - گل یا پوچ\n"
        "/xo - دوز\n"
        "/morris - دوز متحرک\n"
        "/hokm1 - حکم تک‌راند (۴ نفره)\n"
        "/hokm3 - حکم بهترین از ۳ راند (۴ نفره)\n"
        "/hokm5 - حکم بهترین از ۵ راند (۴ نفره)\n"
        "/hangman - دار بازی\n"
        "/streak - مشاهده جدول استریک برد (از دکمه زیر هم می‌توانید استفاده کنید)\n\n"
        "💡 نکته: برای شروع هر بازی، در گروه یا پیوی ربات عبارت @username_robot را تایپ کنید و بازی مورد نظر را انتخاب کنید.\n\n"
        "برای ارائه پیشنهاد انتقاد یا گزارش باگ به :@Arsheyaio مراجعه کنید\n"
         "لینک دانلود پروژه:https://github.com/Arsheya-oi/mini-game-bot-telegram\n\n"
        " تشکر ویژه از Amiro بابت سرور❤️🙏\n"
        "🔹 نسخه ۲.۷ - رفع باگ دار بازی و دیتابیس مافیا"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏅 مشاهده جدول استریک", callback_data="show_streak")],
        [InlineKeyboardButton("📖 راهنمای کامل بازی‌ها", callback_data="help_games")],
    ])

    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=welcome_text,
            reply_markup=keyboard
        )
        if update.message.chat.type != "private":
            await update.message.reply_text("📩 پیام خوش‌آمدگویی نسخه ۲.۷ به پیوی شما ارسال شد. لطفاً آن را بررسی کنید.")
    except (Forbidden, BadRequest):
        await update.message.reply_text("لطفاً ابتدا به ربات پیام /start بدهید تا بتوانم پیام کامل را برایتان بفرستم.")


# ======================== Main ========================

async def load_all_stats():
    global win_streaks, user_names
    win_streaks, user_names = await stats_load_all()


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    async def post_init(app: Application):
        await load_all_stats()
        await mafia_restore_games(app)
        await battleship_restore_games(app)

    app.post_init = post_init

    # دستورات
    app.add_handler(CommandHandler("rps", rps_command))
    app.add_handler(CommandHandler("golpoch", golpoch_command))
    app.add_handler(CommandHandler("xo", xo_command))
    app.add_handler(CommandHandler("morris", morris_command))
    app.add_handler(CommandHandler("hokm1", hokm1_command))
    app.add_handler(CommandHandler("hokm3", hokm3_command))
    app.add_handler(CommandHandler("hokm5", hokm5_command))
    app.add_handler(CommandHandler("hangman", hangman_command))
    app.add_handler(CommandHandler("streak", streak_command))
    app.add_handler(CommandHandler("start", start_command))

    # هندلرهای پیام
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, hangman_guess_text_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, mini_app_handler))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(ChosenInlineResultHandler(chosen_result_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    start_activity_dashboard_async()
    logger.info("ربات نسخه ۲.۷ با رفع باگ‌ها روشن شد...")
    app.run_polling()


if __name__ == "__main__":
    main()