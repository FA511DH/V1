import os
import random
import json
import requests
import urllib.parse
import time
import feedparser
import re
import io
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import g4f
from bs4 import BeautifulSoup 
import base64
from difflib import SequenceMatcher
from PIL import Image
import pillow_avif  # لدعم صيغة AVIF

# --- إعدادات GitHub والمصادر السرية ---
GG_TOKEN = os.environ.get("GG_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")

# قراءة المصادر من Secrets (تكون مخفية تماماً)
raw_feeds = os.environ.get("RSS_FEEDS", "")
if raw_feeds:
    RSS_FEEDS = [f.strip() for f in raw_feeds.split(",") if f.strip()]
else:
    # قائمة احتياطية في حال لم يتم ضبط السر (يفضل تركها فارغة للأمان)
    RSS_FEEDS = []

def clean_json_response(response_text):
    """تنظيف الرد لاستخراج JSON فقط"""
    try:
        if not response_text: return None
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            return json.loads(json_match.group(0))
    except: pass
    return None

def similar(a, b):
    """مقياس التشابه للعناوين"""
    return SequenceMatcher(None, a, b).ratio()

def upload_image_to_github(image_content, title):
    """رفع الصورة إلى GitHub بدلاً من Base64 لضمان الأرشفة ومنع مشاكل العرض"""
    try:
        # تعديل استخدام GG_TOKEN هنا أيضاً
        if not GG_TOKEN or not GITHUB_REPO:
            return None
            
        img = Image.open(io.BytesIO(image_content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        
        output = io.BytesIO()
        img.save(output, format="AVIF", quality=50)
        processed_content = output.getvalue()
        
        clean_name = re.sub(r'[^\w\s-]', '', title).strip().lower().replace(' ', '-')
        file_path = f"images/{clean_name}-{random.randint(10,99)}.avif"
        
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
        encoded_content = base64.b64encode(processed_content).decode('utf-8')
        
        headers = {"Authorization": f"token {GG_TOKEN}"}
        data = {
            "message": f"Upload image for: {title}",
            "content": encoded_content,
            "branch": "main"
        }
        
        res = requests.put(url, headers=headers, json=data)
        if res.status_code in [200, 201]:
            return f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{file_path}"
    except Exception as e:
        print(f"❌ Upload Error: {e}")
    return None

def get_trending_topic(service, blog_id):
    print("1. 🕵️‍♀️ Hunting for Fresh News (Smart Mode)...")
    if not RSS_FEEDS:
        raise Exception("RSS_FEEDS secret is empty. Please add your sources.")
        
    try:
        posts = service.posts().list(blogId=blog_id, maxResults=40).execute()
        existing_titles = [p['title'].lower() for p in posts.get('items', [])]
    except: existing_titles = []

    # خلط المصادر السرية
    random.shuffle(RSS_FEEDS)
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                title = entry.title.lower()
                
                if title in existing_titles: continue
                
                is_duplicate = False
                for old in existing_titles:
                    if similar(title, old) > 0.85: 
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    print(f"   🔥 Topic Found: {entry.title}")
                    return entry.title, entry.link 
        except: continue
    raise Exception("No fresh news found at the moment.")

def scrape_full_content(url):
    print("   📖 Analyzing Source Data...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(res.content, 'html.parser')
        
        for s in soup(["script", "style", "nav", "footer", "aside", "form", "ads", "iframe"]): 
            s.decompose()
        
        content = soup.find('article') or soup.find('main') or soup
        text = " ".join([p.get_text().strip() for p in content.find_all(['p', 'h2', 'li'])])
        return text[:8000]
    except: return None

def generate_pro_article(topic, news_url): 
    print(f"2. ✍️  Writing Rich Article (350-400 words)...")
    source_text = scrape_full_content(news_url)
    if not source_text or len(source_text) < 200:
        source_text = f"Topic: {topic}. Please research and write details."

    today_date = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
    Act as a professional Gaming Editor for 'Pro Gamer AR'.
    Task: Write a RICH, ENGAGING Arabic article (approx 350-400 words) about: "{topic}".
    
    Context Info:
    - **Current Date**: {today_date} (Use this for time context).
    - Source Data: "{source_text[:4000]}"
    
    REQUIRED STRUCTURE:
    1. **Introduction**: Narrative paragraph. Start directly with the news.
    2. **The Details**: Use <h2>. Full paragraphs explaining "How" and "Why".
    3. **Pro Gamer Advice**: A dedicated section titled "نصيحة للاعبين".
    4. **Conclusion**: Summary.

    **LABELS (TAGS) INSTRUCTIONS**:
    - Do NOT use generic tags like "News" or "Games".
    - EXTRACT the **Exact Game Name** (e.g., "Grand Theft Auto VI" or "GTA 6").
    - EXTRACT the **Platform** mentioned (e.g., "PlayStation 5", "PC", "Xbox").
    - EXTRACT the **Genre** (e.g., "Action", "RPG").
    - Use English for Game Names (it's better for SEO).
    
    Output JSON ONLY:
    {{
        "title": "Professional Arabic Title",
        "content": "HTML Body (p, h2, ul, li)",
        "labels": ["Game Name", "Platform", "Genre"],
        "image_description": "Cinematic shot of [Character/Scene], 8k, detailed, no text"
    }}
    """
    
    for i in range(3):
        try:
            response = g4f.ChatCompletion.create(model=g4f.models.gpt_4, messages=[{"role": "user", "content": prompt}])
            data = clean_json_response(response)
            if data and data.get('content'): return data
        except: time.sleep(3)
            
    raise Exception("AI Generation Failed")

def post_to_blogger():
    token_str = os.environ.get("BLOGGER_TOKEN_JSON")
    if not token_str: return
    creds = Credentials.from_authorized_user_info(json.loads(token_str))
    service = build('blogger', 'v3', credentials=creds)
    blog_id = service.blogs().listByUser(userId='self').execute()['items'][0]['id']
    
    topic, news_url = get_trending_topic(service, blog_id)
    article = generate_pro_article(topic, news_url)
    
    print("3. 🎨 Generating & Uploading Permanent Image...")
    
    clean_prompt = f"{article['image_description']}, no text, no typography, no words, masterpiece, 8k, unreal engine 5 render, photorealistic"
    encoded_prompt = urllib.parse.quote(clean_prompt)
    seed = random.randint(1, 9999)
    pollinations_url = f"https://pollinations.ai/p/{encoded_prompt}?width=1280&height=720&model=flux&seed={seed}&nologo=true"
    
    final_img_url = pollinations_url
    try:
        res = requests.get(pollinations_url, timeout=45)
        if res.status_code == 200:
            github_url = upload_image_to_github(res.content, article['title'])
            if github_url: final_img_url = github_url
    except: pass

    img_html = f'''
    <div class="separator" style="clear: both; text-align: center; margin-bottom: 20px;">
        <img border="0" src="{final_img_url}" 
             alt="{article['title']}" 
             title="{article['title']}" 
             style="width: 100%; max-width: 800px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" />
    </div>
    '''
    
    full_content = img_html + article['content']
    
    service.posts().insert(blogId=blog_id, body={
        "title": article['title'], 
        "content": full_content, 
        "labels": article.get('labels', [])
    }).execute()
    print(f"✅ Published Successfully with Permanent GitHub Image: {article['title']}")

if __name__ == "__main__":
    try:
        post_to_blogger()
    except Exception as e:
        print(f"🛑 Error: {e}")
