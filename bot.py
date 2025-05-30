import os
import time
import re
import requests
import logging
import sys
import tempfile
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Чтение учётных данных из окружения
EMAIL = os.environ.get("OK_EMAIL")
PASSWORD = os.environ.get("OK_PASSWORD")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

if not all([EMAIL, PASSWORD, TELEGRAM_TOKEN, TELEGRAM_USER_ID]):
    print("❌ Задайте OK_EMAIL, OK_PASSWORD, TELEGRAM_BOT_TOKEN и TELEGRAM_USER_ID.")
    sys.exit(1)

# Логгер: консоль + Telegram
class TelegramHandler(logging.Handler):
    def __init__(self, token, chat_id):
        super().__init__()
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
    def emit(self, record):
        try:
            requests.post(self.api_url, data={"chat_id": self.chat_id, "text": self.format(record)})
        except:
            pass

logger = logging.getLogger("okru_bot")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(fmt)
logger.addHandler(ch)
tg = TelegramHandler(TELEGRAM_TOKEN, TELEGRAM_USER_ID)
tg.setFormatter(fmt)
logger.addHandler(tg)

# Инициализация WebDriver
def init_driver():
    opts = uc.ChromeOptions()
    
    # Используем headless, но не new (для совместимости с Xvfb)
    if os.getenv('DISPLAY'):
        logger.info("🖥️ Обнаружен DISPLAY, работаем с Xvfb")
    else:
        opts.add_argument('--headless=new')
        logger.info("🔇 Работаем в headless режиме")
    
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--disable-extensions')
    opts.add_argument('--disable-plugins')
    opts.add_argument('--disable-web-security')
    opts.add_argument('--allow-running-insecure-content')
    opts.add_argument('--disable-popup-blocking')
    opts.add_argument('--disable-notifications')
    
    # Настройки для загрузки файлов
    temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
    prefs = {
        "download.default_directory": temp_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_settings.popups": 0,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    opts.add_experimental_option("prefs", prefs)
    
    version_main = int(os.getenv("CHROME_MAJOR", "136"))
    
    try:
        driver = uc.Chrome(options=opts, version_main=version_main)
        logger.info(f"✅ Chrome инициализирован с версией {version_main}")
        return driver
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации драйвера с версией {version_main}: {e}")
        try:
            driver = uc.Chrome(options=opts)
            logger.info("✅ Chrome инициализирован без указания версии")
            return driver
        except Exception as e2:
            logger.error(f"❌ Критическая ошибка инициализации драйвера: {e2}")
            raise

driver = init_driver()
wait = WebDriverWait(driver, 20)

# Функция для создания скриншота при ошибках
def take_screenshot(name="error"):
    try:
        timestamp = int(time.time())
        filename = f"{name}_{timestamp}.png"
        driver.save_screenshot(filename)
        logger.info(f"📸 Скриншот сохранен: {filename}")
        return filename
    except Exception as e:
        logger.error(f"❌ Не удалось создать скриншот: {e}")
        return None

# Отправка ссылки на пост в Telegram
def send_post_link_to_telegram(post_link):
    try:
        full_url = f"https://ok.ru{post_link}" if post_link.startswith('/') else post_link
        message = f"✅ Пост опубликован: {full_url}"
        api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(api_url, data={
            "chat_id": TELEGRAM_USER_ID, 
            "text": message
        })
        if response.json().get('ok'):
            logger.info(f"📤 Ссылка отправлена в Telegram: {full_url}")
        else:
            logger.error(f"❌ Ошибка отправки в Telegram: {response.text}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ссылки в Telegram: {e}")

# Поиск ссылки на опубликованный пост
def wait_for_post_link(timeout=30):
    try:
        logger.info("⏳ Ищу ссылку на опубликованный пост...")
        tip_selectors = [
            "#hook_Block_TipBlock .js-tip-block-url",
            ".tip-block_lk a.js-tip-block-url",
            ".action-tip a[href*='/topic/']",
            ".toast a[href*='/topic/']"
        ]
        for i in range(timeout):
            for selector in tip_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elems:
                        if el.is_displayed():
                            link = el.get_attribute("href")
                            if link and "/topic/" in link:
                                logger.info(f"✅ Найдена ссылка на пост: {link}")
                                return link
                except:
                    continue
            time.sleep(1)
            if i % 10 == 0 and i > 0:
                logger.info(f"⏳ Поиск ссылки на пост... ({i}/{timeout} сек)")
        logger.warning("⚠️ Ссылка на пост не найдена в течение таймаута")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка поиска ссылки на пост: {e}")
        return None

# Подтверждение личности, если требуется
def try_confirm_identity():
    try:
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//input[@value='Yes, confirm']"
            " | //button[contains(text(),'Yes, confirm')]"
            " | //button[contains(text(),'Да, это я')]"
        )))
        btn.click()
        logger.info("🔓 Подтверждена личность")
        time.sleep(1)
    except Exception:
        logger.info("ℹ️ Страница подтверждения личности не показана")

# ... остальной код без изменений до функции post_to_group ...

def post_to_group(group_url, video_file=None, video_url=None, text=""):
    post_url = group_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю страницу постинга")
    try:
        driver.get(post_url)
        time.sleep(3)
        box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
            "div[contenteditable='true']"
        )))
        box.click()
        # ... код загрузки видео или вставки ссылки и текста ...
        # Финальная проверка и публикация
        share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
        is_disabled = share_button.get_attribute("disabled") is not None
        if is_disabled:
            logger.error("❌ Кнопка Share неактивна - не могу опубликовать")
            take_screenshot("share_button_disabled_before_publish")
            return
        # Публикуем и обрабатываем ссылку
        share_button.click()
        logger.info("✅ Опубликовано")
        # Ищем ссылку на опубликованный пост
        post_link = wait_for_post_link(timeout=30)
        if post_link:
            send_post_link_to_telegram(post_link)
        else:
            logger.warning("⚠️ Не удалось получить ссылку на пост")
        time.sleep(5)
    except Exception as e:
        logger.error(f"❌ Общая ошибка постинга в группу {group_url}: {e}")
        take_screenshot("post_general_error")

# Основной поток
def main():
    try:
        logger.info("🚀 Начинаю работу")
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        logger.info("🔑 Логин")
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        # SMS-верификация и остальные шаги логина
        try_sms_verification()
        logger.info("🎉 Вход выполнен")

        groups = retrieve_groups()
        video_file, video_url, post_text = retrieve_post_info()

        for i, g in enumerate(groups, 1):
            logger.info(f"📝 Публикую в группу {i}/{len(groups)}: {g}")
            post_to_group(g, video_file, video_url, post_text)
            if i < len(groups):
                time.sleep(3)

        # Очистка временных файлов
        if video_file and os.path.exists(video_file):
            try:
                os.unlink(video_file)
                logger.info("🗑️ Временный файл удален")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось удалить временный файл: {e}")
        temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
        if temp_dir != tempfile.gettempdir():
            try:
                import shutil
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info("🗑️ Временная папка очищена")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось очистить временную папку: {e}")

        logger.info("🎉 Все задачи выполнены")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Завершено")

if __name__ == '__main__':
    main()
