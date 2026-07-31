// ===================================================
//  اتصال به تلگرام WebApp
// ===================================================

const tg = window.Telegram.WebApp;
tg.expand(); // بزرگ کردن صفحه به تمام نمایشگر

// ===================================================
//  تنظیمات اولیه
// ===================================================

const BOT_USERNAME = 'yay-game'; // ⚠️ اینجا نام کاربری ربات خودت رو بذار (مثل: MyGameBot)
const API_URL = '/api/game'; // آدرس سرور Backend (اگر از Node.js استفاده می‌کنی)
let currentGame = null; // بازی فعلی
let gameState = null; // وضعیت بازی

// ===================================================
//  منو و ناوبری
// ===================================================

function showMenu() {
    document.getElementById('menu').style.display = 'block';
    document.getElementById('game-container').style.display = 'none';
    document.getElementById('game-content').innerHTML = '';
}

function goBack() {
    if (currentGame) {
        // ارسال پیام لغو به ربات
        sendToBot({ action: 'cancel', game: currentGame });
    }
    showMenu();
}

function startGame(gameType) {
    currentGame = gameType;
    document.getElementById('menu').style.display = 'none';
    document.getElementById('game-container').style.display = 'block';
    document.getElementById('game-title').textContent = getGameTitle(gameType);
    document.getElementById('game-content').innerHTML = '<div class="loading">⏳ در حال شروع بازی...</div>';
    
    // ارسال درخواست شروع بازی به ربات
    const user = tg.initDataUnsafe?.user || {};
    sendToBot({ 
        action: 'start', 
        game: gameType, 
        user_id: user.id || 0,
        user_name: user.first_name || 'کاربر'
    });
}

function getGameTitle(type) {
    const titles = {
        'rps': '🪨📄✂️ سنگ کاغذ قیچی',
        'golpoch': '🤲 گل یا پوچ',
        'xo': '❌🟢 دوز',
        'morris': '🔄 دوز متحرک',
        'hokm': '🃏 حکم',
        'mafia': '🕵️ مافیا',
        'quiz': '🧠 کوییز',
        'hangman': '🎯 دار بازی',
        'tournament': '🏆 تورنمنت',
        'blackjack': '🃏 ۲۱ با پاسور'
    };
    return titles[type] || 'بازی';
}

// ===================================================
//  ارتباط با ربات (ارسال درخواست)
// ===================================================

function sendToBot(data) {
    // اضافه کردن اطلاعات کاربر تلگرام
    const fullData = {
        ...data,
        chat_id: tg.initDataUnsafe?.chat?.id || 0,
        user: tg.initDataUnsafe?.user || {},
        init_data: tg.initData || ''
    };
    
    // ارسال درخواست به سرور Backend
    fetch(API_URL, {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'X-Telegram-Init-Data': tg.initData || ''
        },
        body: JSON.stringify(fullData)
    })
    .then(res => res.json())
    .then(response => {
        if (response.error) {
            showError(response.error);
        } else {
            handleGameUpdate(response);
        }
    })
    .catch(err => {
        // اگر سرور Backend در دسترس نبود، از روش جایگزین استفاده می‌کنیم
        // (ارسال پیام مستقیم به ربات از طریق WebApp)
        sendToBotDirect(data);
    });
}

// ===================================================
//  روش جایگزین: ارسال مستقیم به ربات از طریق WebApp
// ===================================================

function sendToBotDirect(data) {
    // این روش از قابلیت WebApp ارسال پیام به ربات استفاده می‌کند
    // ربات باید هندلر WebAppData داشته باشد
    tg.sendData(JSON.stringify(data));
}

// ===================================================
//  نمایش خطا
// ===================================================

function showError(message) {
    document.getElementById('game-content').innerHTML = `
        <div style="background:#ff1744;color:white;padding:20px;border-radius:10px;text-align:center;">
            ❌ ${message}
            <br><br>
            <button onclick="goBack()" style="background:#fff;color:#222;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;">
                بازگشت به منو
            </button>
        </div>
    `;
}

// ===================================================
//  مدیریت پاسخ‌های ربات
// ===================================================

function handleGameUpdate(data) {
    const gameType = data.game || currentGame;
    
    switch(gameType) {
        case 'blackjack':
            renderBlackjack(data);
            break;
        case 'rps':
            renderRPS(data);
            break;
        case 'xo':
            renderXO(data);
            break;
        case 'morris':
            renderMorris(data);
            break;
        case 'golpoch':
            renderGolpoch(data);
            break;
        case 'hokm':
            renderHokm(data);
            break;
        case 'mafia':
            renderMafia(data);
            break;
        case 'quiz':
            renderQuiz(data);
            break;
        case 'hangman':
            renderHangman(data);
            break;
        case 'tournament':
            renderTournament(data);
            break;
        default:
            // نمایش داده‌های خام برای تست
            document.getElementById('game-content').innerHTML = `
                <div style="text-align:center;padding:40px;">
                    <h3>${data.title || 'بازی'}</h3>
                    <pre style="text-align:right;background:#0f3460;padding:20px;border-radius:10px;overflow:auto;font-size:12px;max-height:400px;">${JSON.stringify(data, null, 2)}</pre>
                </div>
            `;
    }
}

// ===================================================
//  ===== بازی ۲۱ (بلک‌جک) – کامل =====
// ===================================================

function renderBlackjack(data) {
    const container = document.getElementById('game-content');
    
    // استخراج اطلاعات
    const players = data.players || [];
    const dealer = data.dealer || { cards: [], score: '?' };
    const turn = data.turn_index || 0;
    const phase = data.phase || 'playing';
    const result = data.result || null;
    const allFinished = data.all_finished || false;
    const dealerRevealed = data.dealer_revealed || allFinished;
    const myId = tg.initDataUnsafe?.user?.id || 0;
    
    let html = `<div class="blackjack-table">`;
    
    // ===== نمایش دیلر =====
    html += `<div class="blackjack-dealer">`;
    html += `<h3>🎩 دیلر</h3>`;
    html += `<div class="blackjack-cards">`;
    
    if (dealer.cards && dealer.cards.length > 0) {
        dealer.cards.forEach((card, i) => {
            // کارت دوم دیلر تا پایان مخفی است
            if (i === 1 && !dealerRevealed && phase === 'playing') {
                html += `<div class="card card-back">🂠</div>`;
            } else {
                html += renderCard(card);
            }
        });
    }
    html += `</div>`;
    
    const dealerScore = allFinished || dealerRevealed ? dealer.score : '?';
    html += `<div class="blackjack-score">جمع: ${dealerScore}</div>`;
    html += `</div>`;
    
    // ===== نمایش بازیکنان =====
    players.forEach((p, idx) => {
        const isCurrent = idx === turn && phase === 'playing';
        const isMe = p.id === myId;
        const showScore = allFinished || p.finished || p.bust;
        const status = p.bust ? '💥 بست' : (p.finished ? '✅ ایستاده' : '🔄 در حال بازی');
        
        html += `<div class="blackjack-player" style="${isCurrent ? 'border:2px solid #ffd700;' : ''}">`;
        html += `<h3>${p.name} ${isMe ? '👤' : ''} ${isCurrent ? '⭐ (نوبت شما)' : ''}</h3>`;
        html += `<div class="blackjack-cards">`;
        if (p.cards && p.cards.length > 0) {
            p.cards.forEach(card => {
                html += renderCard(card);
            });
        }
        html += `</div>`;
        html += `<div class="blackjack-score">جمع: ${showScore ? p.score : '??'}</div>`;
        html += `<div class="player-status">${status}</div>`;
        html += `</div>`;
    });
    
    // ===== دکمه‌های کنترل (فقط برای بازیکن فعلی) =====
    if (phase === 'playing' && !data.game_over) {
        const currentPlayer = players[turn];
        if (currentPlayer && currentPlayer.id === myId) {
            if (!currentPlayer.finished && !currentPlayer.bust) {
                html += `<div class="blackjack-controls">`;
                html += `<button class="btn-hit" onclick="blackjackHit()">🃏 کارت بگیر</button>`;
                html += `<button class="btn-stand" onclick="blackjackStand()">✋ بایست</button>`;
                html += `<button class="btn-view" onclick="blackjackView()">👀 کارتام رو ببین</button>`;
                html += `</div>`;
            } else {
                html += `<div style="text-align:center;padding:10px;color:#aaa;">⏳ منتظر پایان نوبت دیگران...</div>`;
            }
        } else {
            const currentName = players[turn]?.name || 'نفر بعدی';
            html += `<div style="text-align:center;padding:15px;color:#ffd700;font-size:16px;">👉 نوبت: ${currentName}</div>`;
        }
    }
    
    // ===== نتیجه بازی =====
    if (result) {
        html += `<div class="blackjack-result">`;
        if (result.winner) {
            html += `<span class="winner">🏆 برنده: ${result.winner} 🏆</span>`;
        } else if (result.draw) {
            html += `🤝 ${result.draw}`;
        } else if (result.dealer_winner) {
            html += `🎩 ${result.dealer_winner}`;
        } else {
            html += `🎩 دیلر برنده شد!`;
        }
        html += `</div>`;
    }
    
    html += `</div>`;
    container.innerHTML = html;
}

// ===================================================
//  رندر کارت
// ===================================================

function renderCard(card) {
    if (!card) return '';
    const isRed = card.suit === '♥' || card.suit === '♦';
    return `<div class="card ${isRed ? 'red' : 'black'}">${card.rank}${card.suit}</div>`;
}

// ===================================================
//  توابع کنترل بازی ۲۱
// ===================================================

function blackjackHit() {
    sendToBot({ action: 'hit', game: 'blackjack' });
}

function blackjackStand() {
    sendToBot({ action: 'stand', game: 'blackjack' });
}

function blackjackView() {
    sendToBot({ action: 'view', game: 'blackjack' });
}

// ===================================================
//  ===== بازی سنگ‌کاغذ‌قیچی =====
// ===================================================

function renderRPS(data) {
    const container = document.getElementById('game-content');
    const players = data.players || [];
    const myId = tg.initDataUnsafe?.user?.id || 0;
    const isMyTurn = data.turn === myId || !data.turn;
    const choices = data.choices || {};
    const score = data.score || {};
    
    let html = `<div style="padding:15px;">`;
    html += `<h3>🪨📄✂️ سنگ کاغذ قیچی</h3>`;
    
    // نمایش وضعیت
    if (data.round) {
        html += `<div style="background:#0f3460;padding:15px;border-radius:10px;margin:15px 0;">`;
        html += `<div style="display:flex;justify-content:space-around;">`;
        players.forEach(p => {
            const choice = choices[p.id];
            const choiceEmoji = choice ? getRPSEmoji(choice) : '❓';
            html += `<div style="text-align:center;">`;
            html += `<div style="font-size:32px;">${choiceEmoji}</div>`;
            html += `<div>${p.name}</div>`;
            html += `<div style="font-size:14px;color:#aaa;">امتیاز: ${score[p.id] || 0}</div>`;
            html += `</div>`;
        });
        html += `</div>`;
        html += `</div>`;
    }
    
    // دکمه‌های انتخاب
    if (isMyTurn && !data.game_over) {
        html += `<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:20px 0;">`;
        html += `<button onclick="rpsChoice('rock')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">🪨</button>`;
        html += `<button onclick="rpsChoice('paper')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">📄</button>`;
        html += `<button onclick="rpsChoice('scissors')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">✂️</button>`;
        html += `</div>`;
    } else if (!data.game_over) {
        html += `<div style="text-align:center;color:#aaa;padding:20px;">⏳ منتظر انتخاب حریف...</div>`;
    }
    
    // نتیجه
    if (data.result) {
        html += `<div style="background:#2d4059;padding:20px;border-radius:10px;text-align:center;margin-top:15px;">`;
        html += `<span style="font-size:20px;color:#f5a623;">${data.result}</span>`;
        html += `</div>`;
    }
    
    html += `</div>`;
    container.innerHTML = html;
}

function getRPSEmoji(choice) {
    const emojis = { 'rock': '🪨', 'paper': '📄', 'scissors': '✂️' };
    return emojis[choice] || '❓';
}

function rpsChoice(choice) {
    sendToBot({ action: 'choice', game: 'rps', choice: choice });
}

// ===================================================
//  ===== بازی دوز (XO) =====
// ===================================================

function renderXO(data) {
    const container = document.getElementById('game-content');
    const board = data.board || [];
    const turn = data.turn || '';
    const players = data.players || [];
    const myId = tg.initDataUnsafe?.user?.id || 0;
    const isMyTurn = turn === myId;
    const gameOver = data.game_over || false;
    const winner = data.winner || null;
    
    let html = `<div style="padding:15px;">`;
    html += `<h3>❌🟢 دوز</h3>`;
    
    // نمایش بازیکنان
    html += `<div style="display:flex;justify-content:space-around;margin:15px 0;background:#0f3460;padding:15px;border-radius:10px;">`;
    players.forEach(p => {
        const symbol = p.id === players[0]?.id ? '❌' : '🟢';
        html += `<div>${symbol} ${p.name}</div>`;
    });
    html += `</div>`;
    
    // صفحه بازی
    html += `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:300px;margin:0 auto;">`;
    for (let i = 0; i < 9; i++) {
        const cell = board[i] || '';
        const emoji = cell === 'X' ? '❌' : (cell === 'O' ? '🟢' : '・');
        const clickable = !cell && !gameOver && isMyTurn;
        html += `<div onclick="${clickable ? `xoMove(${i})` : ''}" style="
            background:${cell ? '#1a4f8a' : '#0f3460'};
            padding:20px;
            text-align:center;
            font-size:36px;
            border-radius:10px;
            cursor:${clickable ? 'pointer' : 'default'};
            min-height:70px;
            display:flex;
            align-items:center;
            justify-content:center;
            transition:all 0.2s;
        ">${emoji}</div>`;
    }
    html += `</div>`;
    
    // پیام نوبت
    if (!gameOver) {
        const turnName = players.find(p => p.id === turn)?.name || 'نفر بعدی';
        const isMe = turn === myId;
        html += `<div style="text-align:center;margin-top:15px;color:#ffd700;">`;
        html += isMe ? '⭐ نوبت شماست!' : `⏳ نوبت: ${turnName}`;
        html += `</div>`;
    }
    
    // نتیجه
    if (gameOver) {
        html += `<div style="background:#2d4059;padding:20px;border-radius:10px;text-align:center;margin-top:15px;">`;
        if (winner) {
            const winnerName = players.find(p => p.id === winner)?.name || 'برنده';
            html += `<span style="font-size:20px;color:#f5a623;">🏆 برنده: ${winnerName}</span>`;
        } else {
            html += `<span style="font-size:20px;color:#aaa;">🤝 مساوی شد!</span>`;
        }
        html += `</div>`;
    }
    
    html += `</div>`;
    container.innerHTML = html;
}

function xoMove(index) {
    sendToBot({ action: 'move', game: 'xo', index: index });
}

// ===================================================
//  ===== سایر بازی‌ها (ساده) =====
// ===================================================

function renderGolpoch(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🤲 گل یا پوچ</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderMorris(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🔄 دوز متحرک</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderHokm(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🃏 حکم</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderMafia(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🕵️ مافیا</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderQuiz(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🧠 کوییز</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderHangman(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🎯 دار بازی</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

function renderTournament(data) {
    const container = document.getElementById('game-content');
    container.innerHTML = `
        <div style="padding:20px;text-align:center;">
            <h3>🏆 تورنمنت</h3>
            <div style="background:#0f3460;padding:20px;border-radius:10px;margin:15px 0;">
                <pre style="text-align:right;font-size:14px;">${JSON.stringify(data, null, 2)}</pre>
            </div>
            <p style="color:#aaa;">در حال توسعه...</p>
        </div>
    `;
}

// ===================================================
//  راه‌اندازی اولیه
// ===================================================

// نمایش منو
showMenu();

// تنظیم دکمه بستن در تلگرام
tg.MainButton.text = 'بستن';
tg.MainButton.onClick(() => {
    tg.close();
});
tg.MainButton.show();

// دریافت پارامترهای URL برای شروع مستقیم بازی
const urlParams = new URLSearchParams(window.location.search);
const startGameParam = urlParams.get('start');
if (startGameParam) {
    setTimeout(() => startGame(startGameParam), 500);
}

// ===================================================
//  هندلر پیام‌های دریافتی از ربات (برای روش WebApp Data)
// ===================================================

// اگر ربات از طریق WebApp Data پاسخ می‌فرستد، این تابع صدا زده می‌شود
tg.onEvent('mainButtonClicked', () => {
    // دکمه اصلی کلیک شد
});

// ===================================================
//  نمایش اطلاعات کاربر در کنسول (برای دیباگ)
// ===================================================

console.log('Telegram User:', tg.initDataUnsafe?.user);
console.log('Chat ID:', tg.initDataUnsafe?.chat?.id);