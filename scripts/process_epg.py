#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import os
import gzip
from urllib.parse import quote

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

def merge_with_priority(contents):
    """
    合并EPG，以第一个源（CN）为主：
    - 保留CN的所有频道和节目
    - 对于其他源，只添加频道id不在CN中的频道的节目
    """
    print("🔄 按优先级合并EPG（CN优先）...")
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG EPG (CN优先)')
    merged_root.set('generator-info-name', 'JMYG Merger')

    # 先处理CN（第一个源）
    cn_name, cn_content = contents[0]
    cn_root = ET.fromstring(cn_content)
    fix_icon_url(cn_root)
    fix_display_name(cn_root)

    cn_channel_ids = set()
    for ch in cn_root.findall('channel'):
        cid = ch.get('id')
        if cid:
            cn_channel_ids.add(cid)
            merged_root.append(ch)   # 添加CN频道

    # 添加CN的节目
    cn_prog_count = 0
    for prog in cn_root.findall('programme'):
        merged_root.append(prog)
        cn_prog_count += 1
    print(f"✅ CN 频道数: {len(cn_channel_ids)}, 节目数: {cn_prog_count}")

    # 处理其他源
    for src_name, src_content in contents[1:]:
        try:
            src_root = ET.fromstring(src_content)
            fix_icon_url(src_root)
            fix_display_name(src_root)

            # 收集该源中CN没有的频道
            new_channel_ids = set()
            for ch in src_root.findall('channel'):
                cid = ch.get('id')
                if cid and cid not in cn_channel_ids:
                    merged_root.append(ch)
                    new_channel_ids.add(cid)

            # 添加这些新频道的节目
            added_progs = 0
            for prog in src_root.findall('programme'):
                ch_id = prog.get('channel')
                if ch_id and ch_id in new_channel_ids:
                    merged_root.append(prog)
                    added_progs += 1
            print(f"✅ {src_name} 新增频道数: {len(new_channel_ids)}, 新增节目数: {added_progs}")
        except Exception as e:
            print(f"❌ 处理 {src_name} 出错: {e}")

    # 最终去重（以防万一）
    total_progs = len(merged_root.findall('programme'))
    print(f"📊 合并后总节目数: {total_progs}")
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
    print(f"💾 已保存: {filename}")

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
        merged = merge_with_priority(sources)
        save_data(merged, 'epg_merged.xml')
        # 为了保持接口一致，也生成一个 perfect 文件（与 merged 相同，因为已经以CN为主）
        save_data(merged, 'epg_perfect.xml')
        print("✅ 生成完成！")
    else:
        print("❌ 所有源下载失败")

if __name__ == '__main__':
    main()
