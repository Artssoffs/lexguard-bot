# Пример: Получение списка Issues из репозитория GitHub
import requests

owner = "OWNER"
repo = "REPO"
url = f"https://api.github.com/repos/{owner}/{repo}/issues"

response = requests.get(url)
if response.status_code == 200:
    issues = response.json()
    for issue in issues:
        print(f"Issue #{issue['number']}: {issue['title']}")
else:
    print("Ошибка при получении данных:", response.status_code)