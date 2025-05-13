import os
import argparse
import requests # type: ignore

from dotenv import load_dotenv  # type: ignore
from notion_client import Client  # type: ignore

def extract_title(page):
    try:
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                title_list = prop.get("title", [])
                if title_list:
                    return title_list[0]["text"]["content"]
                else:
                    return ""
    except Exception:
        pass
    return "[Untitled]"

def is_untitled(page):
    title = extract_title(page)
    return title.lower() in ["", "untitled", "[untitled]"]

def stream_untitled_pages():
    cursor = None
    while True:
        response = notion.search(
            query="",
            filter={"property": "object", "value": "page"},
            start_cursor=cursor
        )
        for page in response["results"]:
            if is_untitled(page):
                yield page
        cursor = response.get("next_cursor")
        if not cursor:
            break

def get_page_content_text(page_id):
    blocks = notion.blocks.children.list(page_id)["results"]
    text_content = []
    for block in blocks:
        block_type = block["type"]
        if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
            rich_text = block[block_type].get("rich_text", [])
            for t in rich_text:
                if t["type"] == "text":
                    text_content.append(t["text"]["content"])
    return " ".join(text_content).strip()

def is_empty(page_id):
    """
    Returns True if the Notion page contains no visible content of any block type.
    """
    blocks = notion.blocks.children.list(page_id)["results"]

    for block in blocks:
        block_type = block.get("type")
        block_data = block.get(block_type, {})

        if "rich_text" in block_data:
            for rt in block_data["rich_text"]:
                if rt.get("type") == "text":
                    content = rt["text"]["content"].strip()
                    if content:
                        return False

        elif block_type in ["to_do", "callout", "toggle", "quote", "code"]:
            if "rich_text" in block_data:
                for rt in block_data["rich_text"]:
                    if rt.get("type") == "text" and rt["text"]["content"].strip():
                        return False

        elif block_type in [
            "image", "video", "file", "embed", "equation",
            "pdf", "bookmark", "table", "table_row", "synced_block", "link_to_page"
        ]:
            return False  

        elif block_data:
            return False

    return True  


def suggest_title_llm(text, model="gemma:2b-instruct"):
    prompt = f"Suggest a short, clear title (max 10 words) that captures the main idea of this note. Respond with the title only — no formatting, no quotes, no Markdown::\n\n{text}"

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False}
    )
    try:
        return response.json()["response"].strip()
    except Exception:
        return "[LLM error: no title]"

def format_notion_url(page_id):
    return f"https://www.notion.so/{page_id.replace('-', '')}"


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("INTERNAL_INTEGRATION_SECRET")
    notion = Client(auth=token)

    parser = argparse.ArgumentParser(description="Tidy untitled Notion pages")
    parser.add_argument("--auto-apply", action="store_true", help="Automatically apply suggested titles")
    parser.add_argument("--confirm-delete", action="store_true", default=True,
    help="Prompt to delete empty, untitled pages (default: true)")
    args = parser.parse_args()

    count = 0
    print("Scanning for Untitled Pages:\n")

    for idx, page in enumerate(stream_untitled_pages(), 1):
        page_id = page["id"]
        last_edited = page["last_edited_time"][:10]
        url = format_notion_url(page_id)
        raw_text = get_page_content_text(page_id)
        suggested_title = suggest_title_llm(raw_text) if raw_text else "[No content]"

        if is_empty(page_id) and args.confirm_delete:
            print(f"{idx}. Untitled and empty — {format_notion_url(page_id)}") 
            confirm = input("Delete this empty page? (yes/no): ").strip().lower()
            if confirm == "yes":
                notion.blocks.delete(page_id)
                print("Page deleted.\n")
            continue

        if suggested_title:
            print(f"{idx}. [Untitled] — Suggested: \"{suggested_title}\"")
            print(f"   Open: {format_notion_url(page_id)}\n")

            if args.auto_apply:
                notion.pages.update(
                    page_id=page_id,
                    properties={"title": {"title": [{"text": {"content": suggested_title}}]}}
                )
                print("Title applied.\n")
            else:
                confirm = input("Apply this title? (yes/no): ").strip().lower()
                if confirm == "yes":
                    notion.pages.update(
                        page_id=page_id,
                        properties={"title": {"title": [{"text": {"content": suggested_title}}]}}
                    )
                    print("Title applied.\n")

    print(f"Scan complete.\n")