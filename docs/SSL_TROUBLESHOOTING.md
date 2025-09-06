# Решение SSL проблем с Speechmatics API

## Проблема

При использовании Speechmatics API может возникнуть ошибка:
```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate in certificate chain
```

## Быстрое решение

### 1. Отключите SSL верификацию (для разработки)

Добавьте в ваш `.env` файл:
```env
SSL_VERIFY=false
```

### 2. Перезапустите бота

```bash
# Остановите бота (Ctrl+C)
# Запустите заново
python main.py
```

## Альтернативные решения

### Для macOS

```bash
# Обновите сертификаты Python
/Applications/Python\ 3.11/Install\ Certificates.command

# Или установите certifi
pip install --upgrade certifi
```

### Для Ubuntu/Debian

```bash
# Обновите сертификаты системы
sudo apt-get update && sudo apt-get install ca-certificates

# Обновите certifi
pip install --upgrade certifi
```

### Для Windows

```bash
# Обновите certifi
pip install --upgrade certifi

# Или отключите SSL верификацию
set PYTHONHTTPSVERIFY=0
```

## Проверка решения

После применения решения попробуйте снова отправить аудио файл боту. Ошибка SSL должна исчезнуть.

## Безопасность

⚠️ **Важно**: Отключение SSL верификации снижает безопасность соединения. Используйте `SSL_VERIFY=false` только в среде разработки. В продакшене рекомендуется обновить сертификаты и использовать `SSL_VERIFY=true`.

## Дополнительная информация

- [Документация Speechmatics](https://docs.speechmatics.com/)
- [Настройка SSL в Python](https://docs.python.org/3/library/ssl.html)
- [Обновление сертификатов certifi](https://pypi.org/project/certifi/)
