import json
import subprocess
import os
import re
import time
from flask import Flask, request, jsonify
from openai import OpenAI
import httpx

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 🗭️ Создаём httpx клиент без прокси
no_proxy_client = httpx.Client()

# 🧠 Создаём OpenAI клиент
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    http_client=no_proxy_client
)

ASSISTANT_ID = os.environ.get("ASSISTANT_ID")

app = Flask(__name__)

@app.route("/generate", methods=["POST"])
def generate():
    print("📥 POST-запрос получен на /generate")

    try:
        try:
            data = request.get_json(force=True)
            with open("render_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== 📥 Поступил запрос {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
                
            print("📦 Полученные данные:\n", data)
        except Exception as e:
            error_msg = f"\n❗️ Ошибка при парсинге JSON: {str(e)} — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            print(error_msg)
            return jsonify({"error": "Ошибка парсинга JSON", "details": str(e)}), 400
                   
        if not data:
            msg = f"\n‼️ Нет JSON-данных в запросе от {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            print(msg)
            return jsonify({"error": "Нет данных"}), 400

        chunks = data.get("chunks", [])
        reference_chunk = data.get("reference_chunk", "").strip()
        previous_text = data.get("previous_text", "").strip()


        generated_blocks = {
            "element_name": "",
            "meta_title": "",
            "meta_keywords": "",
            "meta_description": "",
            "article_parts": []
        }

        accumulated_article = ""

        chunks = [c for c in chunks if isinstance(c, str) and c.strip()]
        with open("render_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== ✅ Фильтрованные чанки ({len(chunks)}): ===\n")
            for idx, c in enumerate(chunks):
                f.write(f"\n--- Чанк {idx} (первые 300 символов): ---\n{c[:300]}\n...\n")
            
        if not chunks:
            return jsonify({"error": "Все чанки были пустыми или некорректными"}), 400

        for i, chunk in enumerate(chunks):
            print(f"\n🔁 Создание потока для чанка {i}")
            thread = client.beta.threads.create()
            with open("render_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n🔁 Поток {i}: создан thread_id={thread.id}\n")

            if i == 0:
                system_prompt = (
                    "🔹 Это первая часть статьи. Начни ярко, живо, от первого лица. Не завершай статью — продолжение следует.\n\n"
                )
            else:
                system_prompt = (
                    "🔹 Продолжи статью, опираясь на предыдущую часть и контекст. Не делай выводов, статья продолжается.\n\n"
                )
                if previous_text:
                    system_prompt += "=== Предыдущая часть статьи ===\n" + previous_text + "\n\n"
                    
            if reference_chunk:
               system_prompt += "=== Справочная информация ===\n" + reference_chunk + "\n\n"

            print(f"📄 Чанк {i}: {chunk[:200]}...\n")

            with open("render_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n📝 Отправка чанка {i} ассистенту. prompt:\n{system_prompt[:500]}...\n")
                f.write(f"\n🔹 Содержимое чанка:\n{chunk[:1000]}...\n")

            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=system_prompt + "\n\n" + chunk
            )

            print("🚀 Запуск ассистента")
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID,
                extra_headers={"OpenAI-Beta": "assistants=v2"}
            )

            print("⏳ Ожидание ответа от ассистента...")
            while True:
                run_status = client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )
                if run_status.status == "completed":
                    print("✅ Ассистент завершил генерацию")
                    break
                elif run_status.status == "failed":
                    raise Exception(f"Ассистент не справился с задачей для чанка {i}")
                time.sleep(1)

            print("📬 Получение ответа от ассистента")
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            if not messages.data or not messages.data[0].content:
                raise Exception(f"Нет контента в ответе на чанк {i}")

            with open("render_debug.log", "a", encoding="utf-8") as f:
                f.write(f"\n📨 Ответ на чанк {i} (первые 1000 символов):\n")
                f.write(article_part[:1000] + "\n...\n" if 'article_part' in locals() and article_part else "❌ article_part пустой\n")

            
            
            
            # 🧠 Ищем JSON-ответ от ассистента с ключами blocks, meta и т.д.
            content = ""
            article_part = ""
            
            for msg in messages.data:
                for item in msg.content:
                    if hasattr(item, "text") and hasattr(item.text, "value"):
                        text_value = item.text.value.strip()
                        content += text_value + "\n\n"
                        
                        try:
                            parsed = json.loads(text_value)
                            if isinstance(parsed, dict) and "blocks" in parsed:
                                print("✅ Найден JSON с блоками!")
                                
                                if i == 0:
                                    generated_blocks["element_name"] = parsed.get("element_name", "")
                                    generated_blocks["meta_title"] = parsed.get("meta_title", "")
                                    generated_blocks["meta_keywords"] = parsed.get("meta_keywords", "")
                                    generated_blocks["meta_description"] = parsed.get("meta_description", "")

                                blocks = parsed.get("blocks", {})
                                article_part = "\n\n".join(blocks.values())
                                break  # прерываем внутренний цикл

                        except Exception as e:
                            print(f"⚠️ Ошибка при JSON-декодировании: {e}")

                if article_part:
                    break

            with open("debug_chunks_output.log", "a", encoding="utf-8") as f:
                f.write(f"\n=== Чанк {i} ===\n{content[:1000]}\n...\n")

            def extract_block(tag, text):
                match = re.search(rf"==={tag}===\s*(.+?)(?=(?:===|$))", text, re.DOTALL)
                return match.group(1).strip() if match else ""

            
            # Только если article_part не был получен через JSON → пробуем legacy-метод
            if not article_part:
                if i == 0:
                    generated_blocks["element_name"] = extract_block("ELEMENT_NAME", content)
                    generated_blocks["meta_title"] = extract_block("META_TITLE", content)
                    generated_blocks["meta_keywords"] = extract_block("META_KEYWORDS", content)
                    generated_blocks["meta_description"] = extract_block("META_DESCRIPTION", content)
                    article_part = extract_block("ARTICLE", content)
                else:
                    article_part = extract_block("ARTICLE", content)

            generated_blocks["article_parts"].append(article_part)
            
            # Не добавляем контекстный чанк (index 1) в accumulated_article
            if i != 1:
                accumulated_article += "\n\n" + article_part

            time.sleep(5)

        print("=== 📅 ОТВЕТ ОТ OPENAI ===")
        print(content[:1000] + "\n...")
        print("=== 🖚 ===")


        with open("render_debug.log", "a", encoding="utf-8") as f:
                f.write("\n=== 📦 Сбор финального JSON ===\n")
                f.write(f"Заголовок: {generated_blocks['element_name']}\n")
                f.write(f"META TITLE: {generated_blocks['meta_title']}\n")
                f.write(f"ARTICLE preview: {accumulated_article[:1000]}\n...\n")
            
        result = {
            "element_name": generated_blocks["element_name"],
            "meta_title": generated_blocks["meta_title"],
            "meta_keywords": generated_blocks["meta_keywords"],
            "meta_description": generated_blocks["meta_description"],
            "article": "\n\n".join(generated_blocks["article_parts"])
        }

        with open("render_debug.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== Финальный результат от {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(f"Название: {result['element_name']}\n")
            f.write(f"META TITLE: {result['meta_title']}\n")
            f.write(f"META DESC: {result['meta_description']}\n")
            f.write(f"META KEYS: {result['meta_keywords']}\n")
            f.write("ARTICLE: " + result["article"][:1000] + "\n...\n")

        return jsonify(result)

    except Exception as e:
        print(f"❌ Глобальная ошибка в generate(): {str(e)}")
        return jsonify({"error": "Внутренняя ошибка сервера", "details": str(e)}), 500


if __name__ == "__main__":
    print("🟢 Flask сервер запущен. Ожидаем запросы...")
    app.run(host="0.0.0.0", port=10000)
