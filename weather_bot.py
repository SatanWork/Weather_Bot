import os
import time
import logging
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токены из переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")

if not TELEGRAM_TOKEN or not WEATHER_API_KEY:
    logger.error("Необходимо установить переменные окружения TELEGRAM_TOKEN и WEATHER_API_KEY")
    exit(1)

# Настройки кэширования (10 минут)
CACHE_TTL = 600
weather_cache = {}  # {location.lower(): (timestamp, current_data, forecast_data)}

def get_weather(location: str):
    """
    Получает данные о погоде по названию или координатам.
    Если строка содержит запятую, пытаемся распарсить lat, lon.
    Иначе – ищем по названию населённого пункта.
    """
    now = time.time()
    key = location.lower()

    # Проверяем кэш
    if key in weather_cache:
        timestamp, cached_current, cached_forecast = weather_cache[key]
        if now - timestamp < CACHE_TTL:
            logger.info(f"Используем кэш для: {location}")
            return cached_current, cached_forecast

    # Формируем URL для запроса к API OpenWeatherMap
    if ',' in location:
        parts = location.split(',')
        try:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            url_current = (
                f"http://api.openweathermap.org/data/2.5/weather?"
                f"lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            )
            url_forecast = (
                f"http://api.openweathermap.org/data/2.5/forecast?"
                f"lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            )
        except ValueError:
            # Если координаты не распарсились, пробуем как название
            url_current = (
                f"http://api.openweathermap.org/data/2.5/weather?"
                f"q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            )
            url_forecast = (
                f"http://api.openweathermap.org/data/2.5/forecast?"
                f"q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
            )
    else:
        url_current = (
            f"http://api.openweathermap.org/data/2.5/weather?"
            f"q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        )
        url_forecast = (
            f"http://api.openweathermap.org/data/2.5/forecast?"
            f"q={location}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        )

    # Запрос текущей погоды
    response_current = requests.get(url_current)
    if response_current.status_code != 200:
        return None, None
    current_data = response_current.json()
    if current_data.get("cod") != 200:
        return None, None

    # Запрос прогноза
    response_forecast = requests.get(url_forecast)
    forecast_data = None
    if response_forecast.status_code == 200:
        forecast_data = response_forecast.json()

    # Сохраняем в кэш
    weather_cache[key] = (now, current_data, forecast_data)
    return current_data, forecast_data

def generate_weather_image(weather: dict, forecast: dict, location: str):
    """
    Генерирует картинку с информацией о погоде:
      - Выбирает фоновое изображение в зависимости от текущей погоды.
      - Накладывает текст: (город/координаты, температура, ветер, краткий прогноз).
    """
    main_weather = weather["weather"][0]["main"]  # Clear, Rain, Snow, Clouds и т.д.
    description = weather["weather"][0]["description"].capitalize()
    temp = weather["main"]["temp"]
    wind_speed = weather["wind"]["speed"]

    # Определяем фон
    if main_weather == "Clear":
        bg_path = "assets/sunny.png"
    elif main_weather == "Rain":
        bg_path = "assets/rain.png"
    elif main_weather == "Snow":
        bg_path = "assets/snow.png"
    elif main_weather == "Clouds":
        bg_path = "assets/cloudy.png"
    else:
        bg_path = "assets/default.png"  # если нет, создадим серый фон

    # Загружаем фоновое изображение
    try:
        bg = Image.open(bg_path).convert("RGBA")
    except IOError:
        bg = Image.new("RGBA", (800, 400), (200, 200, 200, 255))

    draw = ImageDraw.Draw(bg)

    # Шрифт
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except IOError:
        font = ImageFont.load_default()

    # Текст о текущей погоде
    weather_text = (
        f"{location}\n"
        f"Погода: {description}\n"
        f"Температура: {temp:.1f}°C\n"
        f"Ветер: {wind_speed:.1f} м/с"
    )
    draw.multiline_text((50, 50), weather_text, fill="black", font=font, spacing=8)

    # Прогноз
    if forecast and "list" in forecast and len(forecast["list"]) > 0:
        next_forecast = forecast["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_desc = next_forecast["weather"][0]["description"].capitalize()

        if forecast_weather != main_weather:
            if forecast_weather == "Rain":
                forecast_message = "Прогноз: дождь. Не забудьте взять зонт!"
            else:
                forecast_message = f"Прогноз: {forecast_desc}"
        else:
            forecast_message = "Погода не изменится."

        draw.text((50, 200), forecast_message, fill="black", font=font)

    # Сохраняем картинку в BytesIO
    img_byte_arr = BytesIO()
    bg.convert("RGB").save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start
    """
    await update.message.reply_text(
        "Привет! Отправь название населённого пункта или координаты в формате 'широта, долгота', чтобы узнать погоду."
    )

async def weather_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений.
    Проверяем, введены ли координаты или название.
    Получаем данные о погоде, формируем картинку и отправляем пользователю.
    """
    location = update.message.text.strip()
    logger.info(f"Запрос для: {location}")

    current_data, forecast_data = get_weather(location)
    if current_data is None:
        await update.message.reply_text(
            "Проверьте правильность ввода. Используйте формат 'Город' или 'широта, долгота'."
        )
        return

    # Генерируем картинку
    image_bytes = generate_weather_image(current_data, forecast_data, location)

    # Формируем подпись к картинке (caption)
    description = current_data["weather"][0]["description"].capitalize()
    temp = current_data["main"]["temp"]
    wind_speed = current_data["wind"]["speed"]

    caption = (
        f"{location}\n"
        f"Погода: {description}\n"
        f"Температура: {temp:.1f}°C\n"
        f"Ветер: {wind_speed:.1f} м/с"
    )

    # Прогноз в подписи
    if forecast_data and "list" in forecast_data and len(forecast_data["list"]) > 0:
        next_forecast = forecast_data["list"][0]
        forecast_weather = next_forecast["weather"][0]["main"]
        forecast_desc = next_forecast["weather"][0]["description"].capitalize()

        if forecast_weather != current_data["weather"][0]["main"]:
            if forecast_weather == "Rain":
                caption += "\nПрогноз: дождь. Не забудьте взять зонт!"
            else:
                caption += f"\nПрогноз: {forecast_desc}"
        else:
            caption += "\nПогода не изменится."

    # Отправляем сообщение с фотографией
    await update.message.reply_photo(photo=image_bytes, caption=caption)

def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, weather_handler))

    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
