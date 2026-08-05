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

# ===================== 新增：抓取 Kbro 频道 906 =====================
def fetch_kbro_epg(days=7):
    """
    从 Kbro API 抓取频道 906 的节目，转换为 XMLTV 格式。
    返回完整的 XML 字符串（包含频道和节目），频道 ID 已改为 456841。
    """
    print("📡 开始抓取 Kbro 频道 906 节目...")
    ssl._create_default_https_context = ssl._create_unverified_context
    base_url = "https://epg.kbro.com.tw:2543/epg/epg_program.php"
    params = {"appid": "KBRO"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.kbro.com.tw/",
        "Origin": "https://www.kbro.com.tw"
    }

    # 创建根元素
    tv = ET.Element("tv")
    tv.set("generator-info-name", "Kbro EPG Grabber")
    tv.set("source-info-name", "Kbro")

    # 添加频道（ID 改为 456841）
    channel = ET.SubElement(tv, "channel", id="456841")
    display_name = ET.SubElement(channel, "display-name", lang="TW")
    display_name.text = "驚豔成人電影台"

    start_date = datetime.now().date()
    date_list = [(start_date + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

    total_progs = 0
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
            start_str = item.get("starttime", "")   # 格式: YYYYMMDDHHMMSS
            end_str = item.get("endtime", "")
            desc_str = item.get("programdescr", "")
            if not start_str or not end_str:
                continue

            # 添加时区 +0800
            start_xml = start_str + " +0800"
            stop_xml = end_str + " +0800"

            programme = ET.SubElement(
                tv,
                "programme",
                channel="456841",
                start=start_xml,
                stop=stop_xml
            )
            title = ET.SubElement(programme, "title", lang="zh")
            title.text = prog_name
            if desc_str:
                desc = ET.SubElement(programme, "desc", lang="zh")
                desc.text = desc_str
            total_progs += 1

    print(f"   ✅ 共抓取 {total_progs} 个节目")
    # 生成 XML 字符串
    xml_str = ET.tostring(tv, encoding="utf-8").decode()
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

# ===================== 原脚本函数（未改动） =====================
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
    print(f"💾 哈希文件: {hash_filename}")

# ===================== 主函数（修改） =====================
def main():
    print("🚀 开始处理EPG数据...")

    # 1. 下载 epg.pw 数据
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')

    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)

    # 2. 抓取 Kbro 频道 906 数据（新增）
    kbro_xml = fetch_kbro_epg(days=7)  # 可调整天数

    sources = []
    if cn: sources.append(('CN', cn))
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))
    if kbro_xml: sources.append(('KBRO', kbro_xml))

    if not sources:
        print("❌ 所有源下载失败")
        return

    # 3. 简单合并
    merged_content = simple_merge(sources)

    # 4. 替换 channel="456841" 的节目（用 Kbro 数据替换原有节目）
    print("🔄 替换频道 456841 的节目为 Kbro 抓取数据...")
    root = ET.fromstring(merged_content)

    # 删除所有原有 channel="456841" 的节目
    to_remove = []
    for prog in root.findall('programme'):
        if prog.get('channel') == '456841':
            to_remove.append(prog)
    for prog in to_remove:
        root.remove(prog)
    print(f"   🗑️ 删除了 {len(to_remove)} 个原有节目")

    # 从 kbro_xml 中提取节目并加入（频道已经存在）
    if kbro_xml:
        kbro_root = ET.fromstring(kbro_xml)
        for prog in kbro_root.findall('programme'):
            root.append(prog)
        print(f"   ✅ 添加了 {len(kbro_root.findall('programme'))} 个新节目")

    # 重新生成 merged_content
    merged_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='utf-8').decode()

    # 5. 后续处理
    save_data(merged_content, 'epg_merged.xml')
    cleaned_content = clean_unused_channels(merged_content)
    save_data(cleaned_content, 'epg_merged_clean.xml')
    perfect_content = deduplicate_epg(cleaned_content)
    save_data(perfect_content, 'epg_perfect.xml')

    print("✅ 处理完成！")

if __name__ == '__main__':
    main()
