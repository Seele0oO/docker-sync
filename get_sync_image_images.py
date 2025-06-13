#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
镜像同步规则 JSON 转换脚本
读取当前目录下的 images-run.json，将其从列表格式转换为“源镜像_url: 目标镜像_url”映射，
并写入 images_compat.json。
"""

import json
import sys

def load_rules(input_path: str):
    """从 images-run.json 中加载规则列表"""
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 无法读取 {input_path}: {e}", file=sys.stderr)
        sys.exit(1)

def transform_rules(rules):
    """
    将列表格式转换为 dict：
    {
      "source_url": "target_url" 或 ["target1", "target2", ...],
      ...
    }
    """
    mapping = {}
    for item in rules:
        src = item.get("source")
        tgt = item.get("target")
        if not src or not tgt:
            print(f"⚠️ 跳过无效条目：{item}", file=sys.stderr)
            continue
        mapping[src] = tgt
    return mapping

def write_mapping(mapping, output_path: str):
    """将转换后的映射写入 images_compat.json"""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"✅ 已成功写入 {output_path}")
    except Exception as e:
        print(f"❌ 无法写入 {output_path}: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    input_file = "images-run.json"
    output_file = "images_compat.json"

    rules = load_rules(input_file)
    mapping = transform_rules(rules)
    write_mapping(mapping, output_file)

if __name__ == "__main__":
    main()
