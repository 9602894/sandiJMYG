def deduplicate_epg(xml_content):
    print("🔄 开始去重（频道归一化 + 选择最全频道）...")
    root = ET.fromstring(xml_content)
    new_root = ET.Element('tv')
    new_root.set('source-info-name', 'JMYG Deduped EPG')
    new_root.set('generator-info-name', 'JMYG Deduper')

    # 1. 收集所有频道及其节目（先找出每个频道关联的节目）
    # 建立频道ID -> 频道元素 的映射
    channel_map = {}
    for ch in root.findall('channel'):
        cid = ch.get('id')
        if cid:
            channel_map[cid] = ch

    # 建立频道ID -> 节目列表的映射
    channel_progs = {}
    for prog in root.findall('programme'):
        cid = prog.get('channel')
        if cid:
            channel_progs.setdefault(cid, []).append(prog)

    # 2. 按归一化名称分组
    groups = {}  # norm_name -> list of (cid, channel_element, program_count)
    for cid, ch in channel_map.items():
        name_elem = ch.find('display-name')
        raw_name = name_elem.text.strip() if name_elem is not None and name_elem.text else cid
        norm_name = normalize_channel_name(raw_name)
        progs = channel_progs.get(cid, [])
        groups.setdefault(norm_name, []).append((cid, ch, len(progs)))

    print(f"📊 归一化后频道组数: {len(groups)} (原始频道数: {len(channel_map)})")

    # 3. 对每组选择节目数最多的频道
    selected_channels = []  # 存放选中的频道元素
    id_to_preferred = {}    # 原始ID -> 首选ID（选中的频道的ID）
    for norm_name, items in groups.items():
        # 按节目数降序，节目数相同则按源顺序（原顺序）
        items.sort(key=lambda x: x[2], reverse=True)
        best_cid, best_ch, best_count = items[0]
        selected_channels.append(best_ch)
        for cid, _, _ in items:
            id_to_preferred[cid] = best_cid
        print(f"   {norm_name}: 共 {len(items)} 个频道，选择 {best_cid} (节目数 {best_count})")

    # 4. 将选中的频道加入新根
    for ch in selected_channels:
        new_root.append(ch)

    # 5. 重新处理节目：只保留选中频道的节目，并去重（精确去重）
    seen = set()
    total_kept = 0
    for prog in root.findall('programme'):
        orig_id = prog.get('channel')
        if not orig_id:
            continue
        preferred_id = id_to_preferred.get(orig_id)
        if not preferred_id:
            continue  # 该频道未被选中，跳过
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

    print(f"📊 最终频道数: {len(selected_channels)}, 最终节目数: {total_kept}")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(new_root, encoding='utf-8').decode()
