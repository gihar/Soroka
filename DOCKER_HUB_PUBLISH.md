# Публикация универсального образа в Docker Hub

Этот документ описывает, как создать и опубликовать универсальный Docker образ, который будет работать на всех архитектурах (ARM64, x86_64, ARMv7).

## Преимущества универсального образа

✅ **Один образ для всех платформ** - работает на Apple Silicon, Intel, AMD, ARM  
✅ **Автоматический выбор архитектуры** - Docker сам выберет подходящую версию  
✅ **Упрощенное развертывание** - пользователям не нужно думать об архитектуре  
✅ **Профессиональный подход** - как у официальных образов Docker  

## Подготовка к публикации

### 1. Создайте аккаунт на Docker Hub
```bash
# Войдите в Docker Hub
docker login
```

### 2. Настройте имя образа
Отредактируйте файл `build-multi-platform.sh`:
```bash
IMAGE_NAME="your-dockerhub-username/telegram-bot"  # Замените на ваш username
```

### 3. Убедитесь, что у вас есть Docker Buildx
```bash
docker buildx version
```

## Сборка и публикация

### Быстрая публикация
```bash
# Сделайте скрипт исполняемым
chmod +x build-multi-platform.sh

# Соберите и опубликуйте образ
./build-multi-platform.sh v1.0.0
```

### Ручная сборка
```bash
# Создайте multi-platform builder
docker buildx create --name multiplatform-builder --use

# Соберите образ для всех платформ
docker buildx build \
    --platform linux/amd64,linux/arm64,linux/arm/v7 \
    --tag your-username/telegram-bot:latest \
    --tag your-username/telegram-bot:v1.0.0 \
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
    --name telegram-bot \
    -e TELEGRAM_TOKEN=your_token \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/logs:/app/logs \
    your-username/telegram-bot:latest
```

## Поддерживаемые платформы

| Платформа | Архитектура | Описание |
|-----------|-------------|----------|
| `linux/amd64` | x86_64 | Intel/AMD процессоры |
| `linux/arm64` | ARM64 | Apple Silicon, ARM64 серверы |
| `linux/arm/v7` | ARMv7 | Raspberry Pi 3, старые ARM устройства |

## Проверка образа

### Проверить доступные платформы
```bash
docker buildx imagetools inspect your-username/telegram-bot:latest
```

### Тестирование на разных архитектурах
```bash
# Тест на ARM64 (Apple Silicon)
docker run --rm --platform linux/arm64 your-username/telegram-bot:latest python --version

# Тест на x86_64
docker run --rm --platform linux/amd64 your-username/telegram-bot:latest python --version
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
          platforms: linux/amd64,linux/arm64,linux/arm/v7
          push: true
          tags: |
            your-username/telegram-bot:latest
            your-username/telegram-bot:${{ github.ref_name }}
```

## Troubleshooting

### Ошибка "exec format error"
- Убедитесь, что образ собран для нужной архитектуры
- Проверьте, что используете multi-platform сборку

### Ошибка "no matching manifest"
- Проверьте, что образ опубликован для нужной платформы
- Используйте `docker buildx imagetools inspect` для проверки

### Медленная сборка
- Используйте кэширование слоев
- Рассмотрите использование GitHub Actions для автоматической сборки

## Полезные команды

```bash
# Просмотр всех образов
docker images

# Удаление неиспользуемых образов
docker image prune -a

# Просмотр информации о multi-platform образе
docker buildx imagetools inspect your-username/telegram-bot:latest

# Тестирование образа локально
docker run --rm your-username/telegram-bot:latest python -c "print('Hello from universal image!')"
```
