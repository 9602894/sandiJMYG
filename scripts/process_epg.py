#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import gzip
from urllib.parse import quote

def safe_download(url):
    """安全下载EPG数据"""
    try:
        print(f"📥 下载: {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return response.text
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

def fix_icon_url(root):
    """对icon的src进行URL编码，避免台标乱码"""
    for channel in root.findall('channel'):
        icon = channel.find('icon')
        if icon is not None and 'src' in icon.attrib:
            original_url = icon.attrib['src']
            parts = original_url.split('/')
            encoded_parts = [quote(p) for p in parts]
            icon.attrib['src'] = '/'.join(encoded_parts)

def fix_display_name(root):
    """确保display-name中文安全"""
    for channel in root.findall('channel'):
        for name in channel.findall('display-name'):
            if name.text:
                name.text = name.text.strip()

def merge_epg_data(contents):
    """
    合并多个EPG数据源（不进行去重）
    contents: list of (source_name, xml_content)
    """
    print("🔄 合并EPG数据...")
    
    merged_root = ET.Element('tv')
    merged_root.set('source-info-name', 'JMYG Merged EPG')
    merged_root.set('source-info-url', 'https://github.com/9602894/JMYG')
    merged_root.set('generator-info-name', 'JMYG EPG Merger')
    
    added_channels = set()
    total_progs = 0
    
    for source_name, content in contents:
        try:
            root = ET.fromstring(content)
            fix_icon_url(root)
            fix_display_name(root)
            
            for channel in root.findall('channel'):
                channel_id = channel.get('id')
                if channel_id and channel_id not in added_channels:
                    merged_root.append(channel)
                    added_channels.add(channel_id)
            
            for programme in root.findall('programme'):
                merged_root.append(programme)
                total_progs += 1
                
            print(f"✅ 已合并 {source_name} 数据")
        except Exception as e:
            print(f"❌ 处理 {source_name} 数据时出错: {e}")
    
    print(f"📊 合并后总节目数: {total_progs}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged_root, encoding='utf-8').decode(), total_progs

def deduplicate_epg(xml_content, original_count):
    """
    对合并后的EPG进行去重整理
    - 频道按 id 去重，保留最先出现的
    - 节目按 (channel, start, end, title) 去重，保留最先出现的
    """
    try:
        root = ET.fromstring(xml_content)
        new_root = ET.Element('tv')
        # 复制根属性
        for attr, val in root.attrib.items():
            new_root.set(attr, val)
        
        # 去重 channel
        seen_channels = set()
        for channel in root.findall('channel'):
            cid = channel.get('id')
            if cid and cid not in seen_channels:
                new_root.append(channel)
                seen_channels.add(cid)
        
        # 去重 programme（使用更严格的键：包含title）
        seen_progs = set()
        kept_count = 0
        for prog in root.findall('programme'):
            channel = prog.get('channel')
            start = prog.get('start')
            end = prog.get('end')
            # 获取节目名称（取第一个title）
            title_elem = prog.find('title')
            title = title_elem.text if title_elem is not None and title_elem.text else ''
            if channel and start and end:
                key = (channel, start, end, title.strip())
                if key not in seen_progs:
                    new_root.append(prog)
                    seen_progs.add(key)
                    kept_count += 1
            else:
                # 若缺少关键字段，仍保留
                new_root.append(prog)
                kept_count += 1
        
        print(f"📊 去重后节目数: {kept_count} (去重前: {original_count}, 减少: {original_count - kept_count})")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()
    except Exception as e:
        print(f"❌ 去重失败: {e}")
        return xml_content  # 返回原内容

def simple_timezone_fix(xml_content):
    """时区修复为东八区"""
    if xml_content:
        return xml_content.replace('+0000', '+0800').replace('UTC', '+0800')
    return xml_content

def save_data(content, filename):
    """保存XML及压缩版本"""
    os.makedirs('epg_data', exist_ok=True)
    
    with open(f'epg_data/{filename}', 'w', encoding='utf-8') as f:
        f.write(content)
    
    with gzip.open(f'epg_data/{filename}.gz', 'wt', encoding='utf-8') as f:
        f.write(content)
    
    print(f"💾 已保存: {filename}")

def main():
    print("🚀 开始处理EPG数据...")
    
    # 下载三个数据源（按优先级顺序：CN 优先）
    raw_cn = safe_download('https://epg.pw/xmltv/epg_CN.xml')
    raw_tw = safe_download('https://epg.pw/xmltv/epg_TW.xml')
    raw_hk = safe_download('https://epg.pw/xmltv/epg_HK.xml')
    
    # 时区修复
    cn_content = simple_timezone_fix(raw_cn)
    tw_content = simple_timezone_fix(raw_tw)
    hk_content = simple_timezone_fix(raw_hk)
    
    # 构建有效源列表（顺序决定去重时的优先级）
    sources = []
    if cn_content:
        sources.append(('CN', cn_content))
    if tw_content:
        sources.append(('TW', tw_content))
    if hk_content:
        sources.append(('HK', hk_content))
    
    if sources:
        # 1. 生成合并文件（含重复）
        merged_content, total_progs = merge_epg_data(sources)
        if merged_content:
            save_data(merged_content, 'epg_merged.xml')
            print("✅ EPG数据合并完成！")
            
            # 2. 生成去重后的完美文件
            perfect_content = deduplicate_epg(merged_content, total_progs)
            save_data(perfect_content, 'epg_perfect.xml')
            print("✅ EPG数据去重整理完成，已生成 epg_perfect.xml")
        else:
            print("❌ 合并失败，使用第一个有效源作为备用")
            save_data(sources[0][1], 'epg_merged.xml')
            # 对备用源也进行去重（先解析统计）
            temp_root = ET.fromstring(sources[0][1])
            temp_count = len(temp_root.findall('programme'))
            perfect_content = deduplicate_epg(sources[0][1], temp_count)
            save_data(perfect_content, 'epg_perfect.xml')
    else:
        print("❌ 所有数据源下载失败，无法生成EPG")

    print("🎉 EPG处理完成！")

if __name__ == '__main__':
    main()
