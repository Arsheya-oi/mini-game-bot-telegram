// ===================================================
//  اتصال به تلگرام WebApp
// ===================================================

const tg = window.Telegram.WebApp;
tg.expand();

// ===================================================
//  تنظیمات اولیه
// ===================================================

let currentGame = null;
let gameState = null;
let myId = tg.initDataUnsafe?.user?.id || 0;

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
//  ارسال به ربات و دریافت پاسخ
// ===================================================

function sendToBot(data) {
    const fullData = {
        ...data,
        chat_id: tg.initDataUnsafe?.chat?.id || 0,
        user: tg.initDataUnsafe?.user || {},
        init_data: tg.initData || ''
    };
    
    // ارسال داده به ربات
    tg.sendData(JSON.stringify(fullData));
    console.log('📤 ارسال به ربات:', fullData);
}

// ===================================================
//  دریافت پاسخ از ربات (از طریق WebApp)
// ===================================================

// این تابع توسط ربات صدا زده می‌شه وقتی داده‌ای می‌فرسته
// اما در حال حاضر ربات پاسخ رو به صورت پیام متنی برمی‌گردونه،
// بنابراین ما باید از یک روش جایگزین استفاده کنیم.

// در نسخه‌ی نهایی، ربات از طریق web_app_data پاسخ می‌فرسته
// و این تابع اون رو دریافت می‌کنه.

// برای تست، ما از یک تابع برای نمایش پاسخ‌های ربات استفاده می‌کنیم
// که توسط کاربر در چت با ربات دیده می‌شه.

// ===================================================
//  رندر بازی‌ها (دریافت از ربات)
// ===================================================

function renderGame(data) {
    const container = document.getElementById('game-content');
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
        default:
            container.innerHTML = `
                <div style="text-align:center;padding:40px;color:#aaa;">
                    <h3>${getGameTitle(gameType)}</h3>
                    <pre style="background:#0f3460;padding:20px;border-radius:10px;text-align:right;overflow:auto;max-height:400px;">${JSON.stringify(data, null, 2)}</pre>
                </div>
            `;
    }
}

// ===================================================
//  ===== بازی ۲۱ (بلک‌جک) =====
// ===================================================

function renderBlackjack(data) {
    const container = document.getElementById('game-content');
    
    const players = data.players || [];
    const dealer = data.dealer || { cards: [], score: '?' };
    const turn = data.turn_index || 0;
    const phase = data.phase || 'playing';
    const result = data.result || null;
    const allFinished = data.all_finished || false;
    const dealerRevealed = data.dealer_revealed || allFinished;
    
    let html = `<div class="blackjack-table">`;
    
    // دیلر
    html += `<div class="blackjack-dealer">`;
    html += `<h3>🎩 دیلر</h3>`;
    html += `<div class="blackjack-cards">`;
    if (dealer.cards) {
        dealer.cards.forEach((card, i) => {
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
    
    // بازیکنان
    players.forEach((p, idx) => {
        const isCurrent = idx === turn && phase === 'playing';
        const isMe = p.id === myId;
        const showScore = allFinished || p.finished || p.bust;
        const status = p.bust ? '💥 بست' : (p.finished ? '✅ ایستاده' : '🔄 در حال بازی');
        
        html += `<div class="blackjack-player" style="${isCurrent ? 'border:2px solid #ffd700;' : ''}">`;
        html += `<h3>${p.name} ${isMe ? '👤' : ''} ${isCurrent ? '⭐ (نوبت شما)' : ''}</h3>`;
        html += `<div class="blackjack-cards">`;
        if (p.cards) {
            p.cards.forEach(card => {
                html += renderCard(card);
            });
        }
        html += `</div>`;
        html += `<div class="blackjack-score">جمع: ${showScore ? p.score : '??'}</div>`;
        html += `<div class="player-status">${status}</div>`;
        html += `</div>`;
    });
    
    // دکمه‌های کنترل
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
    
    // نتیجه
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
    const choices = data.choices || {};
    const score = data.score || {};
    const gameOver = data.game_over || false;
    const result = data.result || null;
    
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
    if (!gameOver && !data.my_choice) {
        html += `<div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:20px 0;">`;
        html += `<button onclick="rpsChoice('rock')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">🪨</button>`;
        html += `<button onclick="rpsChoice('paper')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">📄</button>`;
        html += `<button onclick="rpsChoice('scissors')" style="font-size:24px;padding:15px 25px;border:none;border-radius:12px;background:#0f3460;color:#eee;cursor:pointer;">✂️</button>`;
        html += `</div>`;
    } else if (!gameOver) {
        html += `<div style="text-align:center;color:#aaa;padding:20px;">⏳ منتظر انتخاب حریف...</div>`;
    }
    
    // نتیجه
    if (result) {
        html += `<div style="background:#2d4059;padding:20px;border-radius:10px;text-align:center;margin-top:15px;">`;
        html += `<span style="font-size:20px;color:#f5a623;">${result}</span>`;
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
//  ===== دوز =====
// ===================================================

function renderXO(data) {
    const container = document.getElementById('game-content');
    const board = data.board || [];
    const turn = data.turn || '';
    const players = data.players || [];
    const gameOver = data.game_over || false;
    const winner = data.winner || null;
    const isMyTurn = turn === myId;
    
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
        html += `<div style="text-align:center;margin-top:15px;color:#ffd700;">`;
        html += isMyTurn ? '⭐ نوبت شماست!' : `⏳ نوبت: ${turnName}`;
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
//  راه‌اندازی اولیه
// ===================================================

// گوش دادن به پیام‌های دریافتی از ربات (از طریق WebApp)
tg.onEvent('web_app_data', (data) => {
    console.log('📩 دریافت از ربات:', data);
    try {
        const parsed = typeof data === 'string' ? JSON.parse(data) : data;
        renderGame(parsed);
    } catch (e) {
        console.log('خطا در پردازش پاسخ ربات:', e);
    }
});

showMenu();

tg.MainButton.text = 'بستن';
tg.MainButton.onClick(() => {
    tg.close();
});
tg.MainButton.show();

console.log('✅ Mini App آماده است!');
console.log('👤 کاربر:', tg.initDataUnsafe?.user);