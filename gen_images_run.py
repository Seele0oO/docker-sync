import json
import os
from get_target_name import get_target_image_name

# 读取 images.json
with open('images.json', 'r') as f:
    images = json.load(f)

namespace = os.environ.get('ALIYUN_REGISTRY_NAMESPACE')
if not namespace:
    raise Exception('ALIYUN_REGISTRY_NAMESPACE not set')

result = []
for item in images:
    source = item['source']
    versions = item['versions']
    for version in versions:
        target = get_target_image_name(source, version)
        result.append({
            'source': source + ':' + version,
            'target': target
        })

with open('images-run.json', 'w') as f:
    json.dump(result, f, indent=2)
