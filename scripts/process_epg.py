#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import quote, unquote
import re
import hashlib
from collections import defaultdict
import ssl
import json
from datetime import datetime, timedelta

# ===================== 抓取 Kbro 节目数据（返回节目列表） =====================
def fetch_kbro_programs(days=7):
    print("📡 开始抓取 Kbro 频道 906 节目...")
    ssl._create_default_https_context = ssl._create_unverified_context
    base_url = "https://epg.kbro.com.tw:2543/epg/epg_program.php"
    params = {"appid": "KBRO"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kbro.com.tw/",
        "Origin": "https://www.kbro.com.tw"
    }

    programs = []
    start_date = datetime.now().date()
    date_list = [(start_date + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

    for date_str in date_list:
        params["date"] = date_str
        try:
            resp = requests.get(base_url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"   ⚠️ 抓取 {date_str} 失败: {e}")
            continue
        if not data or "PROG" not in data:
            continue
        for item in data["PROG"]:
            if item.get("channelid") != "906":
                continue
            prog_name = item.get("programname", "")
            start_str = item.get("starttime", "")
            end_str = item.get("endtime", "")
            desc_str = item.get("programdescr", "")
            if not start_str or not end_str:
                continue
            prog_date = start_str[:8] if len(start_str) >= 8 else ""
            programs.append({
                "title": prog_name,
                "start": start_str + " +0800",
                "stop": end_str + " +0800",
                "desc": desc_str,
                "date": prog_date
            })

    print(f"   ✅ 共抓取 {len(programs)} 个节目")
    return programs

# ===================== 生成格式化节目字符串（严格按模板） =====================
def format_programs(programs):
    """
    生成节目文本，每个节目格式如下（缩进2空格，子标签4空格，无多余空行）：
      <programme channel="456841" start="..." stop="...">
        <title lang="zh">...</title>
        <desc>...</desc>
        <date>...</date>
        <audio>
          <stereo>stereo</stereo>
        </audio>
      </programme>
    """
    lines = []
    for p in programs:
        lines.append(f'  <programme channel="456841" start="{p["start"]}" stop="{p["stop"]}">')
        lines.append(f'    <title lang="zh">{p["title"]}</title>')
        if p["desc"]:
            lines.append(f'    <desc>{p["desc"]}</desc>')
        lines.append(f'    <date>{p["date"]}</date>')
        lines.append('    <audio>')
        lines.append('      <stereo>stereo</stereo>')
        lines.append('    </audio>')
        lines.append('  </programme>')
    return '\n'.join(lines)

# ===================== 原有功能函数（不变） =====================
def safe_download(url):
    try:
        print(f"📥 下载: {url}")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

def fix_icon_url(root):
    for ch in root.findall('channel'):
        icon = ch.find('icon')
        if icon is not None and 'src' in icon.attrib:
            raw = icon.attrib['src']
            decoded = unquote(raw)
            if decoded.startswith('//'):
                decoded = 'https:' + decoded
            icon.attrib['src'] = decoded

def fix_display_name(root):
    for ch in root.findall('channel'):
        for name in ch.findall('display-name'):
            if name.text:
                name.text = name.text.strip()

def normalize_channel_name(name):
    if not name:
        return name
    name = re.sub(r'[（(].*?[）)]', '', name)
    name = re.sub(r'[\[【].*?[\]】]', '', name)
    name = re.sub(r'CCTV[- ]?(\d+)[ ]?(综合|财经|综艺|体育|电影|电视剧|纪录|科教|戏曲|社会与法|新闻|少儿|音乐|奥林匹克|农业农村|高清)?', r'CCTV-\1', name, flags=re.IGNORECASE)
    name = re.sub(r'CCTV(\d+)', r'CCTV-\1', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s\-_]*(高清|HD|标清|高标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[\s\-_]+$', '', name)
    return name.strip()

def simple_merge(contents):
    print("🔄 简单合并所有EPG数据（不去重）...")
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG (raw)')
    merged_root.set('generator-info-name', 'JMYG Merger')
    total_progs = 0
    total_channels = 0
    for src_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            fix_display_name(root)
            for ch in root.findall('channel'):
                merged_root.append(ch)
                total_channels += 1
            for prog in root.findall('programme'):
                merged_root.append(prog)
                total_progs += 1
            print(f"✅ 已合并 {src_name} (频道数: {len(root.findall('channel'))}, 节目数: {len(root.findall('programme'))})")
        except Exception as e:
            print(f"❌ 处理 {src_name} 出错: {e}")
    print(f"📊 简单合并后总频道数: {total_channels}, 总节目数: {total_progs}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode()

def clean_unused_channels(xml_content):
    print("🧹 开始清理无节目频道...")
    root = ET.fromstring(xml_content)
    refs = set()
    for prog in root.findall('programme'):
        ch = prog.get('channel')
        if ch:
            refs.add(ch)
    to_remove = []
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if cid and cid not in refs:
            to_remove.append(ch)
    for ch in to_remove:
        root.remove(ch)
    print(f"🧹 删除了 {len(to_remove)} 个无节目频道，剩余频道数: {len(root.findall('channel'))}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

def deduplicate_epg(xml_content):
    print("🔄 开始高级去重...")
    root = ET.fromstring(xml_content)
    new_root = ET.Element('tv')
    new_root.set('source-info-name', 'JMYG Deduped EPG')
    new_root.set('generator-info-name', 'JMYG Deduper')

    norm_to_channel = {}
    id_to_preferred = {}
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if not cid:
            continue
        name_elem = ch.find('display-name')
        raw_name = name_elem.text.strip() if name_elem is not None and name_elem.text else cid
        norm_name = normalize_channel_name(raw_name)
        if norm_name not in norm_to_channel:
            norm_to_channel[norm_name] = ch
            id_to_preferred[cid] = cid
        else:
            preferred_ch = norm_to_channel[norm_name]
            id_to_preferred[cid] = preferred_ch.get('id')

    for ch in norm_to_channel.values():
        new_root.append(ch)
    print(f"📊 频道去重后: {len(norm_to_channel)} (原 {len(root.findall('channel'))})")

    prog_groups = defaultdict(list)
    for prog in root.findall('programme'):
        orig_id = prog.get('channel')
        if not orig_id:
            continue
        preferred_id = id_to_preferred.get(orig_id, orig_id)
        start = prog.get('start', '')
        if not start:
            prog.set('channel', preferred_id)
            new_root.append(prog)
            continue
        start_minute = start[:12] if len(start) >= 12 else start
        key = (preferred_id, start_minute)
        prog_groups[key].append(prog)

    kept_count = 0
    for key, progs in prog_groups.items():
        if len(progs) == 1:
            best = progs[0]
        else:
            def score(p):
                s = 0
                if p.find('desc') is not None:
                    s += 10
                if p.find('sub-title') is not None:
                    s += 5
                title = p.find('title')
                if title is not None and title.text:
                    s += len(title.text)
                return s
            best = max(progs, key=score)
        best.set('channel', key[0])
        new_root.append(best)
        kept_count += 1

    print(f"📊 节目去重后: {kept_count} (原 {len(root.findall('programme'))})")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()

def simple_timezone_fix(xml_content):
    if xml_content:
        return xml_content.replace('+0000', '+0800').replace('UTC', '+0800')
    return xml_content

def save_data(content, filename):
    os.makedirs('epg_data', exist_ok=True)
    filepath = f'epg_data/{filename}'
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            existing = f.read()
        if existing == content:
            print(f"⏭️ 内容无变化，跳过保存: {filename}")
            return
    content_bytes = content.encode('utf-8')
    md5_hash = hashlib.md5(content_bytes).hexdigest()
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    hash_filename = f"{filename}.hash"
    with open(f'epg_data/{hash_filename}', 'w', encoding='utf-8') as f:
        f.write(md5_hash)
    print(f"💾 已保存: {filename} (大小: {len(content_bytes)/1024/1024:.2f} MB, MD5: {md5_hash})")

# ===================== 主函数 =====================
def main():
    print("🚀 开始处理EPG数据...")
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')
    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)

    # 抓取 Kbro 节目列表
    kbro_programs = fetch_kbro_programs(days=7)
    if not kbro_programs:
        print("⚠️ 未抓取到任何节目，退出")
        return

    # 生成格式化节目字符串（无多余空行，严格缩进）
    new_programs_str = format_programs(kbro_programs)

    sources = []
    if cn: sources.append(('CN', cn))
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))

    if not sources:
        print("❌ 所有 epg.pw 源下载失败")
        return

    # 合并所有源（不包含 Kbro，因为我们会单独替换）
    merged_content = simple_merge(sources)

    # 用正则替换所有 channel="456841" 的节目块
    print("🔄 替换频道 456841 的节目...")
    # 匹配从 <programme channel="456841" 到对应的 </programme>，包括中间的换行和缩进，非贪婪，匹配所有连续节目
    pattern = r'(<programme channel="456841".*?</programme>\s*)+'
    # 使用 re.DOTALL 让 . 匹配换行
    merged_content = re.sub(pattern, new_programs_str + '\n', merged_content, flags=re.DOTALL)
    print("   ✅ 替换完成")

    save_data(merged_content, 'epg_merged.xml')
    cleaned_content = clean_unused_channels(merged_content)
    save_data(cleaned_content, 'epg_merged_clean.xml')
    perfect_content = deduplicate_epg(cleaned_content)
    save_data(perfect_content, 'epg_perfect.xml')

    print("✅ 处理完成！")

if __name__ == '__main__':
    main()
