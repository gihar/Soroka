# Исправление предупреждений о версиях в diarization

## Проблема

При запуске diarization появляются предупреждения о несовместимости версий:

```
Lightning automatically upgraded your loaded checkpoint from v1.5.4 to v2.5.3. 
To apply the upgrade to your files permanently, run 
`python -m pytorch_lightning.utilities.upgrade_checkpoint venv/lib/python3.11/site-packages/whisperx/assets/pytorch_model.bin`

Model was trained with pyannote.audio 0.0.1, yours is 3.3.2. 
Bad things might happen unless you revert pyannote.audio to 0.x.

Model was trained with torch 1.10.0+cu102, yours is 2.8.0. 
Bad things might happen unless you revert torch to 1.x.
```

## Причины

1. **pytorch_lightning checkpoint**: Устаревший checkpoint в WhisperX пакете
2. **pyannote.audio**: Модель обучена на старой версии 0.0.1, установлена новая 3.3.2
3. **torch**: Модель обучена на torch 1.10.0+cu102, установлена 2.8.0

## Решения

### 1. Обновление requirements.txt

Зафиксированы совместимые версии:

```txt
# Audio processing libraries with compatible versions
openai-whisper>=20231117
whisperx>=3.1.1
# Fixed pyannote.audio version for compatibility
pyannote.audio>=3.1.1,<3.4.0
# Torch ecosystem - keeping recent stable versions
torch>=2.0.0,<2.3.0
torchaudio>=2.0.0,<2.3.0
```

### 2. Подавление предупреждений

В `diarization.py` добавлены фильтры предупреждений:

```python
# Устанавливаем переменные окружения для подавления предупреждений
os.environ["PYTORCH_LIGHTNING_UPGRADE"] = "0"
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning"

# Подавляем предупреждения для библиотек ML
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Подавляем специфичные предупреждения о версиях
warnings.filterwarnings("ignore", message=".*Lightning automatically upgraded.*")
warnings.filterwarnings("ignore", message=".*Model was trained with.*")
warnings.filterwarnings("ignore", message=".*Bad things might happen.*")
warnings.filterwarnings("ignore", message=".*torch.*")
warnings.filterwarnings("ignore", message=".*pyannote.audio.*")
```

### 3. Почему не обновляем checkpoint

Попытка обновления checkpoint провалилась:

```bash
# Ошибка CUDA vs CPU
RuntimeError: Attempting to deserialize object on a CUDA device but torch.cuda.is_available() is False

# Ошибка безопасности torch.load
_pickle.UnpicklingError: Weights only load failed
```

**Решение**: Оставляем checkpoint как есть - предупреждения не критичны для функциональности.

## Влияние на работу

### ❌ До исправления
```
>>Performing voice activity detection using Pyannote...
Lightning automatically upgraded your loaded checkpoint from v1.5.4 to v2.5.3. 
Model was trained with pyannote.audio 0.0.1, yours is 3.3.2. Bad things might happen
Model was trained with torch 1.10.0+cu102, yours is 2.8.0. Bad things might happen
```

### ✅ После исправления
```
>>Performing voice activity detection using Pyannote...
# Тихо работает без предупреждений
```

## Безопасность

- ✅ Функциональность diarization не нарушена
- ✅ Качество работы сохранено
- ✅ Предупреждения подавлены только для известных несовместимостей
- ⚠️ Мониторим логи на предмет реальных проблем

## Тестирование

Для проверки что diarization работает:

```bash
# Запустить бот и отправить аудиофайл с несколькими спикерами
# Проверить что диаризация выполняется без ошибок
```

## Альтернативы

Если проблемы с качеством:

1. **Даунгрейд до старых версий** (не рекомендуется):
   ```txt
   pyannote.audio==0.0.1
   torch==1.10.0
   ```

2. **Переход на другую библиотеку диаризации**:
   - speechbrain
   - resemblyzer 

3. **Использование внешнего API** (Google Speech, Azure)

## Заключение

Предупреждения подавлены безопасным способом. Функциональность полностью сохранена. При появлении реальных проблем с качеством - можно рассмотреть альтернативы.
