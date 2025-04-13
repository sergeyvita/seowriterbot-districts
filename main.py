import os
import json
import time
import re
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

# Убираем системные прокси
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=httpx.Client()
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")
app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def generate():
    try:
        print("📥 Запрос на /generate")

        init = request.form.get("init", "false").lower() == "true"
        delete_file = request.form.get("delete", "false").lower() == "true"
        prompt = request.form.get("prompt", "").strip()
        thread_id = request.form.get("thread_id", "").strip()
        file_id = request.form.get("file_id", "").strip()

        # === Этап INIT: загрузка файла и создание потока ===
        if init:
            uploaded_files = [file for key, file in request.files.items() if key.startswith("context_file")]

            if not uploaded_files:
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
                print(f"📎 Файл загружен: {file_response.id}")
                os.remove(temp_path)

            if not file_ids:
                return jsonify({"error": "Не удалось загрузить ни один файл"}), 500

            thread = client.beta.threads.create()
            print(f"🧵 Thread создан: {thread.id}")

            return jsonify({"thread_id": thread.id, "file_id": file_ids[0]})

        # === Этап генерации одного раздела ===
        if not thread_id or not file_id:
            return jsonify({"error": "Не передан thread_id или file_id"}), 400

        # Отправляем prompt с привязкой к файлу
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=prompt,
            attachments=[
                {"file_id": file_id, "tools": [{"type": "file_search"}]}
            ]
        )
        print(f"📨 Prompt отправлен в thread {thread_id}")

        # Удаление файла после сообщения, если запрошено
        if delete_file:
            try:
                client.files.delete(file_id)
                print(f"🧹 Файл {file_id} удалён")
            except Exception as e:
                print(f"⚠️ Ошибка удаления файла {file_id}: {e}")

        # Запускаем ассистента
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID,
            extra_headers={"OpenAI-Beta": "assistants=v2"}
        )

        # Ждём завершения
        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if run_status.status == "completed":
                break
            elif run_status.status == "failed":
                return jsonify({"error": "Ассистент не справился"}), 500
            time.sleep(1)

        # Получаем ответ
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        content = ""
        for msg in messages.data:
            for item in msg.content:
                if hasattr(item, "text") and hasattr(item.text, "value"):
                    content += item.text.value.strip() + "\n"

        print("📦 Ответ получен, начинаем разбор")

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
        print(f"❌ Ошибка в generate(): {e}")
        return jsonify({"error": "Ошибка сервера", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
