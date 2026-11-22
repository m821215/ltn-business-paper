import time
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
import requests
from bs4 import BeautifulSoup

# 自由時報全分類對照表（產出檔名: (顯示名稱, 原始 RSS 網址)）
FEEDS = {
    "all_paper.xml": ("即時總覽", "https://news.ltn.com.tw/rss/all.xml"),
    "politics_paper.xml": ("政治", "https://news.ltn.com.tw/rss/politics.xml"),
    "society_paper.xml": ("社會", "https://news.ltn.com.tw/rss/society.xml"),
    "life_paper.xml": ("生活", "https://news.ltn.com.tw/rss/life.xml"),
    "opinion_paper.xml": ("評論", "https://news.ltn.com.tw/rss/opinion.xml"),
    "world_paper.xml": ("國際", "https://news.ltn.com.tw/rss/world.xml"),
    "business_paper.xml": ("財經", "https://news.ltn.com.tw/rss/business.xml"),
    "sports_paper.xml": ("體育", "https://news.ltn.com.tw/rss/sports.xml"),
    "entertainment_paper.xml": ("娛樂", "https://news.ltn.com.tw/rss/entertainment.xml"),
    "art_paper.xml": ("藝文", "https://news.ltn.com.tw/rss/art.xml"),
    "def_paper.xml": ("軍武", "https://news.ltn.com.tw/rss/def.xml"),
    "local_paper.xml": ("地方", "https://news.ltn.com.tw/rss/local.xml"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 快取字典：避免 all.xml 與各分類重複抓取同一篇新聞的網頁
ARTICLE_CACHE: dict[str, tuple[str, str]] = {}

def fetch_article_details(url: str) -> tuple[str, str]:
    """進入自由時報網頁抓取封面大圖 (og:image) 與前段內文（含記憶體快取）"""
    if url in ARTICLE_CACHE:
        return ARTICLE_CACHE[url]

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        og_img = soup.find("meta", property="og:image")
        img_url = og_img["content"].strip() if (og_img and og_img.get("content")) else ""
        
        paragraphs = soup.select("div.text p")
        clean_texts = [
            p.get_text(strip=True) for p in paragraphs 
            if p.get_text(strip=True) and not p.get("class")
        ]
        full_summary = "<br><br>".join(clean_texts[:2]) if clean_texts else ""
        
        ARTICLE_CACHE[url] = (img_url, full_summary)
        time.sleep(0.25)  # 僅在實際發送網路請求時稍微延遲
        return img_url, full_summary
    except Exception as e:
        print(f"抓取失敗 ({url}): {e}")
        ARTICLE_CACHE[url] = ("", "")
        return "", ""

def process_single_feed(output_file: str, category_name: str, rss_url: str):
    print(f"\n=== 開始處理 [{category_name}] ({rss_url}) ===")
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[{category_name}] RSS 讀取失敗: {e}")
        return

    items = root.findall(".//item")
    paper_articles = []
    for item in items:
        link = item.findtext("link", "").strip()
        if "/paper/" in link:
            paper_articles.append({
                "title": item.findtext("title", "無標題").strip(),
                "link": link,
                "pub_date": item.findtext("pubDate", "").strip(),
                "raw_desc": item.findtext("description", "").strip(),
            })

    print(f"[{category_name}] 共篩選出 {len(paper_articles)} 篇報紙新聞")

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"自由時報 - {category_name}報紙版 (含圖)"
    ET.SubElement(channel, "link").text = "https://news.ltn.com.tw/list/newspaper"
    ET.SubElement(channel, "description").text = f"自動過濾自由時報{category_name}分類網址包含 /paper/ 的新聞並嵌入原圖"
    ET.SubElement(channel, "language").text = "zh-TW"

    tz_tw = timezone(timedelta(hours=8))
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(tz_tw))

    for art in paper_articles:
        img_url, rich_summary = fetch_article_details(art["link"])
        summary_text = rich_summary if rich_summary else art["raw_desc"]
        
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "title").text = art["title"]
        ET.SubElement(item_el, "link").text = art["link"]
        
        guid = ET.SubElement(item_el, "guid", isPermaLink="true")
        guid.text = art["link"]
        
        if art["pub_date"]:
            ET.SubElement(item_el, "pubDate").text = art["pub_date"]

        if img_url:
            html_body = f'<p><img src="{img_url}" style="max-width:100%; height:auto;" /></p><p>{summary_text}</p>'
        else:
            html_body = f'<p>{summary_text}</p>'

        ET.SubElement(item_el, "description").text = f"__CDATA_START__{html_body}__CDATA_END__"

    rough_string = ET.tostring(rss, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    pretty_xml = (
        pretty_xml
        .replace("__CDATA_START__", "<![CDATA[")
        .replace("__CDATA_END__", "]]>")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
    print(f"[{category_name}] 已儲存為 {output_file}")

def main():
    for output_file, (category_name, rss_url) in FEEDS.items():
        process_single_feed(output_file, category_name, rss_url)
    print("\n所有分類 XML 全部更新完成！")

if __name__ == "__main__":
    main()
