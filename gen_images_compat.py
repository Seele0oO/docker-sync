import json
import os
from get_target_name import get_target_image_name

# 读取 images.json
with open('images.json', 'r') as f:
    images = json.load(f)

result = {}
for item in images:
    source = item.get('source')
    versions = item.get('versions', [])
    one_time = item.get('sync-one-time', [])
    all_versions = sorted(set(versions + one_time))
    for version in all_versions:
        target = get_target_image_name(source, version)
        result[f'{source}:{version}'] = target

with open('images_compat.json', 'w') as f:
    json.dump(result, f, indent=2)
print('✅ 已生成 images_compat.json')
