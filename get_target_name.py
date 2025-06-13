import json
import os

def get_target_image_name(source, version):
    """
    根据完整访问地址 source（不含版本）生成目标镜像地址，
    并将路径中的 '/' 替换为 '-'，避免多级目录
    """
    namespace = os.environ.get('ALIYUN_REGISTRY_NAMESPACE', 'LOCALTEST')  # 默认 LOCALTEST 方便本地调试
    parts = source.split('/', 1)
    repo_path = parts[1] if len(parts) == 2 else parts[0]
    safe_repo = repo_path.replace('/', '-')
    return f"registry.cn-hangzhou.aliyuncs.com/{namespace}/{safe_repo}:{version}"

if __name__ == "__main__":
    with open("images.json", "r") as f:
        images = json.load(f)
    result = {}
    for img in images:
        src = img.get("source") or img.get("name")
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