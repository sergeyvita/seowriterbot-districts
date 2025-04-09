#!/usr/bin/env bash

echo ">>> Очистка pip-кэша..."
rm -rf ~/.cache/pip

echo ">>> Удаление openai (на всякий случай)..."
pip uninstall -y openai

echo ">>> Установка новой версии OpenAI..."
pip install --no-cache-dir "openai>=1.25.1"

echo ">>> Установка остальных зависимостей..."
pip install --no-cache-dir flask==2.3.3 tiktoken httpx
