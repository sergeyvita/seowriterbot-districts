import os
import json
import time
import re
import logging
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

# Настроим логирование, чтобы выводить логи в консоль
logging.basicConfig(level=logging.DEBUG)  # Устанавливаем уровень логирования на DEBUG
logger = logging.getLogger(__name__)  # Получаем логгер

# Убираем системные прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=httpx.Client()
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
app = Flask(__name__)

@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        uploaded_file = request.files.get('file')
        if not uploaded_file or uploaded_file.filename == "":
            logger.error("Файл не передан")
            return jsonify({"error": "Файл не передан"}), 400

        temp_path = f"/tmp/{int(time.time())}_{uploaded_file.filename}"
        uploaded_file.save(temp_path)

        with open(temp_path, "rb") as f:
            contents = f.read(200)
            logger.debug(f"🔍 Первые 200 байт содержимого файла: {contents[:200]}")
            file_response = client.files.create(file=f, purpose="assistants")

        os.remove(temp_path)
        logger.info(f"✅ Файл загружен: {file_response.id}")

        return jsonify({"file_id": file_response.id})

    except Exception as e:
        logger.error(f"❌ Ошибка в upload_file(): {e}")
        return jsonify({"error": "Ошибка загрузки", "details": str(e)}), 500



@app.route("/generate", methods=["POST"])
def generate():
    try:
        logger.info("📥 Запрос на /generate")

        init = request.values.get("init", "false").lower() == "true"
        delete_file = request.form.get("delete", "false").lower() == "true"
        prompt = request.form.get("prompt", "").strip()
        thread_id = request.form.get("thread_id", "").strip()
        file_id = request.form.get("file_id", "").strip()

        if init:
            uploaded_files = []
            for i in range(20):  # поддержка до 20 файлов context_file[0]...context_file[19]
                file_key = f"context_file[{i}]"
                if file_key in request.files:
                    uploaded_files.append(request.files[file_key])
        


            if not uploaded_files:
                logger.error("Файлы context_file[] не переданы")
                return jsonify({"error": "Файлы context_file[] не переданы"}), 400

            file_ids = []

            for i, uploaded_file in enumerate(uploaded_files):
                if uploaded_file.filename == "":
                    continue

                temp_path = f"/tmp/{int(time.time())}_{i}_{uploaded_file.filename}"
                uploaded_file.save(temp_path)

                with open(temp_path, "rb") as f:
                    file_response = client.files.create(file=f, purpose="assistants")

                file_ids.append(file_response.id)
                logger.info(f"📎 Файл загружен: {file_response.id}")
                os.remove(temp_path)

            if not file_ids:
                logger.error("Не удалось загрузить ни один файл")
                return jsonify({"error": "Не удалось загрузить ни один файл"}), 500

            thread = client.beta.threads.create()
            logger.info(f"🧵 Thread создан: {thread.id}")

            return jsonify({"thread_id": thread.id, "file_id": file_ids[0]})

        # === Этап генерации одного раздела ===
        if not thread_id or not file_id:
            logger.error("Не передан thread_id или file_id")
            return jsonify({"error": "Не передан thread_id или file_id"}), 400

        logger.info(f"Отправка сообщения в thread {thread_id} с file_id={file_id} и prompt={prompt}")
        
        # Отправляем prompt с привязкой к файлу
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt,
            attachments=[{"file_id": file_id, "tools": [{"type": "file_search"}]}]
        )
        logger.info(f"📨 Prompt отправлен в thread {thread_id}")

        # Удаление файла после сообщения, если запрошено
        if delete_file:
            try:
                client.files.delete(file_id)
                logger.info(f"🧹 Файл {file_id} удалён")
            except Exception as e:
                logger.error(f"⚠️ Ошибка удаления файла {file_id}: {e}")
                return jsonify({"error": f"Ошибка при удалении файла: {str(e)}"}), 500

        # Запускаем ассистента
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            extra_headers={"OpenAI-Beta": "assistants=v2"}
        )

        # Ждём завершения
        while True:
            try:
                run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                logger.info(f"📊 Статус потока: {run_status.status}")
                if run_status.status == "completed":
                    break
                elif run_status.status == "failed":
                    logger.error("Поток завершился с ошибкой.")
                    return jsonify({"error": "Ассистент не справился"}), 500
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при получении статуса потока: {e}")
                return jsonify({"error": f"Ошибка при получении статуса потока: {str(e)}"}), 500

        # Получаем ответ
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        content = ""
        for msg in messages.data:
            for item in msg.content:
                if hasattr(item, "text") and hasattr(item.text, "value"):
                    content += item.text.value.strip() + "\n"

        logger.info("📦 Ответ получен, начинаем разбор")

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

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Ошибка в generate(): {e}")
        return jsonify({"error": "Ошибка сервера", "details": str(e)}), 500

@app.route("/delete_file", methods=["POST"])
def delete_file():
    try:
        data = request.get_json(force=True)   # ждём JSON: {"file_id": "file‑abc123"}
        file_id = data.get("file_id", "").strip()

        if not file_id:
            return jsonify({"error": "file_id обязателен"}), 400

        client.files.delete(file_id)           # собственно удаление
        logger.info(f"🗑️  Файл {file_id} удалён")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"⚠️  Ошибка удаления файла {file_id}: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
