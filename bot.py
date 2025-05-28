import os
import time
import re
import requests
import logging
import sys
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Для корректной работы через GitHub Actions:
# в workflow добавьте шаг установки Chrome и экспорт в окружение:
# echo "CHROME_MAJOR=<major_version>" >> $GITHUB_ENV

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

# Инициализация WebDriver с версией драйвера, соответствующей CHROME_MAJOR
def init_driver():
    opts = uc.ChromeOptions()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    # Берём основную версию драйвера из окружения (fallback 136)
    version_main = int(os.getenv("CHROME_MAJOR", "136"))
    return uc.Chrome(options=opts, version_main=version_main)

# Запуск драйвера
driver = init_driver()
wait = WebDriverWait(driver, 20)

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
        last = max(ids)+1 if ids else None
    except:
        pass
    deadline = time.time() + timeout
    logger.info("⏳ Ожидаю SMS-код")
    while time.time() < deadline:
        try:
            resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        except:
            time.sleep(poll)
            continue
        if not resp.get('ok'):
            time.sleep(poll)
            continue
        for upd in resp['result']:
            last = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message')
            if not msg or str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                continue
            txt = msg.get('text','').strip()
            m = re.match(r"^(?:#код\s*)?(\d{4,6})$", txt, re.IGNORECASE)
            if m:
                code = m.group(1)
                logger.info("✅ Код получен")
                return code
        time.sleep(poll)
    logger.error("❌ Таймаут SMS-кода")
    raise TimeoutException("SMS-код не получен")

# SMS-верификация: проверка data-l и ввод кода
def try_sms_verification():
    data_l = driver.find_element(By.TAG_NAME,'body').get_attribute('data-l') or ''
    if 'userMain' in data_l and 'anonymMain' not in data_l:
        logger.info("✅ Уже залогинен")
        return
    logger.info("🔄 Запрашиваю SMS-код")
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
    logger.info("✍️ Ввёл SMS-код")
    next_btn = driver.find_element(By.XPATH,
        "//input[@type='submit' and @value='Next']"
    )
    next_btn.click()
    logger.info("✅ SMS-верификация успешна")

# Ожидание команды #группы и извлечение URL групп
def retrieve_groups(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Жду команду #группы")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#группы\s+(.+)", txt, re.IGNORECASE)
                if m:
                    urls = re.findall(r"https?://ok\.ru/group/\d+/?", m.group(1))
                    if urls:
                        logger.info("✅ Группы получены")
                        return urls
        time.sleep(poll)

# Ожидание команды #пост и извлечение URL видео и текста
def retrieve_post_info(poll=5):
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    last = None
    try:
        init = requests.get(api, params={'timeout':0}).json()
        ids = [u['update_id'] for u in init.get('result', [])]
        last = max(ids)+1 if ids else None
    except:
        pass
    logger.info("⏳ Жду команду #пост")
    while True:
        resp = requests.get(api, params={'timeout':0,'offset': last}).json()
        if resp.get('ok'):
            for u in resp['result']:
                last = u['update_id'] + 1
                msg = u.get('message') or {}
                if str(msg.get('chat',{}).get('id')) != TELEGRAM_USER_ID:
                    continue
                txt = msg.get('text','').strip()
                m = re.match(r"#пост\s+(.+)", txt, re.IGNORECASE)
                if m:
                    rest = m.group(1).strip()
                    url_m = re.search(r"https?://\S+", rest)
                    if url_m:
                        vid = url_m.group(0)
                        txt_body = rest.replace(vid, "").strip()
                        logger.info("✅ Пост-инфо получено")
                        return vid, txt_body
        time.sleep(poll)

# Постинг видео и текста в группу
def post_to_group(group_url, video_url, text):
    post_url = group_url.rstrip('/') + '/post'
    logger.info("🚀 Открываю страницу постинга")
    driver.get(post_url)

    box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "div[contenteditable='true']"
    ))
    )
    box.click()
    box.clear()

    # Вставляем ссылку и пробел, чтобы загрузить превью
    box.send_keys(video_url)
    box.send_keys(Keys.SPACE)
    logger.info("✍️ Ссылка вставлена и пробел отправлен")

    # Ждём появление карточки превью
    attached = False
    for _ in range(10):
        if driver.find_elements(By.CSS_SELECTOR, "div.vid-card.vid-card__xl"):
            attached = True
            break
        if driver.find_elements(By.CSS_SELECTOR, "div.mediaPreview, div.mediaFlex, div.preview_thumb"):
            attached = True
            break
        time.sleep(1)
    if attached:
        logger.info("✅ Видео-карта появилась")
    else:
        logger.warning(f"⚠️ Не дождался карточки видео за 10 сек на {group_url}")

    # Вставляем текст
    box.send_keys(" " + text)
    logger.info("✍️ Текст вставлен")

    # Публикуем
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
        "button.js-pf-submit-btn[data-action='submit']"
    )))
    btn.click()
    logger.info("✅ Опубликовано")
    time.sleep(1)

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
        try_sms_verification()
        logger.info("🎉 Вход выполнен")

        groups = retrieve_groups()
        video_url, post_text = retrieve_post_info()
        for g in groups:
            post_to_group(g, video_url, post_text)

        logger.info("🎉 Все задачи выполнены")
    except Exception as e:
        logger.error(f"🔥 Ошибка: {e}")
        sys.exit(1)
    finally:
        driver.quit()
        logger.info("🔒 Завершено")

if __name__ == '__main__':
    main()
