import os
import json
import time
import re
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx
import logging  # Добавляем для логирования

# Убираем системные прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=httpx.Client()
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
app = Flask(__name__)

# Настройка логирования
logging.basicConfig(filename="/path/to/your/logfile.log", level=logging.DEBUG)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        app.logger.info("📥 Запрос на /generate")  # Логируем начало запроса

        init = request.form.get("init", "false").lower() == "true"
        delete_file = request.form.get("delete", "false").lower() == "true"
        prompt = request.form.get("prompt", "").strip()
        thread_id = request.form.get("thread_id", "").strip()
        file_id = request.form.get("file_id", "").strip()

        # === Этап INIT: загрузка файла и создание потока ===
        if init:
            uploaded_files = [file for key, file in request.files.items() if key.startswith("context_file")]

            if not uploaded_files:
                app.logger.error("Ошибка: Файлы context_file[] не переданы")
                return jsonify({"error": "Файлы context_file[] не переданы"}), 400

            file_ids = []
            app.logger.info("Загружаем файлы для инициализации...")

            for i, uploaded_file in enumerate(uploaded_files):
                if uploaded_file.filename == "":
                    continue

                temp_path = f"/tmp/{int(time.time())}_{i}_{uploaded_file.filename}"
                uploaded_file.save(temp_path)

                with open(temp_path, "rb") as f:
                    file_response = client.files.create(file=f, purpose="assistants")

                file_ids.append(file_response.id)
                app.logger.info(f"📎 Файл загружен: {file_response.id}")
                os.remove(temp_path)

            if not file_ids:
                app.logger.error("Ошибка: Не удалось загрузить ни один файл")
                return jsonify({"error": "Не удалось загрузить ни один файл"}), 500

            thread = client.beta.threads.create()
            app.logger.info(f"🧵 Thread создан: {thread.id}")

            return jsonify({"thread_id": thread.id, "file_id": file_ids[0]})

        # === Этап генерации одного раздела ===
        if not thread_id or not file_id:
            app.logger.error("Ошибка: Не передан thread_id или file_id")
            return jsonify({"error": "Не передан thread_id или file_id"}), 400

        # Отправляем prompt с привязкой к файлу
        app.logger.info(f"📨 Отправляем prompt в thread {thread_id} с file_id {file_id}")
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt,
            attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}]
        )

        # Удаление файла после сообщения, если запрошено
        if delete_file:
            try:
                client.files.delete(file_id)
                app.logger.info(f"🧹 Файл {file_id} удалён")
            except Exception as e:
                app.logger.error(f"⚠️ Ошибка удаления файла {file_id}: {e}")
                return jsonify({"error": f"Ошибка при удалении файла: {str(e)}"}), 500

        # Запускаем ассистента
        app.logger.info("🚀 Запуск ассистента...")
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            extra_headers={"OpenAI-Beta": "assistants=v2"}
        )

        # Ждём завершения
        while True:
            try:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                app.logger.info(f"📊 Статус потока: {run_status.status}")
                if run_status.status == "completed":
                    break
                elif run_status.status == "failed":
                    app.logger.error("⚠️ Поток завершился с ошибкой.")
                    return jsonify({"error": "Ассистент не справился"}), 500
                time.sleep(1)
            except Exception as e:
                app.logger.error(f"❌ Ошибка при получении статуса потока: {e}")
                return jsonify({"error": f"Ошибка при получении статуса потока: {str(e)}"}), 500

        # Получаем ответ
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        content = ""
        for msg in messages.data:
            for item in msg.content:
                if hasattr(item, "text") and hasattr(item.text, "value"):
                    content += item.text.value.strip() + "\n"

        app.logger.info("📦 Ответ получен, начинаем разбор")

        def extract_block(tag, text):
            match = re.search(rf"==={tag}===\s*(.+?)(?=(?:===|$))", text, re.DOTALL)
            return match.group(1).strip() if match else ""

        result = {
            "element_name": extract_block("ELEMENT_NAME", content),
            "meta_title": extract_block("META_TITLE", content),
            "meta_keywords": extract_block("META_KEYWORDS", content),
            "meta_description": extract_block("META_DESCRIPTION", content),
            "article": extract_block("ARTICLE", content) or content.strip()
        }

        app.logger.info("📤 Возвращаем результат генерации")
        return jsonify(result)

    except Exception as e:
        app.logger.error(f"❌ Ошибка в generate(): {e}")
        return jsonify({"error": "Ошибка сервера", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
