# ربات سنگ‌کاغذ‌قیچی گروهی (حالت inline — بدون نیاز به عضویت تو گروه)

## ۱. ساخت ربات و گرفتن توکن
1. تو تلگرام برو به [@BotFather](https://t.me/BotFather).
2. `/newbot` رو بزن، اسم و یوزرنیم دلخواه بده (یوزرنیم باید به `bot` ختم بشه).
3. توکنی که میده رو کپی کن و داخل `rps_bot.py` جای `PUT-YOUR-TOKEN-HERE` بذار.

## ۲. فعال کردن حالت Inline (خیلی مهم!)
هنوز تو چت با BotFather:

1. بنویس: `/setinline`
2. ربات خودت رو انتخاب کن.
3. یه متن راهنما بفرست، مثلاً: `شروع بازی سنگ کاغذ قیچی`

بعد:

1. بنویس: `/setinlinefeedback`
2. ربات خودت رو انتخاب کن.
3. گزینه **Enabled** (۱۰۰٪) رو بزن.

(این قسمت لازمه چون کد باید بفهمه پیام بازی واقعاً کِی فرستاده شده تا بازیکن اول رو ثبت کنه.)

## ۳. نصب پیش‌نیازها و اجرا
```bash
pip install -r requirements.txt
python rps_bot.py
```
تا وقتی این دستور در حال اجراست ربات فعاله.

## ۴. نحوه بازی (بدون اضافه کردن ربات به گروه!)
1. تو گروه دوستات، تو کادر نوشتن پیام بنویس:
   ```
   @یوزرنیم_ربات
   ```
   (یوزرنیمی که موقع ساخت ربات انتخاب کردی)
2. یه لیست کوچیک بالای صفحه میاد با یه گزینه "🎮 شروع بازی سنگ‌کاغذ‌قیچی".
3. روش بزن — یه پیام با دکمه "قبول چالش" تو گروه فرستاده می‌شه (انگار خودت نوشتیش).
4. یه نفر دیگه روی "قبول چالش" می‌زنه.
5. هر دو نفر دکمه‌های سنگ/کاغذ/قیچی رو می‌زنن (فقط خودشون جواب خودشون رو می‌بینن).
6. نتیجه خودکار تو همون پیام گروه اعلام می‌شه.

نکته: این روش نیاز نداره ربات عضو گروه باشه یا دسترسی خاصی داشته باشه.

## اجرای همیشگی (اختیاری)
با بستن ترمینال، ربات خاموش می‌شه. برای روشن ماندن دائمی باید رو یه سرور/سرویس هاست
(مثل یه VPS ارزون یا Railway/Render) اجراش کنی.
--------------------------------------------------------------------------------------------------------------------------------------------------------------------
این متن به انگلیسی:

---

**Rock-Paper-Scissors Group Bot (Inline mode — no need to add the bot to the group)**

**1. Creating the bot and getting a token**

1. In Telegram, go to [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, give it a name and a username (the username must end with `bot`).
3. Copy the token it gives you and put it in `rps_bot.py` in place of `PUT-YOUR-TOKEN-HERE`.

**2. Enabling Inline mode (very important!)**

Still in the chat with BotFather:

1. Type: `/setinline`
2. Select your bot.
3. Send a placeholder text, e.g.: `Start a Rock Paper Scissors game`

Then:

1. Type: `/setinlinefeedback`
2. Select your bot.
3. Choose the **Enabled (100%)** option.

(This step is necessary because the code needs to know exactly when a game message has actually been sent, in order to register the first player.)

**3. Installing requirements and running**

```
pip install -r requirements.txt
python rps_bot.py
```

The bot stays active as long as this command is running.

**4. How to play (without adding the bot to the group!)**

1. In your friends' group, in the message input box, type:

```
@your_bot_username
```

(the username you chose when creating the bot)

2. A small list appears above with an option "🎮 Start Rock Paper Scissors game."
3. Tap it — a message with a "Accept Challenge" button gets sent to the group (as if you wrote it yourself).
4. Someone else taps "Accept Challenge."
5. Both players tap Rock/Paper/Scissors buttons (each only sees their own choice).
6. The result is announced automatically in the same group message.

Note: this method doesn't require the bot to be a member of the group or have any special permissions.

**Running permanently (optional)**

Closing the terminal will turn off the bot. To keep it running permanently, you need to run it on a server/hosting service (such as a cheap VPS or Railway/Render).
