# Usage Guide

## Getting Started

1.  Start the bot in Telegram: `/start`
2.  The bot will welcome you and is ready to accept files.

## Processing Meetings

### Option 1: Upload File
Simply drag and drop an audio or video file into the chat.
-   **Supported Formats**: MP3, WAV, M4A, OGG, MP4, MOV, etc.
-   **Limit**: 20MB (Telegram restriction).

### Option 2: External Links
Send a direct link to a file from:
-   **Google Drive** (must be publicly accessible or shared with the bot if configured)
-   **Yandex Disk**
-   **Direct URL** (e.g., `https://example.com/meeting.mp3`)

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize the bot |
| `/help` | Show help message |
| `/settings` | Configure LLM provider and other user settings |
| `/templates` | Manage meeting templates |
| `/performance` | Show system performance stats (Admin only) |
| `/health` | Check system health (Admin only) |

## Meeting Templates

Soroka supports various templates to structure your minutes:
-   **General**: Standard meeting structure.
-   **Daily Standup**: For agile teams.
-   **Strategic Session**: High-level planning.
-   **Technical Review**: For engineering discussions.

You can select a template after uploading a file, or let the bot **Auto-detect** the best template based on the content.

## Feedback & Improvements

After receiving the minutes, you can:
-   **Regenerate**: Try again with a different LLM or template.
-   **Edit**: Request changes to specific sections.
