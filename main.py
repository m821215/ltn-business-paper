import time
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
import requests
from bs4 import BeautifulSoup

RSS_SOURCE = "https://news.ltn.com.tw/rss/business.xml"
OUTPUT_FILE = "business_paper.xml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_article_details(url: str) -> tuple[str, str]:
    """進入自由時報網頁抓取封面大圖 (og:image) 與前段內文"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 擷取新聞封面主圖
        og_img = soup.find("meta", property="og:image")
        img_url = og_img["content"].strip() if (og_img and og_img.get("content")) else ""
        
        # 擷取前兩段內文作為摘要
        paragraphs = soup.select("div.text p")
        clean_texts = [
            p.get_text(strip=True) for p in paragraphs 
            if p.get_text(strip=True) and not p.get("class")
        ]
        full_summary = "<br><br>".join(clean_texts[:2]) if clean_texts else ""
        
        return img_url, full_summary
    except Exception as e:
        print(f"抓取失敗 ({url}): {e}")
        return "", ""

def main():
    print(f"正在讀取自由時報財經版 RSS: {RSS_SOURCE}")
    resp = requests.get(RSS_SOURCE, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    
    root = ET.fromstring(resp.content)
    items = root.findall(".//item")
    
    paper_articles = []
    for item in items:
        link = item.findtext("link", "").strip()
        # 僅保留網址包含 /paper/ 的報紙版新聞
        if "/paper/" in link:
            title = item.findtext("title", "無標題").strip()
            pub_date = item.findtext("pubDate", "").strip()
            raw_desc = item.findtext("description", "").strip()
            
            paper_articles.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "raw_desc": raw_desc
            })

    print(f"共篩選出 {len(paper_articles)} 篇財經報紙新聞，開始擷取圖片...")

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "自由時報 - 財經報紙版 (含圖)"
    ET.SubElement(channel, "link").text = "https://ec.ltn.com.tw/list/paper"
    ET.SubElement(channel, "description").text = "自動過濾自由時報財經版網址包含 /paper/ 的新聞並嵌入原圖"
    ET.SubElement(channel, "language").text = "zh-TW"

    tz_tw = timezone(timedelta(hours=8))
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(tz_tw))

    for idx, art in enumerate(paper_articles, 1):
        print(f"[{idx}/{len(paper_articles)}] 處理中: {art['title']}")
        img_url, rich_summary = fetch_article_details(art["link"])
        summary_text = rich_summary if rich_summary else art["raw_desc"]
        
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "title").text = art["title"]
        ET.SubElement(item_el, "link").text = art["link"]
        
        guid = ET.SubElement(item_el, "guid", isPermaLink="true")
        guid.text = art["link"]
        
        if art["pub_date"]:
            ET.SubElement(item_el, "pubDate").text = art["pub_date"]

        # 將圖片標籤直接寫入 description，確保 Inoreader 預設直接顯示圖片
        if img_url:
            html_body = f'<p><img src="{img_url}" style="max-width:100%; height:auto;" /></p><p>{summary_text}</p>'
        else:
            html_body = f'<p>{summary_text}</p>'

        ET.SubElement(item_el, "description").text = f"__CDATA_START__{html_body}__CDATA_END__"
        time.sleep(0.3)

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

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
    print("business_paper.xml 產出完成！")

if __name__ == "__main__":
    main()
