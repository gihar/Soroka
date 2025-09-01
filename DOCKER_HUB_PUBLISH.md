# Публикация универсального образа в Docker Hub

Этот документ описывает, как создать и опубликовать универсальный Docker образ, который будет работать на всех архитектурах (ARM64, x86_64).

## Преимущества универсального образа

✅ **Один образ для всех платформ** - работает на Apple Silicon, Intel, AMD, ARM  
✅ **Автоматический выбор архитектуры** - Docker сам выберет подходящую версию  
✅ **Упрощенное развертывание** - пользователям не нужно думать об архитектуре  
✅ **Профессиональный подход** - как у официальных образов Docker  
✅ **Оптимизированный размер** - использует многоэтапную сборку  

## Подготовка к публикации

### 1. Создайте аккаунт на Docker Hub
```bash
# Войдите в Docker Hub
docker login
```

### 2. Настройте имя образа
Отредактируйте файл `build.sh`:
```bash
IMAGE_NAME="your-dockerhub-username/soroka"  # Замените на ваш username
```

### 3. Убедитесь, что у вас есть Docker Buildx
```bash
docker buildx version
```

## Сборка и публикация

### Быстрая публикация с универсальным скриптом
```bash
# Сделайте скрипт исполняемым (если еще не сделано)
chmod +x build.sh

# Соберите и опубликуйте multi-platform образ
./build.sh -m v1.0.0

# Или с очисткой старых образов
./build.sh -m -c v1.0.0
```

### Локальная сборка для тестирования
```bash
# Локальная оптимизированная сборка
./build.sh

# Локальная сборка с очисткой
./build.sh -l -c

# Локальная сборка с версией
./build.sh -l v1.0.0
```

### Ручная сборка (альтернатива)
```bash
# Создайте multi-platform builder
docker buildx create --name multiplatform-builder --use

# Соберите образ для всех платформ
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag your-username/soroka:latest \
    --tag your-username/soroka:v1.0.0 \
    --push \
    .
```

## Использование опубликованного образа

### Через docker-compose
```bash
# Используйте production конфигурацию
docker-compose -f docker-compose.prod.yml up -d
```

### Через docker run
```bash
docker run -d \
    --name soroka-bot \
    -e TELEGRAM_TOKEN=your_token \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/logs:/app/logs \
    your-username/soroka:latest
```

## Поддерживаемые платформы

| Платформа | Архитектура | Описание |
|-----------|-------------|----------|
| `linux/amd64` | x86_64 | Intel/AMD процессоры |
| `linux/arm64` | ARM64 | Apple Silicon, ARM64 серверы |

## Проверка образа

### Проверить доступные платформы
```bash
docker buildx imagetools inspect your-username/soroka:latest
```

### Тестирование на разных архитектурах
```bash
# Тест на ARM64 (Apple Silicon)
docker run --rm --platform linux/arm64 your-username/soroka:latest python --version

# Тест на x86_64
docker run --rm --platform linux/amd64 your-username/soroka:latest python --version
```

## Версионирование

Рекомендуемая схема версионирования:
- `latest` - последняя стабильная версия
- `v1.0.0` - семантическое версионирование
- `v1.0.0-beta` - бета-версии
- `v1.0.0-rc1` - релиз-кандидаты

## Автоматизация с GitHub Actions

Создайте `.github/workflows/docker-publish.yml`:

```yaml
name: Publish Docker Image

on:
  push:
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v2
      
      - name: Login to Docker Hub
        uses: docker/login-action@v2
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
      
      - name: Build and push
        uses: docker/build-push-action@v4
        with:
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            your-username/soroka:latest
            your-username/soroka:${{ github.ref_name }}
```

## Универсальный скрипт build.sh

### Опции скрипта
```bash
./build.sh [опции] [версия]

Опции:
  -l, --local      Локальная оптимизированная сборка (по умолчанию)
  -m, --multi      Multi-platform сборка для Docker Hub
  -c, --clean      Очистка старых образов перед сборкой
  -h, --help       Показать справку
```

### Примеры использования
```bash
# Локальная сборка для разработки
./build.sh

# Multi-platform сборка для продакшена
./build.sh -m v1.0.0

# Сборка с очисткой
./build.sh -m -c latest

# Показать справку
./build.sh --help
```

## Troubleshooting

### Ошибка "exec format error"
- Убедитесь, что образ собран для нужной архитектуры
- Проверьте, что используете multi-platform сборку

### Ошибка "no matching manifest"
- Проверьте, что образ опубликован для нужной платформы
- Используйте `docker buildx imagetools inspect` для проверки

### Медленная сборка
- Используйте кэширование слоев (включено по умолчанию в build.sh)
- Рассмотрите использование GitHub Actions для автоматической сборки

### Ошибка "Docker Buildx не найден"
- Установите Docker Desktop или обновите Docker
- Убедитесь, что buildx доступен: `docker buildx version`

## Полезные команды

```bash
# Просмотр всех образов
docker images

# Удаление неиспользуемых образов
docker image prune -a

# Просмотр информации о multi-platform образе
docker buildx imagetools inspect your-username/soroka:latest

# Тестирование образа локально
docker run --rm your-username/soroka:latest python -c "print('Hello from universal image!')"

# Проверка синтаксиса скрипта
bash -n build.sh

# Локальная сборка с подробным выводом
./build.sh -l -c
```

## Преимущества оптимизированного образа

✅ **Многоэтапная сборка** - меньший размер финального образа  
✅ **Безопасность** - исключены инструменты сборки из финального образа  
✅ **Кэширование** - BuildKit inline cache для ускорения сборки  
✅ **Предсказуемость** - явно указанный UID 1000 для пользователя  
✅ **Универсальность** - один скрипт для всех задач сборки
