import os
from dotenv import load_dotenv
from pathlib import Path

# Загружаем .env
loaded = load_dotenv()
print(".env загружен:", loaded)
print("Текущая папка:", os.getcwd())
print("Файлы в папке:", [f for f in os.listdir(".") if f.startswith(".env") or f.endswith(".json")])
print()

sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
sa_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")

print("GOOGLE_SERVICE_ACCOUNT_JSON =", sa_path)

if sa_path:
    path_obj = Path(sa_path)
    print("Это абсолютный путь:", path_obj.is_absolute())
    print("Файл существует:", path_obj.exists())
    if not path_obj.exists():
        alt_path = Path.cwd() / sa_path
        print("Пробуем путь относительно текущей папки:", alt_path)
        print("Существует там:", alt_path.exists())

print()
if sa_content:
    print("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT = Есть (длина:", len(sa_content), ")")
    print("Начинается с:", sa_content[:50])
else:
    print("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT = None")