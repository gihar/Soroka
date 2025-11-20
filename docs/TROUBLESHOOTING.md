# Troubleshooting

## Common Issues

### 1. "File too large"
-   **Cause**: Telegram limits bots to downloading files under 20MB.
-   **Solution**: Upload the file to Google Drive or Yandex Disk and send the link to the bot.

### 2. "Transcription failed"
-   **Cause**: The audio might be corrupted, silent, or in an unsupported format.
-   **Solution**: Check the file locally. If it plays fine, try converting it to MP3/WAV before uploading.

### 3. OOM (Out of Memory) Errors
-   **Symptoms**: Bot crashes or restarts during processing of large files.
-   **Solution**:
    -   Increase Docker memory limit.
    -   Switch `TRANSCRIPTION_MODE` to `cloud` or `groq` to offload processing.
    -   Reduce `MAX_SPEAKERS` in config.

### 4. "LLM Error"
-   **Cause**: API key issues or provider outages.
-   **Solution**: Check your API keys in `.env`. Verify your balance with the provider (OpenAI, Anthropic, etc.).

## Logs

If you are hosting the bot, check the logs for detailed error messages:

```bash
# Docker
docker-compose logs -f --tail=100

# Local
tail -f logs/bot.log
```

## Getting Help

If you encounter a bug, please open an issue on GitHub with:
1.  Description of the problem.
2.  Steps to reproduce.
3.  Relevant log snippets.
