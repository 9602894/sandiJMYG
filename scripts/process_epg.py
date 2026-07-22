#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import quote
import re

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
            parts = icon.attrib['src'].split('/')
            icon.attrib['src'] = '/'.join(quote(p) for p in parts)

def fix_display_name(root):
    for ch in root.findall('channel'):
        for name in ch.findall('display-name'):
            if name.text:
                name.text = name.text.strip()

def normalize_channel_name(name):
    if not name:
        return name
    # 去除末尾常见后缀（高清、HD、标清等）
    name = re.sub(r'[\s\-_]+(高清|HD|标清|高标清|付费|测试)$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(高清|HD|标清|高标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
    return name.strip()

def simple_merge(contents):
    """简单合并所有源，不做任何去重"""
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
            # 直接添加所有频道和节目
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

def deduplicate_epg(xml_content):
    """对合并后的XML进行去重：频道归一化 + 节目精确去重 (start, end, title)"""
    print("🔄 开始去重（频道归一化 + 节目精确去重）...")
    root = ET.fromstring(xml_content)
    new_root = ET.Element('tv')
    new_root.set('source-info-name', 'JMYG Deduped EPG')
    new_root.set('generator-info-name', 'JMYG Deduper')
    
    # 1. 频道归一化合并（保留第一个出现的）
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
    
    # 添加去重后的频道
    for ch in norm_to_channel.values():
        new_root.append(ch)
    print(f"📊 频道去重后: {len(norm_to_channel)} (原 {len(root.findall('channel'))})")
    
    # 2. 节目精确去重 (channel, start, end, title)
    seen = set()
    total_kept = 0
    for prog in root.findall('programme'):
        orig_id = prog.get('channel')
        if not orig_id:
            continue
        preferred_id = id_to_preferred.get(orig_id, orig_id)
        start = prog.get('start', '')
        end = prog.get('end', '')
        title_elem = prog.find('title')
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else ''
        key = (preferred_id, start, end, title)
        if key not in seen:
            prog.set('channel', preferred_id)
            new_root.append(prog)
            seen.add(key)
            total_kept += 1
    print(f"📊 节目去重后: {total_kept} (原 {len(root.findall('programme'))})")
    
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()

def simple_timezone_fix(xml_content):
    if xml_content:
        return xml_content.replace('+0000', '+0800').replace('UTC', '+0800')
    return xml_content

def save_data(content, filename):
    os.makedirs('epg_data', exist_ok=True)
    with open(f'epg_data/{filename}', 'w', encoding='utf-8') as f:
        f.write(content)
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    size = len(content.encode('utf-8'))
    print(f"💾 已保存: {filename} ({size/1024/1024:.2f} MB)")

def main():
    print("🚀 开始处理EPG数据...")
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')
    
    cn = simple_timezone_fix(raw_cn)
    tw = simple_timezone_fix(raw_tw)
    hk = simple_timezone_fix(raw_hk)
    
    sources = []
    if cn: sources.append(('CN', cn))
    if tw: sources.append(('TW', tw))
    if hk: sources.append(('HK', hk))
    
    if not sources:
        print("❌ 所有源下载失败")
        return
    
    # 1. 生成原始合并文件（不去重）
    merged_content = simple_merge(sources)
    save_data(merged_content, 'epg_merged.xml')
    
    # 2. 对合并内容进行去重，生成 perfect
    perfect_content = deduplicate_epg(merged_content)
    save_data(perfect_content, 'epg_perfect.xml')
    
    print("✅ 处理完成！")

if __name__ == '__main__':
    main()
