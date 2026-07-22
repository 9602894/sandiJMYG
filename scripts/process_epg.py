#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import quote
import re
from collections import defaultdict

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
    """仅去除清晰度后缀（高清、HD、标清等），保留数字等核心标识"""
    if not name:
        return name
    # 去除末尾的清晰度标识，支持多种写法
    name = re.sub(r'[\s\-_]*(高清|HD|标清|高标清|付费|测试)[\s\-_]*$', '', name, flags=re.IGNORECASE)
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

def deduplicate_epg(xml_content):
    print("🔄 开始智能去重（按归一化名称分组，保留节目最多的ID）...")
    root = ET.fromstring(xml_content)
    new_root = ET.Element('tv')
    new_root.set('source-info-name', 'JMYG Deduped EPG')
    new_root.set('generator-info-name', 'JMYG Deduper')

    # 1. 收集所有频道及其节目（通过统计节目数量来评估哪个ID更全）
    # 先建立所有频道的原始ID、归一化名称、节目列表（根据后续节目遍历）
    # 因为节目在root中，我们需要先扫描所有节目，按原始ID分组计数，同时保留节目元素引用
    # 但为了后续合并，我们需要把节目按ID分类，并记录原始节目元素

    # 首先建立 id -> channel element 映射
    id_to_channel = {}
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if cid:
            id_to_channel[cid] = ch

    # 按原始ID分组节目
    id_to_programs = defaultdict(list)
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        if cid:
            id_to_programs[cid].append(prog)

    # 2. 按归一化名称分组，每组选择节目最多的ID
    norm_to_ids = defaultdict(list)  # norm_name -> list of ids
    for cid, ch in id_to_channel.items():
        name_elem = ch.find('display-name')
        raw_name = name_elem.text.strip() if name_elem is not None and name_elem.text else cid
        norm_name = normalize_channel_name(raw_name)
        norm_to_ids[norm_name].append(cid)

    # 对每组，选出节目数量最多的ID
    norm_to_best_id = {}
    for norm_name, ids in norm_to_ids.items():
        best_id = max(ids, key=lambda cid: len(id_to_programs.get(cid, [])))
        norm_to_best_id[norm_name] = best_id

    # 同时建立所有ID到最佳ID的映射（用于迁移节目）
    id_to_preferred = {}
    for norm_name, ids in norm_to_ids.items():
        best_id = norm_to_best_id[norm_name]
        for cid in ids:
            id_to_preferred[cid] = best_id

    # 3. 添加保留的频道（只添加最佳ID的频道元素，但需更新display-name为归一化名称？保留原样也可）
    # 我们只添加最佳ID的频道，并确保其display-name是最清晰的（可选，保留原样）
    added_channels = set()
    for norm_name, best_id in norm_to_best_id.items():
        ch = id_to_channel[best_id]
        new_root.append(ch)
        added_channels.add(best_id)
    # 注意：可能有些原始频道没有节目（id_to_programs为空），但也被选为best，但无所谓

    print(f"📊 频道去重后: {len(norm_to_best_id)} (原 {len(id_to_channel)})")

    # 4. 合并所有节目到最佳ID，并去重
    seen = set()
    total_kept = 0
    for orig_id, progs in id_to_programs.items():
        preferred_id = id_to_preferred.get(orig_id, orig_id)
        for prog in progs:
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

    merged_content = simple_merge(sources)
    save_data(merged_content, 'epg_merged.xml')

    perfect_content = deduplicate_epg(merged_content)
    save_data(perfect_content, 'epg_perfect.xml')

    print("✅ 处理完成！")

if __name__ == '__main__':
    main()
