import os
import re
import random
import asyncio
import logging
import sqlite3
import base64
import urllib.parse
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from openai import AsyncOpenAI
from aiohttp import web, ClientSession

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Расширенный словарь колоритных фраз
GYPSY_PHRASES = [
    "Та шоб я поховала своего мужа!",
    "Сыночек, поешь ты мои пятки!",
    "Прокляну, пропасть!",
    "Дабуле миленький...",
    "Хас ямарэ туфли!",
    "Тэпогодаю тукэ, пропасть?",
    "Минч!",
    "Хняс дро муй!",
    "Мамоновка твой дом!",
    "Тююю!",
    "Улюююю!",
    "Бещасный!",
    "Самый Крутой здесь - Назар с черемушек!",
    "Вы беспризоники!",
    "Хняв мэ тукэ пу шэро!",
    "Дайте ему Кар в студию!",
    "Чавалэ закэрэн у муй!",
    "Ой, ромалэ, шо делается!",
    "Шоб у тебя золото в медь превратилось!"
]

DB_FILE = "chat_phrases.db"

# --- СОСТОЯНИЯ ДЛЯ ДИАЛОГОВ (FSM) ---
class CourtFlow(StatesGroup):
    waiting_for_details = State()

class DreamFlow(StatesGroup):
    waiting_for_dream = State()

class PawnshopFlow(StatesGroup):
    waiting_for_item = State()

class RitualFlow(StatesGroup):
    waiting_for_egg = State()
    waiting_for_spit = State()

# --- БЕЗОПАСНАЯ БАЗА ДАННЫХ ---
def _init_db_sync():
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learned_phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE
            )
        """)
        conn.commit()
    finally:
        conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _save_phrase_sync(text: str):
    clean_text = text.strip()
    if 15 <= len(clean_text) <= 120 and "байзиха" not in clean_text.lower() and not clean_text.startswith("/"):
        try:
            conn = sqlite3.connect(DB_FILE, timeout=5.0)
            try:
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO learned_phrases (phrase) VALUES (?)", (clean_text,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logging.error(f"Ошибка сохранения фразы: {e}")

async def save_phrase(text: str):
    await asyncio.to_thread(_save_phrase_sync, text)

def _get_random_learned_phrase_sync():
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5.0)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT phrase FROM learned_phrases ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except Exception:
        return None

async def get_random_learned_phrase():
    return await asyncio.to_thread(_get_random_learned_phrase_sync)

# --- ПРОМПТЫ ДЛЯ НЕЙРОСЕТИ ---
SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха, старая цыганка с богатым жизненным опытом. Твой стиль — резкий, дерзкий, язвительный, но колоритный. Используй цыганские слова: чавалэ, ромалэ, ловэ, джюкэль, муй, шэро, гаджо.
"""

SYSTEM_PROMPT_COURT = "Ты 90-летняя цыганка Байзиха, вершишь суд. Рассуди спорщиков абсурдно, с юмором, назначь виноватому штраф в свою пользу (ловэ, кони). До 4 предложений."
SYSTEM_PROMPT_DREAM = "Ты цыганка Байзиха. Пользователь рассказывает сон. Растолкуй его абсурдно. Найди порчу и скажи, что для снятия нужно срочно отдать тебе ловэ. До 4 предложений."
SYSTEM_PROMPT_PAWNSHOP = """Ты 90-летняя цыганка Байзиха, держишь подпольный ломбард. Пользователь принес вещь на продажу. 
Жестко раскритикуй эту вещь (найди ржавчину, сглаз, блох, скажи что она ворованная у соседа). Предложи за неё сущие копейки, либо вообще потребуй доплатить тебе, чтобы ты согласилась её выкинуть на помойку! Используй цыганские словечки. Отвечай до 4 предложений."""

# --- МЕНЮ КОМАНД ---
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="menu", description="Узнать все способности Байзихи"),
        BotCommand(command="game", description="Сыграть в напёрстки"),
        BotCommand(command="ritual", description="Пройти ритуал снятия порчи"),
        BotCommand(command="pawnshop", description="Сдать вещь в цыганский ломбард"),
        BotCommand(command="court", description="Цыганский суд"),
        BotCommand(command="predict", description="Цыганское гадание"),
        BotCommand(command="dream", description="Цыганский сонник"),
        BotCommand(command="steal", description="Украсть ловэ"),
        BotCommand(command="curse", description="Навести сглаз"),
        BotCommand(command="narisui", description="Нарисовать картинку")
    ]
    await bot.set_my_commands(commands)

# --- ОТМЕНА ДЕЙСТВИЙ (Выход из состояний) ---
@dp.message(Command("cancel"), StateFilter("*"))
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply("Всё, забыли! Отменила, беспризорник.")

# Вспомогательная функция для обработки случайных команд во время диалога
async def check_interrupt(message: types.Message, state: FSMContext) -> bool:
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.reply("Тьфу, перебиваешь бабку! Ладно, забыли старое. Жми свою команду еще раз, гаджо!")
        return True
    return False

# Хэндлер /start и /menu
@dp.message(Command("start"))
@dp.message(Command("menu"))
async def show_features(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "👵 **Шо надо, беспризорники? Вот шо бабка Байзиха умеет:**\n\n"
        "🎮 **Напёрстки:** `/game` — сыграй с бабкой на ловэ, угадай где шарик!\n"
        "💎 **Ломбард:** `/pawnshop` — принеси мне вещь, а я скажу, сколько копеек она стоит.\n"
        "🥚 **Снять порчу:** `/ritual` — выкатаю сглаз яйцом (интерактивный квест).\n\n"
        "⚖️ **Суд:** `/court` — рассужу ваш спор по понятиям.\n"
        "🌙 **Сонник:** `/dream` — растолкую твой сон.\n"
        "🔮 **Гадание:** `/predict` — раскину картишки.\n"
        "💸 **Отжать ловэ:** `/steal` — обшарю карманы случайного гаджо.\n"
        "☠️ **Сглаз:** `/curse` — наведу цыганский сглаз.\n"
        "🎨 **Рисовать:** `/narisui [текст]` — нарисую картинку.\n"
        "💬 И просто пиши `байзиха` в тексте или кидай фото с этой подписью!"
    )
    await message.reply(text, parse_mode="Markdown")

# --- 🎮 1. ЦЫГАНСКИЕ НАПЁРСТКИ (КНОПКИ) ---
@dp.message(Command("game"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("наперстки"))
async def game_start(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🥃 Левый", callback_data="cup_1"),
            InlineKeyboardButton(text="🥃 Средний", callback_data="cup_2"),
            InlineKeyboardButton(text="🥃 Правый", callback_data="cup_3")
        ]
    ])
    await message.reply(
        "🎪 **Кручу-верчу, запутать хочу!**\n\n"
        "Подходи, гаджо, не стесняйся! Ставь свои ловэ! "
        "Угадаешь под каким напёрстком шарик — озолочу! Не угадаешь — останешься без штанов!\n\n"
        "Жми на кнопку, выбирай!", 
        reply_markup=markup
    )

@dp.callback_query(F.data.startswith("cup_"))
async def game_process(callback: CallbackQuery):
    win = random.random() < 0.1
    if win:
        text = "🤬 Тьфу, пропасть! Твоя взяла! Забирай свои копейки, глаза б мои тебя не видели! Хас ямарэ туфли!"
    else:
        phrases = [
            "Ахахаха! Шарик-то в рукаве был! Байзиха забирает твои денежки! 💸",
            "Тююю! Пусто! Оставляй куртку и иди домой пешком, беспризорник! 💸",
            "Проиграл, гаджо! А я говорила, не связывайся с бабкой! Гони ловэ! 💸"
        ]
        text = random.choice(phrases)

    await callback.message.edit_text(text)
    await callback.answer()

# --- 💎 2. ЦЫГАНСКИЙ ЛОМБАРД (FSM + ИИ) ---
@dp.message(Command("pawnshop"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("ломбард"))
async def pawnshop_start(message: types.Message, state: FSMContext):
    await message.reply(
        "💎 **Цыганский ломбард открыт!**\n\n"
        "Шо принёс, ромалэ? Пиши сюда, какую вещь хочешь мне продать. "
        "Только не подсовывай мусор, я глаз-алмаз имею!\n\n"
        "*(Напиши, что сдаёшь. Для отмены жми /cancel)*"
    )
    await state.set_state(PawnshopFlow.waiting_for_item)

@dp.message(PawnshopFlow.waiting_for_item)
async def pawnshop_process(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return

    wait_msg = await message.reply("🔎 Тааак, надеваю очки, дай пощупаю...")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_PAWNSHOP},
                {"role": "user", "content": f"Я хочу сдать в ломбард вот это: {message.text}"}
            ],
            temperature=0.8,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
        await wait_msg.edit_text(f"⚖️ **ОЦЕНКА БАЙЗИХИ:**\n\n{ai_reply}")
    except Exception:
        await wait_msg.edit_text("Тьфу, воняет от твоей вещи так, что аж хрустальный шар треснул! Забирай и уходи!")
    
    await state.clear()

# --- 🥚 3. РИТУАЛ СНЯТИЯ ПОРЧИ (ИНТЕРАКТИВНЫЙ КВЕСТ) ---
@dp.message(Command("ritual"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("ритуал"))
async def ritual_start(message: types.Message, state: FSMContext):
    await message.reply(
        "🥚 **Ой, чавалэ, вижу на тебе страшную порчу!** Венец безбрачия и проклятие пустого кошелька!\n\n"
        "Будем выкатывать яйцом! Быстро пришли мне сюда эмодзи яйца (🥚)!"
    )
    await state.set_state(RitualFlow.waiting_for_egg)

@dp.message(RitualFlow.waiting_for_egg)
async def ritual_egg_step(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    if "🥚" in message.text:
        await message.reply(
            "Так, хорошо! Катаю-катаю, всю хворь забираю...\n\n"
            "Теперь, шоб беда ушла, плюнь через левое плечо! Напиши мне прям словами: `Тьфу тьфу тьфу`"
        )
        await state.set_state(RitualFlow.waiting_for_spit)
    else:
        await message.reply("Какое же это яйцо?! Ты слепой, гаджо?! Шли 🥚, а то порча навсегда останется!")

@dp.message(RitualFlow.waiting_for_spit)
async def ritual_spit_step(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    text = message.text.lower()
    if "тьфу" in text or "тфу" in text:
        await message.reply(
            "✨ **Всё, порча снята!** Аура чистая, как слеза младенца!\n\n"
            "А теперь гони 5000 рублей за работу, беспризорник! Бабка бесплатно свою магию не тратит! 💸💸💸"
        )
        await state.clear()
    else:
        await message.reply("Не так плюешь! Надо писать `Тьфу тьфу тьфу`! Давай заново, пока демоны не сожрали!")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (СУД, СОН, ГАДАНИЕ И Т.Д.) ---
@dp.message(Command("court"))
async def court_start(message: types.Message, state: FSMContext):
    await message.reply("⚖️ Ой, ромалэ, суд идёт! Пиши кто с кем рамсит (имена) и из-за чего спор? (Для отмены /cancel)")
    await state.set_state(CourtFlow.waiting_for_details)

@dp.message(CourtFlow.waiting_for_details)
async def court_process(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    wait_msg = await message.reply("⏳ Слушаю вас, беспризоники...")
    try:
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT_COURT}, {"role": "user", "content": message.text}]
        )
        await wait_msg.edit_text(f"⚖️ **ВЕРДИКТ:**\n\n{res.choices[0].message.content.strip()}")
    except:
        await wait_msg.edit_text("Оба виноваты, расходимся!")
    await state.clear()

@dp.message(Command("dream"))
async def dream_start(message: types.Message, state: FSMContext):
    await message.reply("🌙 Рассказывай бабке свой сон во всех красках! (Для отмены /cancel)")
    await state.set_state(DreamFlow.waiting_for_dream)

@dp.message(DreamFlow.waiting_for_dream)
async def dream_process(message: types.Message, state: FSMContext):
    if await check_interrupt(message, state): return
    if not message.text: return
    
    wait_msg = await message.reply("🔮 Раскидываю карты на твой сон...")
    try:
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT_DREAM}, {"role": "user", "content": message.text}]
        )
        await wait_msg.edit_text(f"🔮 **ТОЛКОВАНИЕ:**\n\n{res.choices[0].message.content.strip()}")
    except:
        await wait_msg.edit_text("Точно к потере 100 рублей. Давай сюда!")
    await state.clear()

@dp.message(Command("narisui"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("нарисуй"))
async def generate_image_handler(message: types.Message):
    raw_text = message.text or ""
    clean_prompt = re.sub(r'(/narisui|байзиха|нарисуй|@\w+)', '', raw_text, flags=re.IGNORECASE).strip()
    if not clean_prompt:
        await message.reply("Шо тебе нарисовать, пропасть? Укажи предмет!")
        return
    encoded_prompt = urllib.parse.quote(clean_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    await message.reply_photo(photo=image_url, caption=f"Вот тебе твоя малярка: «{clean_prompt}»!")

@dp.message(Command("predict"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("погадай"))
async def predict_handler(message: types.Message):
    outcomes = [
        "Вижу... ждет тебя встреча с джюкэлем! Ловэ береги, утащат!",
        "На тебя наложена порча на понос! Давай 500 рублей — сниму!",
        "Дорога дальняя ждет тебя... на Мамоновку пешком!",
        "Казенный дом вижу! Или кредитку заблокируют, одно из двух."
    ]
    await message.reply(f"{random.choice(GYPSY_PHRASES)} {random.choice(outcomes)}")

@dp.message(Command("steal"))
@dp.message(F.text.lower().contains("байзиха") & (F.text.lower().contains("укради") | F.text.lower().contains("отжми")))
async def steal_handler(message: types.Message):
    items = ["500 рублей", "пачку сигарет", "золотой зуб", "магнитолу из жигулей", "права на кобылу"]
    target = message.from_user.first_name if message.from_user else "гаджо"
    await message.reply(f"Хе-хе! Байзиха вытащила у {target} {random.choice(items)}! Хас ямарэ туфли!")

@dp.message(Command("curse"))
@dp.message(F.text.lower().contains("байзиха") & F.text.lower().contains("прокляни"))
async def curse_handler(message: types.Message):
    curses = [
        "Шоб у тебя вайфай ловил только на кладбище!",
        "Шоб тебе зарплату фальшивыми ловэ выдали!",
        "Порча на перхоть и энурез! Тююю на тебя!"
    ]
    await message.reply(f"Прокляну, пропасть! {random.choice(curses)}")

# Безопасный анализ фото
@dp.message(F.photo & F.caption & F.caption.lower().contains("байзиха"))
async def photo_handler(message: types.Message):
    try:
        photo = message.photo[-1]
        file_bytes: BytesIO = await bot.download(photo)
        base64_image = base64.b64encode(file_bytes.getvalue()).decode('utf-8')
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [{"type": "text", "text": "Оцени это фото в стиле Байзихи:"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ],
            max_tokens=150
        )
        await message.reply(res.choices[0].message.content.strip())
    except:
        await message.reply("Очки свои дома забыла, ничего не вижу!")

# --- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ (Нейросеть) ---
@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    text_lower = message.text.lower()
    await save_phrase(message.text)

    if "байзиха" not in text_lower:
        return

    try:
        res = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message.text}],
            temperature=0.85,
            max_tokens=150
        )
        ai_reply = res.choices[0].message.content.strip()
    except:
        ai_reply = "Шо ты мне тут бубнишь, пропасть? Не слышу!"

    final_reply = f"{random.choice(GYPSY_PHRASES)} {ai_reply}" if random.random() < 0.6 else ai_reply
    if random.random() < 0.05:
        learned = await get_random_learned_phrase()
        if learned: final_reply += f" Как один тут ляпнул: «{learned}»!"

    await message.reply(final_reply)

# --- WEB СЕРВЕР И ПИНГ ДЛЯ RENDER ---
async def handle_ping(request):
    return web.Response(text="Бабка Байзиха бдит и ворует коней!")

async def self_ping():
    await asyncio.sleep(10)
    port = os.getenv("PORT", "8080")
    render_url = os.getenv("RENDER_EXTERNAL_URL", f"http://127.0.0.1:{port}")
    async with ClientSession() as session:
        while True:
            try:
                async with session.get(render_url) as resp: pass
            except: pass
            await asyncio.sleep(600)

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await set_bot_commands(bot)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    asyncio.create_task(self_ping())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
