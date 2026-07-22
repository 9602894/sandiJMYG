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
    """归一化频道名称：去除后缀（高清、HD、标清、-等），保留核心名称"""
    if not name:
        return name
    # 去除末尾的常见修饰词（支持中文和英文）
    name = re.sub(r'[\s\-_]+(高清|HD|标清|高标清|付费|测试)$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(高清|HD|标清|高标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
    # 去除末尾可能的空格或连字符
    name = name.strip()
    return name

def merge_and_deduplicate(contents):
    """
    对所有源进行频道归一化去重，然后合并所有节目并去重
    """
    print("🔄 合并所有EPG数据，先归一化频道名称...")
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG')
    merged_root.set('generator-info-name', 'JMYG Deduper')

    # 用于存储：归一化名称 -> 首选频道元素（按源顺序，CN优先）
    norm_to_channel = {}
    # 用于存储：原始频道ID -> 首选频道ID
    id_to_preferred = {}
    # 用于统计
    total_channels_original = 0
    total_channels_normalized = 0

    # 第一步：遍历所有源，收集频道并建立映射
    for src_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            fix_display_name(root)
            for ch in root.findall('channel'):
                cid = ch.get('id')
                if not cid:
                    continue
                total_channels_original += 1
                # 获取频道名称（取第一个display-name）
                name_elem = ch.find('display-name')
                raw_name = name_elem.text.strip() if name_elem is not None and name_elem.text else cid
                norm_name = normalize_channel_name(raw_name)
                # 如果该归一化名称尚未出现，则作为首选
                if norm_name not in norm_to_channel:
                    norm_to_channel[norm_name] = ch
                    # 记录原始ID到首选ID的映射（首选ID即当前频道的ID）
                    id_to_preferred[cid] = cid
                else:
                    # 如果已存在，记录映射到首选ID
                    preferred_ch = norm_to_channel[norm_name]
                    preferred_id = preferred_ch.get('id')
                    id_to_preferred[cid] = preferred_id
            print(f"✅ 已读取 {src_name} 原始频道数: {len(root.findall('channel'))}")
        except Exception as e:
            print(f"❌ 处理 {src_name} 出错: {e}")

    # 第二步：将归一化后的频道加入merged_root
    for norm_name, ch in norm_to_channel.items():
        merged_root.append(ch)
    total_channels_normalized = len(norm_to_channel)
    print(f"📊 归一化后频道总数: {total_channels_normalized} (原始总数: {total_channels_original})")

    # 第三步：遍历所有源的节目，将频道ID替换为首选ID，并进行去重
    seen_progs = set()
    total_progs_added = 0
    for src_name, content in contents:
        try:
            root = ET.fromstring(content)
            for prog in root.findall('programme'):
                orig_id = prog.get('channel')
                if not orig_id:
                    continue
                preferred_id = id_to_preferred.get(orig_id, orig_id)
                start = prog.get('start', '')
                end = prog.get('end', '')
                title_elem = prog.find('title')
                title = title_elem.text if title_elem is not None and title_elem.text else ''
                key = (preferred_id, start, end, title.strip())
                if key not in seen_progs:
                    prog.set('channel', preferred_id)
                    merged_root.append(prog)
                    seen_progs.add(key)
                    total_progs_added += 1
            print(f"✅ 已处理 {src_name} 节目")
        except Exception as e:
            print(f"❌ 处理 {src_name} 节目时出错: {e}")

    print(f"📊 去重后节目总数: {total_progs_added}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode()

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

    if sources:
        merged = merge_and_deduplicate(sources)
        save_data(merged, 'epg_merged.xml')
        # 同样生成一个perfect文件，内容相同
        save_data(merged, 'epg_perfect.xml')
        print("✅ 处理完成！")
    else:
        print("❌ 所有源下载失败")

if __name__ == '__main__':
    main()
