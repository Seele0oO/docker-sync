import os
import sys
import json
import subprocess
import logging
from datetime import datetime
import requests

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

DIGEST_RECORD_FILE = "digest_records.json"

def run_command(command, capture_output=True):
    try:
        logger.info(f"Running: {command}")
        result = subprocess.run(command, shell=True, check=True, capture_output=capture_output, text=True)
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.stderr:
            logger.error(result.stderr.strip())
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {command}")
        logger.error(f"Stdout: {e.stdout}")
        logger.error(f"Stderr: {e.stderr}")
        return None

def check_image_exists(image):
    """使用 docker manifest inspect 判断镜像是否存在"""
    return run_command(f"docker manifest inspect {image}") is not None

def get_digest(image):
    """获取 docker 镜像的 digest"""
    inspect_cmd = f"docker inspect --format='{{{{.RepoDigests}}}}' {image}"
    output = run_command(inspect_cmd)
    if output:
        try:
            return output.split()[0].split('@')[1]
        except Exception:
            return None
    return None

def load_digest_records():
    if not os.path.exists(DIGEST_RECORD_FILE):
        return {}
    try:
        with open(DIGEST_RECORD_FILE, 'r') as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def save_digest_records(records):
    with open(DIGEST_RECORD_FILE, 'w') as f:
        json.dump(records, f, indent=4)

def get_local_repo(source_name):
    """
    从完整访问地址中提取本地镜像名:
    - 如果带 registry，去掉 registry 部分
    - 去掉 official namespace 'library'
    """
    parts = source_name.split('/')
    # 去掉 registry 部分
    if '.' in parts[0] or ':' in parts[0]:
        repo_parts = parts[1:]
    else:
        repo_parts = parts
    # 去掉 library 前缀
    if len(repo_parts) > 1 and repo_parts[0] == 'library':
        repo_parts = repo_parts[1:]
    return '/'.join(repo_parts)

def get_target_image_name(source_name, version):
    """
    根据完整访问地址 source_name（不含版本）生成目标镜像地址，
    并将路径中的 '/' 替换为 '-'，避免多级目录
    """
    namespace = os.environ.get('ALIYUN_REGISTRY_NAMESPACE')
    if not namespace:
        logger.error("Environment variable ALIYUN_REGISTRY_NAMESPACE not set.")
        sys.exit(1)
    parts = source_name.split('/', 1)
    repo_path = parts[1] if len(parts) == 2 else parts[0]
    safe_repo = repo_path.replace('/', '-')
    return f"registry.cn-hangzhou.aliyuncs.com/{namespace}/{safe_repo}:{version}"

def local_image_exists(image_name):
    """检查本地是否存在该镜像"""
    return run_command(f"docker image inspect {image_name}") is not None

def sync_image(image, version, digest_records):
    source = image['name']                 # e.g. docker.io/library/nginx or my.registry.com/org/img
    source_image = f"{source}:{version}"   # fully qualified for pull/check
    local_repo = get_local_repo(source)    # e.g. nginx or org/img
    local_image = f"{local_repo}:{version}"
    target_image = get_target_image_name(source, version)

    logger.info(f"==== Syncing {source_image} ====")

    # 1. 检查远端是否存在
    if not check_image_exists(source_image):
        logger.warning(f"{source_image} does not exist remotely. Skipping.")
        return

    # 2. 拉取镜像
    if not run_command(f"docker pull {source_image}"):
        logger.error(f"Failed to pull {source_image}. Skipping.")
        return

    # 3. 确认本地镜像（使用 local_image 名称）
    if not local_image_exists(local_image):
        logger.error(f"{local_image} not found locally after pull. Skipping.")
        return

    # 4. 获取 digest
    current_digest = get_digest(local_image)
    if not current_digest:
        logger.error(f"Cannot get digest for {local_image}. Skipping.")
        return

    # 5. 判断是否变化
    key = source_image
    prev = digest_records.get(key)
    if prev and prev.get("digest") == current_digest:
        logger.info(f"{key} not changed since last sync. Skipping.")
        return

    # 6. 打标签
    if not run_command(f"docker tag {local_image} {target_image}"):
        logger.error(f"Failed to tag {local_image} as {target_image}")
        return

    # 7. 推送
    if not run_command(f"docker push {target_image}"):
        logger.error(f"Failed to push {target_image}")
        return

    # 8. 记录
    logger.info(f"Successfully synced {local_image} → {target_image}")
    digest_records[key] = {
        "digest": current_digest,
        "last_sync_time": datetime.utcnow().isoformat() + "Z"
    }

def send_wecom_notification(summary: dict):
    key = os.environ.get("WECOM_WEBHOOK_KEY")
    if not key:
        logger.warning("No WECOM_WEBHOOK_KEY, skipping notification.")
        return
    webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    total = summary.get("success",0) + summary.get("failed",0)
    lines = [
        "【Docker 镜像同步报告】",
        f"🕒 {datetime.utcnow().isoformat()}Z UTC",
        f"📦 Total: {total}  ✅ {summary.get('success',0)}  ❌ {summary.get('failed',0)}",
        "",
        "明细："
    ]
    for d in summary.get("details",[]):
        icon = "✅" if d["status"]=="success" else "❌"
        lines.append(f"{icon} {d['image']}:{d['tag']}")
    payload = {"msgtype":"text","text":{"content":"\n".join(lines)}}
    try:
        r = requests.post(webhook, json=payload, timeout=10)
        if r.status_code==200:
            logger.info("WeCom notification sent.")
        else:
            logger.warning(f"WeCom failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"WeCom exception: {e}")

def main():
    try:
        with open('images.json','r') as f:
            images = json.load(f)
    except Exception as e:
        logger.error(f"Load images.json error: {e}")
        sys.exit(1)

    records = load_digest_records()
    summary = {"success":0,"failed":0,"details":[]}

    for img in images:
        name = img.get('name')
        versions = img.get('versions',[])
        one_time = img.get('sync-one-time',[])
        for v in set(versions + one_time):
            try:
                sync_image(img, v, records)
                summary["success"] += 1
                summary["details"].append({"image": name,"tag": v,"status":"success"})
            except Exception as e:
                logger.error(f"Error syncing {name}:{v}: {e}")
                summary["failed"] += 1
                summary["details"].append({"image": name,"tag": v,"status":"failed"})
    save_digest_records(records)
    send_wecom_notification(summary)

if __name__ == "__main__":
    main()
