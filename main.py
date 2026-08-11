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
from aiogram.types import BotCommand
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
    "Шоб у тебя золото в медь превратилось!",
    "Я тебе сейчас ромашку в ухо вставлю, гаджо!",
    "Клянусь своей старой юбкой!",
    "Совэс, как мерин немытый!"
]

DB_FILE = "chat_phrases.db"

# --- СОСТОЯНИЯ ДЛЯ ДИАЛОГОВ (FSM) ---
class CourtFlow(StatesGroup):
    waiting_for_details = State()

class DreamFlow(StatesGroup):
    waiting_for_dream = State()

# --- БАЗА ДАННЫХ ФРАЗ ---
def _init_db_sync():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learned_phrases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phrase TEXT UNIQUE
        )
    """)
    conn.commit()
    conn.close()

async def init_db():
    await asyncio.to_thread(_init_db_sync)

def _save_phrase_sync(text: str):
    clean_text = text.strip()
    if 15 <= len(clean_text) <= 120 and "байзиха" not in clean_text.lower() and not clean_text.startswith("/"):
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO learned_phrases (phrase) VALUES (?)", (clean_text,))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Ошибка сохранения фразы: {e}")

async def save_phrase(text: str):
    await asyncio.to_thread(_save_phrase_sync, text)

def _get_random_learned_phrase_sync():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT phrase FROM learned_phrases ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        return None

async def get_random_learned_phrase():
    return await asyncio.to_thread(_get_random_learned_phrase_sync)

# --- ПРОМПТЫ ДЛЯ НЕЙРОСЕТИ ---
SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха, старая цыганка с богатым жизненным опытом.
Твой стиль — резкий, дерзкий, язвительный, но колоритный.
Используй цыганские слова: чавалэ, ромалэ, ловэ, джюкэль, муй, шэро, гаджо.
Отвечай связно (1-3 предложения), свысока и подкалывая. Не называй себя по имени.
"""

SYSTEM_PROMPT_COURT = """
Ты — 90-летняя бабка Байзиха, старая цыганка. Сейчас ты вершишь Высший Цыганский суд. 
Пользователь рассказал тебе суть спора. Твоя задача — рассудить спорщиков жестко, абсурдно, с юмором.
Обязательно назначь виноватому штраф и забери его себе (ловэ, коней, зубы). Используй цыганские слова!
Отвечай как судья-цыганка, не больше 4 предложений.
"""

SYSTEM_PROMPT_DREAM = """
Ты — 90-летняя бабка Байзиха. Пользователь рассказывает тебе свой сон.
Растолкуй его абсолютно абсурдно и смешно. Найди во сне знак, что на человеке страшный сглаз или порча, 
и скажи, что для снятия ему нужно срочно отдать тебе свои ловэ (деньги). Используй цыганские словечки.
Отвечай коротко (до 3-4 предложений).
"""

# --- МЕНЮ КОМАНД ---
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Поздороваться с бабкой Байзихой"),
        BotCommand(command="menu", description="Узнать все способности Байзихи"),
        BotCommand(command="predict", description="Цыганское гадание"),
        BotCommand(command="steal", description="Украсть ловэ у участника"),
        BotCommand(command="court", description="Цыганский суд (с анализом)"),
        BotCommand(command="dream", description="Цыганский сонник"),
        BotCommand(command="curse", description="Навести сглаз"),
        BotCommand(command="narisui", description="Нарисовать картинку по описанию")
    ]
    await bot.set_my_commands(commands)

# --- ОТМЕНА ДЕЙСТВИЙ (Выход из состояний) ---
@dp.message(Command("cancel"), StateFilter("*"))
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.reply("Всё, забыли! Отменила, беспризорник.")

# Хэндлер /start
@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name if message.from_user else "гаджо"
    phrase = random.choice(GYPSY_PHRASES)
    text = (
        f"👵 Тэ авэн бахтало, {user_name}! {phrase}\n\n"
        f"Шо припёрся к бабке Байзихе? Я хоть и старая, но все ваши хитрости вижу насквозь! "
        f"Ловэ береги, а то утащу! 😉\n\n"
        f"Шоб узнать, шо я умею — жми или пиши `/menu`!"
    )
    await message.reply(text)

# Хэндлер /menu
@dp.message(Command("menu"))
async def show_features(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "👵 **Шо надо, беспризорники? Вот шо бабка Байзиха умеет:**\n\n"
        "💬 **Общение:** Просто напиши `байзиха` в сообщении.\n"
        "🔮 **Гадание:** `/predict` — узнаешь свою судьбу!\n"
        "💸 **Отжать ловэ:** `/steal` — обшарю карманы случайного гаджо в чате.\n"
        "⚖️ **Цыганский суд:** `/court` — расскажи кто с кем спорит, и я рассужу по понятиям!\n"
        "🌙 **Сонник:** `/dream` — растолкую твой сон и найду порчу.\n"
        "☠️ **Сглаз:** `/curse` — наведу цыганский сглаз.\n"
        "🎨 **Рисование:** `/narisui [описание]` — нарисую картинку.\n"
        "📸 **Оценка фото:** Отправь фото со словом `байзиха`.\n"
    )
    await message.reply(text, parse_mode="Markdown")

# --- ⚖️ ЦЫГАНСКИЙ СУД (С ИСПОЛЬЗОВАНИЕМ FSM) ---
@dp.message(Command("court"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "рассуди" in text.lower()))
async def court_start(message: types.Message, state: FSMContext):
    await message.reply(
        "⚖️ Ой, ромалэ, суд идёт! \n\n"
        "Пиши сюда: кто с кем рамсит (назови имена или юзернеймы) и из-за чего сыр-бор? "
        "А бабка почитает и вынесет вердикт!\n\n"
        "*(Если передумал судиться — жми /cancel)*"
    )
    await state.set_state(CourtFlow.waiting_for_details)

@dp.message(CourtFlow.waiting_for_details)
async def court_process(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): # Если юзер ввел другую команду - игнорируем суд
        await state.clear()
        return

    wait_msg = await message.reply("⏳ Тааак, надеваю очки, слушаю вас, беспризоники...")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_COURT},
                {"role": "user", "content": f"Вот детали спора: {message.text}"}
            ],
            temperature=0.8,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
        await wait_msg.edit_text(f"⚖️ **ВЕРДИКТ БАЙЗИХИ:**\n\n{ai_reply}")
    except Exception as e:
        logging.error(f"Ошибка в суде: {e}")
        await wait_msg.edit_text("Тьфу, пропасть! Шар хрустальный запотел. Оба виноваты, расходимся!")
    
    await state.clear() # Завершаем суд

# --- 🌙 ЦЫГАНСКИЙ СОННИК (С ИСПОЛЬЗОВАНИЕМ FSM) ---
@dp.message(Command("dream"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "сон" in text.lower()))
async def dream_start(message: types.Message, state: FSMContext):
    await message.reply(
        "🌙 Шо тебе там привиделось, чавалэ? Рассказывай бабке свой сон во всех красках, "
        "а я растолкую, к деньгам это или порча на тебе лежит!\n\n"
        "*(Жду твой сон. Для отмены жми /cancel)*"
    )
    await state.set_state(DreamFlow.waiting_for_dream)

@dp.message(DreamFlow.waiting_for_dream)
async def dream_process(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        await state.clear()
        return

    wait_msg = await message.reply("🔮 Раскидываю карты на твой сон...")
    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_DREAM},
                {"role": "user", "content": f"Мне приснилось вот что: {message.text}"}
            ],
            temperature=0.9,
            max_tokens=250
        )
        ai_reply = response.choices[0].message.content.strip()
        await wait_msg.edit_text(f"🔮 **ТОЛКОВАНИЕ ОТ БАЙЗИХИ:**\n\n{ai_reply}")
    except Exception as e:
        await wait_msg.edit_text("Тьфу, забыла как толковать! Но точно к потере 100 рублей. Давай сюда!")
    
    await state.clear()

# --- ПРОСТЫЕ ФУНКЦИИ (ГЕНЕРАЦИЯ, КРАЖА, СГЛАЗ) ---

@dp.message(Command("narisui"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "нарисуй" in text.lower()))
async def generate_image_handler(message: types.Message):
    raw_text = message.text or ""
    clean_prompt = re.sub(r'(/narisui|байзиха|нарисуй|@\w+)', '', raw_text, flags=re.IGNORECASE).strip()
    if not clean_prompt:
        await message.reply("Шо тебе нарисовать, пропасть? Укажи предмет, а то кисточку сломаю!")
        return
    encoded_prompt = urllib.parse.quote(clean_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    await message.reply_photo(photo=image_url, caption=f"Вот тебе твоя малярка, гаджо: «{clean_prompt}»!")

@dp.message(Command("predict"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "погадай" in text.lower()))
async def predict_handler(message: types.Message):
    outcomes = [
        "Вижу... ждет тебя встреча с джюкэлем у дома! Ловэ береги, а то утащат!",
        "Карты показывают: на тебя наложена порча на понос! Давай 500 рублей — сниму прямо сейчас!",
        "Дорога дальняя ждет тебя, чавалэ... на Мамоновку пешком!",
        "Будешь богатым, как баро! Но только если мне коня купишь.",
        "Вижу твою судьбу: хас ямарэ туфли, вот шо тебя ждет в эту пятницу!",
        "Казенный дом вижу! Или кредитку заблокируют, одно из двух."
    ]
    reply = random.choice(outcomes)
    phrase = random.choice(GYPSY_PHRASES)
    await message.reply(f"{phrase} {reply}")

@dp.message(Command("steal"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and ("укради" in text.lower() or "отжми" in text.lower())))
async def steal_handler(message: types.Message):
    stolen_items = [
        "500 рублей и серебряную ложку",
        "пачку сигарет и старый кнопочный телефон",
        "носки с дыркой и дырявый кошелек",
        "золотой зуб и 100 рублей на трамвай",
        "магнитолу из жигулей",
        "медный таз и алюминиевую кружку",
        "права на вождение кобылы"
    ]
    target_user = message.from_user.first_name if message.from_user else "гаджо"
    item = random.choice(stolen_items)
    await message.reply(f"Хе-хе-хе! Байзиха ловко обшарила карманы и вытащила у {target_user} {item}! Хас ямарэ туфли!")

@dp.message(Command("curse"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "прокляни" in text.lower()))
async def curse_handler(message: types.Message):
    curses = [
        "Шоб у тебя мизинец на ноге об каждый угол спотыкался!",
        "Тэ япэ тукэ! Шоб тебе весь день в интернете только реклама кашперовского вылезала!",
        "Проклинаю тебя на 3 дня без чая и хабэна!",
        "Шоб у тебя вайфай ловил только на кладбище!",
        "Шоб тебе зарплату фальшивыми ловэ выдали!",
        "Порча на перхоть и энурез! Тююю на тебя!",
        "Шоб твоя машина превратилась в тыкву, а лошадь сдохла!"
    ]
    await message.reply(f"Прокляну, пропасть! {random.choice(curses)}")

# Безопасный анализ фото
@dp.message(F.photo & F.caption & F.caption.func(lambda cap: "байзиха" in cap.lower()))
async def photo_handler(message: types.Message):
    try:
        photo = message.photo[-1]
        file_bytes: BytesIO = await bot.download(photo)
        base64_image = base64.b64encode(file_bytes.getvalue()).decode('utf-8')

        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Оцени это фото с позиции 90-летней язвительной цыганки Байзихи:"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=150
        )
        await message.reply(response.choices[0].message.content.strip())
    except Exception as e:
        await message.reply("Шо это за размытая херня? Очки свои дома забыла, ничего не вижу!")

# --- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ ---
@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message, state: FSMContext):
    # Если юзер находится в состоянии суда или сна, игнорируем его тут
    current_state = await state.get_state()
    if current_state is not None:
        return

    if not message.text:
        return

    text_lower = message.text.lower()
    await save_phrase(message.text)

    if "байзиха" not in text_lower:
        return

    try:
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            temperature=0.85,
            max_tokens=150
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        ai_reply = "Шо ты мне тут бубнишь, пропасть? Не слышу я ничего, старая стала!"

    if random.random() < 0.8:
        random_phrase = random.choice(GYPSY_PHRASES)
        if random.choice([True, False]):
            final_reply = f"{random_phrase} {ai_reply}"
        else:
            final_reply = f"{ai_reply} {random_phrase}"
    else:
        final_reply = ai_reply

    if random.random() < 0.05:
        learned_phrase = await get_random_learned_phrase()
        if learned_phrase:
            final_reply += f" Как один тут ляпнул: «{learned_phrase}»!"

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
                async with session.get(render_url) as resp:
                    pass
            except Exception as e:
                logging.debug(f"Пинг не прошёл: {e}")
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
