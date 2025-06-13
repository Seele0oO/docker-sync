import json

with open("images.json", "r") as f:
    images = json.load(f)

result = {}

for img in images:
    src = img["name"]
    versions = img.get("versions", [])
    one_time = img.get("sync-one-time", [])
    all_versions = sorted(set(versions + one_time))

    # 1. 只源镜像名
    result[src] = src  # 这里可以自定义目标镜像名

    # 2. 源镜像:tag
    for v in all_versions:
        result[f"{src}:{v}"] = src  # 这里可以自定义目标镜像名或带 tag

    # 3. 源镜像:tag1,tag2
    if len(all_versions) > 1:
        result[f"{src}:{','.join(all_versions)}"] = src  # 这里可以自定义目标镜像名

    # 4. 如需支持正则或 value 为 list，可在此扩展
    # 例如 result[f"{src}:/a+/"] = [src, src + "2"]

with open("images_compat.json", "w") as f:
    json.dump(result, f, indent=4)