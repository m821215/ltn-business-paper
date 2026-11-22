import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# 自由時報官方 RSS 分類對照表（產出檔名: (顯示名稱, 原始 RSS 網址)）
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

# 記憶體快取：避免不同分類抓到同一篇文章時重複發送請求
ARTICLE_CACHE: dict[str, tuple[str, str]] = {}

def clean_xml_text(text: str) -> str:
    """移除 XML 1.0 不允許的非法控制字元，避免解析失敗"""
    if not text:
        return ""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

def fetch_article_details(url: str) -> tuple[str, str]:
    """進入自由時報網頁抓取封面大圖 (og:image) 與前段內文（相容新聞版與藝文副刊版）"""
    if url in ARTICLE_CACHE:
        return ARTICLE_CACHE[url]

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 擷取新聞主圖
        og_img = soup.find("meta", property="og:image")
        img_url = og_img["content"].strip() if (og_img and og_img.get("content")) else ""
        
        # 同時支援一般新聞 (div.text p) 與藝文副刊 (div.article_content p) 的內文結構
        paragraphs = soup.select("div.text p, div.article_content p, article p")
        clean_texts = [
            p.get_text(strip=True) for p in paragraphs 
            if p.get_text(strip=True) and not p.get("class")
        ]
        full_summary = "<br><br>".join(clean_texts[:2]) if clean_texts else ""
        
        ARTICLE_CACHE[url] = (img_url, full_summary)
        time.sleep(0.25)
        return img_url, full_summary
    except Exception as e:
        print(f"抓取失敗 ({url}): {e}")
        ARTICLE_CACHE[url] = ("", "")
        return "", ""

def build_and_save_rss(output_file: str, title_text: str, site_link: str, desc_text: str, articles: list[dict]):
    """共用函式：將整理好的文章列表輸出為標準含圖 XML"""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title_text
    ET.SubElement(channel, "link").text = site_link
    ET.SubElement(channel, "description").text = desc_text
    ET.SubElement(channel, "language").text = "zh-TW"

    tz_tw = timezone(timedelta(hours=8))
    now_rfc822 = format_datetime(datetime.now(tz_tw))
    ET.SubElement(channel, "lastBuildDate").text = now_rfc822

    for art in articles:
        img_url, rich_summary = fetch_article_details(art["link"])
        summary_text = clean_xml_text(rich_summary if rich_summary else art.get("raw_desc", ""))
        clean_title = clean_xml_text(art["title"])
        
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "title").text = clean_title
        ET.SubElement(item_el, "link").text = art["link"]
        
        guid = ET.SubElement(item_el, "guid", isPermaLink="true")
        guid.text = art["link"]
        
        pub_date = art.get("pub_date") or now_rfc822
        ET.SubElement(item_el, "pubDate").text = pub_date

        if img_url:
            html_body = f'<p><img src="{img_url}" style="max-width:100%; height:auto;" /></p><p>{summary_text}</p>'
        else:
            html_body = f'<p>{summary_text}</p>'

        ET.SubElement(item_el, "description").text = html_body

    ET.indent(rss, space="  ", level=0)
    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)

    with open(output_file, "wb") as f:
        f.write(xml_bytes)
    print(f"已儲存為 {output_file}（共 {len(articles)} 篇）")

def process_single_feed(output_file: str, category_name: str, rss_url: str):
    """處理官方 RSS 來源並篩選網址包含 /paper/ 的文章"""
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
    build_and_save_rss(
        output_file=output_file,
        title_text=f"自由時報 - {category_name}",
        site_link="https://news.ltn.com.tw/list/newspaper",
        desc_text=f"自動過濾自由時報{category_name}分類網址包含 /paper/ 的新聞並嵌入原圖",
        articles=paper_articles
    )

def process_literature_page():
    """從自由藝文總列表 (newslist) 完整擷取所有包含 /paper/ 的藝文、副刊與家庭版文章"""
    list_url = "https://art.ltn.com.tw/newslist"
    output_file = "literature_paper.xml"
    print(f"\n=== 開始處理 [自由藝文與副刊總覽] ({list_url}) ===")

    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[自由藝文] 網頁讀取失敗: {e}")
        return

    # 移除右側「熱門文章 / 熱門新訊」側邊欄，避免混入舊文章
    for sidebar in soup.select("div.right, aside, div.hot_news, div.boxTitle"):
        sidebar.decompose()

    seen_links = set()
    lit_articles = []

    # 掃描主列表區域中所有包含 /paper/ 的文章連結
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if "/paper/" not in href:
            continue

        full_url = urljoin(list_url, href)
        if full_url in seen_links:
            continue

        title_el = a_tag.find(["h2", "h3", "h4", "p"])
        title = title_el.get_text(strip=True) if title_el else (a_tag.get("title") or a_tag.get_text(strip=True))
        
        if not title or len(title) < 2:
            continue

        seen_links.add(full_url)
        lit_articles.append({
            "title": title,
            "link": full_url,
            "pub_date": "",
            "raw_desc": ""
        })

    # 上限 40 篇以完整涵蓋單日報紙副刊與家庭plus文章量
    lit_articles = lit_articles[:40]
    print(f"[自由藝文與副刊] 共擷取出 {len(lit_articles)} 篇報紙版文章")

    build_and_save_rss(
        output_file=output_file,
        title_text="自由時報 - 藝文副刊",
        site_link=list_url,
        desc_text="自動擷取自由藝文總列表包含 /paper/ 的副刊、家庭與藝文報紙文章並嵌入原圖",
        articles=lit_articles
    )

def main():
    for output_file, (category_name, rss_url) in FEEDS.items():
        process_single_feed(output_file, category_name, rss_url)
    
    # 執行自由藝文與副刊網頁爬蟲
    process_literature_page()
    print("\n所有分類與藝文副刊 XML 全部更新完成！")

if __name__ == "__main__":
    main()
