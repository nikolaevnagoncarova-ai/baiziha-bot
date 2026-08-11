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
from aiogram.filters import Command
from aiogram.types import BotCommand
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
    "Чавалэ закэрэн у муй!"
]

DB_FILE = "chat_phrases.db"

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
        logging.error(f"Ошибка чтения из БД: {e}")
        return None

async def get_random_learned_phrase():
    return await asyncio.to_thread(_get_random_learned_phrase_sync)

SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха, старая цыганка с богатым жизненным опытом.
Твой стиль — резкий, дерзкий, язвительный, но колоритный.

ЦЫГАНСКИЙ ЯЗЫК И ЛЕКСИКА:
Ты свободно вплетаешь в речь цыганские слова:
- Приветствия/обращения: чавалэ, ромал, ромалэ, пшал, пэно, баро, фено, ром, гаджо.
- Словарь: ловэ (деньги), джюкэль (собака), муй (рот/лицо), шэро (голова), кхэр (дом), дром (дорога), хабэн (еда), со (что), джа (иди), яв (приходи).
- Выражения: Тэ авэн бахтало!, Тэ япэ тукэ!, Хас ямарэ туфли.

ПРАВИЛА ОТВЕТА:
1. Отвечай связно и по смыслу сообщений (1-3 предложения), свысока и подкалывая.
2. Не называй себя по имени Байзиха в самом ответе.
"""

# Меню команд в выпадающем списке Telegram (Только английские буквы для команд!)
async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Поздороваться с бабкой Байзихой"),
        BotCommand(command="menu", description="Узнать все способности Байзихи"),
        BotCommand(command="predict", description="Цыганское гадание"),
        BotCommand(command="steal", description="Украсть ловэ у участника"),
        BotCommand(command="court", description="Цыганский суд"),
        BotCommand(command="curse", description="Навести сглаз"),
        BotCommand(command="narisui", description="Нарисовать картинку по описанию")
    ]
    await bot.set_my_commands(commands)

# Хэндлер /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_name = message.from_user.first_name if message.from_user else "гаджо"
    phrase = random.choice(GYPSY_PHRASES)
    text = (
        f"👵 Тэ авэн бахтало, {user_name}! {phrase}\n\n"
        f"Шо припёрся к бабке Байзихе? Я хоть и старая, но все ваши хитрости вижу насквозь! "
        f"Ловэ береги, а то утащу! 😉\n\n"
        f"Шоб узнать, шо я умею — жми или пиши `/menu`!"
    )
    await message.reply(text)

# Хэндлер /menu (вместо /функционал)
@dp.message(Command("menu"))
async def show_features(message: types.Message):
    text = (
        "👵 **Шо надо, беспризорники? Вот шо бабка Байзиха умеет:**\n\n"
        "💬 **Общение:** Напиши слово `байзиха` в сообщении — и я тебе отвечу (иногда припомню ваши фразочки из чата!).\n"
        "🔮 **Гадание:** Напиши `байзиха погадай` или `/predict` — узнаешь свою судьбу!\n"
        "💸 **Отжать ловэ:** Напиши `байзиха укради` или `/steal` — обшарю карманы случайного гаджо в чате.\n"
        "⚖️ **Цыганский суд:** Напиши `байзиха рассуди` или `/court` — разрешу спор.\n"
        "☠️ **Сглаз:** Напиши `байзиха прокляни` или `/curse` — наведу цыганский сглаз.\n"
        "🎨 **Рисование:** Напиши `байзиха нарисуй [описание]` или `/narisui [описание]` — нарисую картинку.\n"
        "📸 **Оценка фото:** Отправь фото со словом `байзиха` — разгляжу вашу рожу и вынесу вердикт!\n"
    )
    await message.reply(text, parse_mode="Markdown")

# Генерация картинок
@dp.message(Command("narisui"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "нарисуй" in text.lower()))
async def generate_image_handler(message: types.Message):
    raw_text = message.text or ""
    clean_prompt = re.sub(r'(/narisui|байзиха|нарисуй|@\w+)', '', raw_text, flags=re.IGNORECASE).strip()
    
    if not clean_prompt:
        await message.reply("Шо тебе нарисовать, пропасть? Укажи хоть предмет!")
        return

    encoded_prompt = urllib.parse.quote(clean_prompt)
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    
    await message.reply_photo(photo=image_url, caption=f"Вот тебе твоя малярка, гаджо: «{clean_prompt}»!")

# Гадание
@dp.message(Command("predict"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "погадай" in text.lower()))
async def predict_handler(message: types.Message):
    outcomes = [
        "Вижу... ждет тебя встреча с джюкэлем у дома! Ловэ береги, а то утащат!",
        "Карты показывают: на тебя наложена порча на понос! Давай 100 рублей — сниму прямо сейчас!",
        "Дорога дальняя ждет тебя, чавалэ... на Мамоновку пешком!",
        "Будешь богатым, как баро, если работать начнешь, а не в чатах сидеть!",
        "Вижу твою судьбу: хас ямарэ туфли, вот шо тебя ждет!"
    ]
    reply = random.choice(outcomes)
    phrase = random.choice(GYPSY_PHRASES)
    await message.reply(f"{phrase} {reply}")

# Кража ловэ
@dp.message(Command("steal"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and ("укради" in text.lower() or "отжми" in text.lower())))
async def steal_handler(message: types.Message):
    stolen_items = [
        "500 рублей и серебряную ложку",
        "пачку сигарет и старый кнопочный телефон",
        "носки с дыркой и дырявый кошелек",
        "золотой зуб и 100 рублей на трамвай"
    ]
    target_user = message.from_user.first_name if message.from_user else "гаджо"
    item = random.choice(stolen_items)
    await message.reply(f"Хе-хе-хе! Байзиха ловко вытащила у {target_user} {item}! Хас ямарэ туфли!")

# Цыганский суд
@dp.message(Command("court"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "рассуди" in text.lower()))
async def court_handler(message: types.Message):
    judgments = [
        "Оба вы беспризоники! В суде Байзихи виноваты оба — с каждого по 200 рублей!",
        "Я посмотрела на вас: истец прав, а ответчику — проклятие на бессонницу!",
        "Чавалэ, закэрэн у муй! Какой суд, если вы даже делиться не умеете!"
    ]
    await message.reply(random.choice(judgments))

# Проклятия
@dp.message(Command("curse"))
@dp.message(F.text.func(lambda text: "байзиха" in text.lower() and "прокляни" in text.lower()))
async def curse_handler(message: types.Message):
    curses = [
        "Шоб у тебя мизинец на ноге об каждый угол спотыкался!",
        "Тэ япэ тукэ! Шоб тебе весь день в интернете только реклама вылезала!",
        "Проклинаю тебя на 3 дня без чая и хабэна!"
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
        logging.error(f"Ошибка при анализе фото: {e}")
        await message.reply("Шо это за размытая херня? Очки свои дома забыла, ничего не вижу!")

# Обработка всех обычных текстовых сообщений
@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message):
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
        logging.error(f"Ошибка при запросе к нейросети: {e}")
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

async def handle_ping(request):
    return web.Response(text="Бабка Байзиха бдит!")

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
