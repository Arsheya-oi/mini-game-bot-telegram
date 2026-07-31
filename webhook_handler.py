# ===================================================
#  هندلر Mini App (برای ارتباط با وب‌سایت)
# ===================================================

import json
import logging
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

# ===================================================
#  تابع اصلی پردازش درخواست‌های Mini App
# ===================================================

async def mini_app_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    این تابع درخواست‌های ارسال‌شده از Mini App رو دریافت می‌کنه.
    Mini App از طریق tg.sendData() یا fetch() داده‌ها رو به ربات می‌فرسته.
    """
    
    # بررسی اینکه آیا داده‌ای از WebApp اومده
    if not update.message or not update.message.web_app_data:
        return
    
    try:
        # دریافت داده‌های ارسال‌شده از Mini App
        data = json.loads(update.message.web_app_data.data)
        user = update.effective_user
        
        logger.info(f"دریافت درخواست از Mini App - کاربر: {user.first_name} - اکشن: {data.get('action')}")
        
        # پردازش درخواست بر اساس نوع
        action = data.get('action')
        game = data.get('game')
        
        response = None
        
        # ===== شروع بازی =====
        if action == 'start':
            response = await handle_start_game(user, game, context, data)
            
        # ===== بازی ۲۱ (بلک‌جک) =====
        elif action == 'hit' and game == 'blackjack':
            response = await handle_blackjack_action(user, 'hit', context, data)
            
        elif action == 'stand' and game == 'blackjack':
            response = await handle_blackjack_action(user, 'stand', context, data)
            
        elif action == 'view' and game == 'blackjack':
            response = await handle_blackjack_view(user, context, data)
            
        # ===== سنگ‌کاغذ‌قیچی =====
        elif action == 'choice' and game == 'rps':
            response = await handle_rps_choice(user, data.get('choice'), context, data)
            
        # ===== دوز (XO) =====
        elif action == 'move' and game == 'xo':
            response = await handle_xo_move(user, data.get('index'), context, data)
            
        # ===== لغو بازی =====
        elif action == 'cancel':
            response = await handle_cancel_game(user, game, context, data)
            
        else:
            response = {'error': f'درخواست نامعتبر: {action} برای بازی {game}'}
        
        # ارسال پاسخ به Mini App
        if response:
            await update.message.reply_text(json.dumps(response))
            
    except json.JSONDecodeError:
        await update.message.reply_text(json.dumps({'error': 'داده‌های ارسال‌شده معتبر نیستند'}))
    except Exception as e:
        logger.exception(f"خطا در پردازش درخواست Mini App: {e}")
        await update.message.reply_text(json.dumps({'error': str(e)}))


# ===================================================
#  توابع کمکی برای پردازش درخواست‌ها
# ===================================================

async def handle_start_game(user, game_type, context, data):
    """
    شروع یک بازی جدید برای Mini App
    اینجا باید کد شروع بازی رو از بخش‌های دیگر کپی کنی
    """
    # فعلاً یک پاسخ نمونه برمی‌گردونیم
    # بعداً این رو با کد واقعی جایگزین می‌کنیم
    return {
        'status': 'started',
        'game': game_type,
        'message': f'بازی {game_type} شروع شد!',
        'players': [{'id': user.id, 'name': user.first_name}],
        'turn': user.id
    }


async def handle_blackjack_action(user, action, context, data):
    """
    مدیریت اقدامات بازی ۲۱ (کارت بگیر / بایست)
    """
    # TODO: کد منطق بازی ۲۱ رو اینجا قرار بده
    return {
        'status': 'ok',
        'action': action,
        'message': f'اقدام {action} انجام شد',
        'game': 'blackjack'
    }


async def handle_blackjack_view(user, context, data):
    """
    نمایش کارت‌های بازیکن در Mini App
    """
    # TODO: کارت‌های بازیکن رو از وضعیت بازی بخون و برگردون
    return {
        'status': 'ok',
        'cards': [],
        'score': 0,
        'game': 'blackjack'
    }


async def handle_rps_choice(user, choice, context, data):
    """
    انتخاب سنگ/کاغذ/قیچی در بازی
    """
    # TODO: کد منطق سنگ‌کاغذ‌قیچی رو اینجا قرار بده
    return {
        'status': 'ok',
        'choice': choice,
        'message': f'انتخاب شما: {choice}',
        'game': 'rps'
    }


async def handle_xo_move(user, index, context, data):
    """
    حرکت در بازی دوز
    """
    # TODO: کد منطق دوز رو اینجا قرار بده
    return {
        'status': 'ok',
        'index': index,
        'message': f'حرکت در خانه {index} ثبت شد',
        'game': 'xo'
    }


async def handle_cancel_game(user, game_type, context, data):
    """
    لغو بازی
    """
    # TODO: بازی رو از حافظه پاک کن
    return {
        'status': 'cancelled',
        'game': game_type,
        'message': f'بازی {game_type} لغو شد'
    }


# ===================================================
#  تابع کمکی برای ارسال پاسخ به Mini App
# ===================================================

async def send_to_mini_app(update: Update, response: dict):
    """ارسال پاسخ به Mini App"""
    try:
        await update.message.reply_text(json.dumps(response))
    except Exception as e:
        logger.error(f"خطا در ارسال پاسخ به Mini App: {e}")