# Git и последующее размещение в Amvera

В проекте создан локальный Git-репозиторий с веткой `main`.
Первый коммит сохраняет найденную реализацию, последующие — законченные изменения.
GitHub не обязателен: Amvera предоставляет собственный удалённый Git-репозиторий.
Для хранения исходников подключён GitHub: [himpls/poker](https://github.com/himpls/poker).
Remote `origin` указывает на `https://github.com/himpls/poker.git`, основная ветка — `main`.

## Отправка изменений в GitHub

После проверок и коммита:

```powershell
git push origin main
```

GitHub хранит исходники и историю; рабочая база и секреты в репозиторий не входят.
Размещение в Amvera выполняется отдельно через remote `amvera` после подготовки окружения.

## Работа над изменениями

```powershell
git status
git diff
python -m pytest -q
git add <конкретные-файлы>
git diff --cached
git commit -m "Краткое описание законченного изменения"
```

Перед коммитом проверять состав файлов. `.env`, `.env.*` кроме `.env.example`,
базы, резервные копии, ключи и `.tools` исключены через `.gitignore`.
Рабочие базы хранятся отдельно; Git версионирует код и миграции, а не данные игроков.

## Подключение Amvera

Когда приложение будет готово к размещению, взять **точный URL** во вкладке
«Репозиторий» выбранного проекта Amvera. Не включать пароль или токен в URL.

```powershell
git remote add amvera <URL-из-кабинета-Amvera>
git remote -v
git ls-remote amvera
```

Если репозиторий Amvera уже содержит коммиты, сначала выполнить
`git fetch amvera`, изучить `git log --all --oneline --graph` и совместить истории.
Не применять force push. При пустом remote и готовом приложении:

```powershell
git push amvera main:master
```

Локальная ветка остаётся `main`; ветка размещения Amvera — `master`.
Push запускает сборку/размещение, поэтому выполнять его после проверки конфигурации,
согласования тарифа и настройки секретов. Код и Mini App должны иметь HTTPS,
SQLite — постоянный диск `/data`. Текущий polling entrypoint ещё не поднимает HTTP.
Remote не добавлен: URL проекта пока не указан. Код в Amvera ещё не отправлялся.

Источник: [официальная инструкция Amvera](https://docs.amvera.ru/applications/git/secondary-origin.html).
