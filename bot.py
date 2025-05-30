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
            requests.post(self.api_url, data={
                "chat_id": self.chat_id,
                "text": self.format(record)
            })
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
        requests.post(api_url, data={
            "chat_id": TELEGRAM_USER_ID,
            "text": message
        })
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ссылки в Telegram: {e}")

# Поиск ссылки на опубликованный пост
def wait_for_post_link(timeout=30):
    try:
        tip_selectors = [
            "#hook_Block_TipBlock .js-tip-block-url",
            ".tip-block_lk a.js-tip-block-url",
            ".action-tip a[href*='/topic/']",
            ".toast a[href*='/topic/']"
        ]
        for _ in range(timeout):
            for selector in tip_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elems:
                        if el.is_displayed():
                            link = el.get_attribute("href")
                            if link and "/topic/" in link:
                                return link
                except:
                    pass
            time.sleep(1)
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

# Получение SMS-кода из Telegram
def retrieve_sms_code(timeout=120, poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids) + 1 if ids else None
    except:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0, 'offset': last}).json()
        except:
            time.sleep(poll)
            continue
        if not resp.get('ok'):
            time.sleep(poll)
            continue
        for upd in resp['result']:
            last = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat', {}).get('id')) != TELEGRAM_USER_ID:
                continue
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", msg.get('text','').strip(), re.IGNORECASE)
            if m:
                return m.group(1)
        time.sleep(poll)
    raise TimeoutException("SMS-код не получен")

# SMS-верификация
def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        return
    btn = wait.until(EC.element_to_be_clickable((By.XPATH,
        "//input[@type='submit' and @value='Get code']"
    )))
    btn.click()
    time.sleep(1)
    if 'too often' in driver.find_element(By.TAG_NAME,'body').text.lower():
        logger.error("🛑 Rate limit")
        sys.exit(1)
    inp = wait.until(EC.presence_of_element_located((By.XPATH,
        "//input[@id='smsCode' or contains(@name,'smsCode')]"
    )))
    code = retrieve_sms_code()
    inp.clear()
    inp.send_keys(code)
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    next_btn.click()

# Скачивание файла из Telegram
def download_file_from_telegram(file_id):
    try:
        file_info = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile",
            params={'file_id': file_id}
        ).json()
        if not file_info.get('ok'):
            return None
        size = file_info['result'].get('file_size', 0)
        if size > 20 * 1024 * 1024:
            return None
        path = file_info['result']['file_path']
        data = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{path}", timeout=60).content
        temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
        os.makedirs(temp_dir, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(path)[1], dir=temp_dir)
        tmp.write(data)
        tmp.close()
        return tmp.name
    except:
        return None

# Ожидание команды #группы
def retrieve_groups(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids) + 1 if ids else None
    except:
        pass
    while True:
        resp = requests.get(api, params={'timeout':0, 'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat', {}).get('id')) != TELEGRAM_USER_ID:
                    continue
                m = re.match(r"#группы\s+(.+)", msg.get('text','').strip(), re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        return urls
        time.sleep(poll)

# Ожидание команды #пост
def retrieve_post_info(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids) + 1 if ids else None
    except:
        pass
    while True:
        resp = requests.get(api, params={'timeout':0, 'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat', {}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                cap = msg.get('caption','').strip()
                match = None
                if txt:
                    match = re.match(r"#пост\s*(.*)", txt, re.IGNORECASE)
                elif cap:
                    match = re.match(r"#пост\s*(.*)", cap, re.IGNORECASE)
                if match:
                    text = match.group(1).strip()
                    vid_file = None
                    vid_url = None
                    if 'video' in msg:
                        vid_file = download_file_from_telegram(msg['video']['file_id'])
                    if not vid_file:
                        um = re.search(r"https?://\S+", txt + " " + cap + " " + text)
                        if um:
                            vid_url = um.group(0)
                            text = (txt + " " + cap + " " + text).replace(vid_url, "").replace("#пост", "").strip()
                    if vid_file or vid_url:
                        return vid_file, vid_url, text
        time.sleep(poll)

# Постинг в группу, возвращает ссылку на пост или None
def post_to_group(group_url, video_file=None, video_url=None, text=""):
    post_url = group_url.rstrip('/') + '/post'
    try:
        driver.get(post_url)
        time.sleep(3)
        box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[contenteditable='true']")))
        box.click()

        # загрузка видео или вставка ссылки
        if video_file and os.path.exists(video_file):
            upload_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[data-l*='button.video']")))
            upload_btn.click()
            up = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file'][accept*='video']")))
            up.send_keys(video_file)
            # ждём активации кнопки Share
            for _ in range(min(120, max(30, os.path.getsize(video_file) // (512*1024)))):
                sb = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
                if sb.get_attribute("disabled") is None:
                    break
                time.sleep(1)
        elif video_url:
            box.clear()
            box.send_keys(video_url + Keys.SPACE)
            for _ in range(15):
                sb = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
                if sb.get_attribute("disabled") is None:
                    break
                time.sleep(1)

        # добавление текста
        if text:
            tb = driver.find_element(By.CSS_SELECTOR, "div[contenteditable='true']")
            tb.click()
            tb.send_keys((" " if video_url else "") + text)

        # публикация
        share_button = driver.find_element(By.CSS_SELECTOR, "button.js-pf-submit-btn[data-action='submit']")
        if share_button.get_attribute("disabled") is not None:
            return None
        share_button.click()
        # ждём и возвращаем ссылку
        link = wait_for_post_link(timeout=30)
        time.sleep(5)
        return link
    except Exception:
        take_screenshot("post_error")
        return None

# Основной поток
def main():
    try:
        driver.get("https://ok.ru/")
        wait.until(EC.presence_of_element_located((By.NAME,'st.email'))).send_keys(EMAIL)
        driver.find_element(By.NAME,'st.password').send_keys(PASSWORD)
        driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
        time.sleep(2)
        try_confirm_identity()
        try_sms_verification()

        groups = retrieve_groups()
        video_file, video_url, post_text = retrieve_post_info()

        post_links = []
        for i, g in enumerate(groups, 1):
            logger.info(f"📝 Публикую в группу {i}/{len(groups)}: {g}")
            link = post_to_group(g, video_file, video_url, post_text)
            if link:
                post_links.append(link)
            if i < len(groups):
                time.sleep(3)

        # Отправляем все собранные ссылки в Telegram
        for link in post_links:
            send_post_link_to_telegram(link)

        # Удаляем временный файл, если он был создан
        if video_file and os.path.exists(video_file):
            try:
                os.unlink(video_file)
            except:
                pass

        # Очистка кастомной папки
        temp_dir = os.getenv('TEMP_VIDEO_DIR', tempfile.gettempdir())
        if temp_dir != tempfile.gettempdir() and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    finally:
        driver.quit()

if __name__ == '__main__':
    main()
