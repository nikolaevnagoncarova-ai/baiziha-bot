import os
import random
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from openai import AsyncOpenAI
from aiohttp import web, ClientSession

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключаемся к OpenRouter
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
    "Минч!"
]

SYSTEM_PROMPT = """
Ты — 90-летняя бабка Байзиха. 
Твой стиль — резкий, дерзкий, язвительный, унижающий собеседника, но при этом колоритный и цыганский.
Ты отвечаешь строго по смыслу того, что написал человек, но обязательно ставишь его на место и понукаешь.

Важные правила:
1. Пиши от лица старой 90-летней бабки-цыганки.
2. Твой ответ должен быть связным и отвечать на сообщение пользователя.
3. Отвечай свысока, с пренебрежением и унижением к собеседнику.
4. Ответ не должен быть слишком длинным (1-3 предложения).
"""

@dp.message(F.text)
async def handle_baizikha_messages(message: types.Message):
    if not message.text:
        return

    text_lower = message.text.lower()
    if "байзиха" not in text_lower:
        return

    try:
        # Бесплатная и быстрая модель Gemini
        response = await client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            temperature=0.8,
            max_tokens=150
        )
        ai_reply = response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"Ошибка при запросе к нейросети: {e}")
        ai_reply = "Шо ты мне тут бубнишь, пропасть? Не слышу я ничего, старая стала!"

    if random.random() < 0.7:
        random_phrase = random.choice(GYPSY_PHRASES)
        if random.choice([True, False]):
            final_reply = f"{random_phrase} {ai_reply}"
        else:
            final_reply = f"{ai_reply} {random_phrase}"
    else:
        final_reply = ai_reply

    await message.reply(final_reply)

async def handle_ping(request):
    return web.Response(text="Бабка Байзиха бдит!")

async def self_ping():
    await asyncio.sleep(10)
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        return

    async with ClientSession() as session:
        while True:
            try:
                async with session.get(render_url) as resp:
                    pass
            except Exception:
                pass
            await asyncio.sleep(600)

async def main():
    logging.basicConfig(level=logging.INFO)

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
