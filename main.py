import os
import random
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types, F
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

# Базовый список цыганских коронных фраз
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

# Инициализация базы данных для запоминания фраз из чата
DB_FILE = "chat_phrases.db"

def init_db():
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

def save_phrase(text: str):
    """Сохраняет интересную фразу из чата в базу данных."""
    clean_text = text.strip()
    # Сохраняем только фразы средней длины, без упоминания бота
    if 15 <= len(clean_text) <= 120 and "байзиха" not in clean_text.lower():
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO learned_phrases (phrase) VALUES (?)", (clean_text,))
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Ошибка сохранения фразы: {e}")

def get_random_learned_phrase():
    """Получает случайную запомненную фразу из базы данных."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT phrase FROM learned_phrases ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logging.error(f"Ошибка чтения фразы из БД: {e}")
        return None

SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха, старая цыганка с богатым жизненным опытом.
Твой стиль — резкий, дерзкий, язвительный, но колоритный. 

ОБУЧЕНИЕ ЦЫГАНСКОМУ ЯЗЫКУ И ЛЕКСИКЕ:
Ты прекрасно знаешь цыганский язык (романо чиб) и постоянно употребляешь цыганские слова, ругательства и выражения:
- Приветствия/обращения: чавалэ (парни/ребята), ромал и ромалэ (цыгане), пшал (брат), пэно (сестра), баро (главный/большой), фено (красивый), ром (цыган), гаджо (нецыган/чужак).
- Словарный запас: ловэ (деньги), джюкэль (собака), муй (рот/лицо), шэро (голова), кхэр (дом), дром (дорога), хабэн (еда), со (что), джа (иди), яв (приходи).
- Пожелания и проклятия: Тэ авэн бахтало! (Будь счастлив!), Тэ япэ тукэ! (Чтоб тебе!), Хас ямарэ туфли (Съешь наши туфли).

ПРАВИЛА ОТВЕТА:
1. Отвечай связно и по смыслу сообщения пользователя (1-3 предложения), но свысока и язвительно.
2. Вплетай в текст цыганские слова, присказки и выражения naturally.
3. Не называй себя по имени Байзиха в самом ответе.
"""

@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message):
    if not message.text:
        return

    text_lower = message.text.lower()
    
    # 1. Запоминаем фразы из всех входящих сообщений чата
    save_phrase(message.text)

    # 2. Реагируем только на сообщения с именем "байзиха"
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

    # 3. Добавляем фирменную цыганскую фразу с вероятностью 80%
    if random.random() < 0.8:
        random_phrase = random.choice(GYPSY_PHRASES)
        if random.choice([True, False]):
            final_reply = f"{random_phrase} {ai_reply}"
        else:
            final_reply = f"{ai_reply} {random_phrase}"
    else:
        final_reply = ai_reply

    # 4. Очень редко (около 5% случаев) приплетаем запомненную фразу из чата
    if random.random() < 0.05:
        learned_phrase = get_random_learned_phrase()
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
    init_db()  # Создаем таблицу в БД при запуске

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
