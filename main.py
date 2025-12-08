import logging

from fastapi import FastAPI, Request
from aiogram.types import Update

from bot import bot, dp
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Love Game Bot")


@app.on_event("startup")
async def on_startup() -> None:
    webhook_url = f"{settings.base_url}/webhook"
    await bot.set_webhook(webhook_url)
    await dp.emit_startup(bot)
    logger.info("Webhook установлен: %s", webhook_url)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await dp.emit_shutdown(bot)
    await bot.session.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"status": "accepted"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
