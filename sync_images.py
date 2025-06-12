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
            digest = output.split()[0].split('@')[1]
            return digest
        except Exception:
            return None
    return None

def load_digest_records():
    if not os.path.exists(DIGEST_RECORD_FILE):
        return {}
    try:
        with open(DIGEST_RECORD_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception:
        return {}

def save_digest_records(records):
    with open(DIGEST_RECORD_FILE, 'w') as f:
        json.dump(records, f, indent=4)

def get_target_image_name(source_name, version):
    """根据完整访问地址 source_name（不含版本）生成目标镜像地址"""
    namespace = os.environ.get('ALIYUN_REGISTRY_NAMESPACE')
    if not namespace:
        logger.error("Environment variable ALIYUN_REGISTRY_NAMESPACE not set.")
        sys.exit(1)
    # 去除源地址中的 registry 域名，只保留仓库路径部分
    if '/' in source_name:
        repo_path = source_name.split('/', 1)[1]
    else:
        repo_path = source_name
    return f"registry.cn-hangzhou.aliyuncs.com/{namespace}/{repo_path}:{version}"

def local_image_exists(image_name):
    """检查本地是否存在该镜像"""
    return run_command(f"docker image inspect {image_name}") is not None

def sync_image(image, version, digest_records):
    name = image['name']  # 现在 name 已经是去掉版本号的完整访问地址
    source_image = f"{name}:{version}"
    target_image = get_target_image_name(name, version)

    logger.info(f"==== Syncing {source_image} ====")

    # Step 1: 镜像存在性校验
    if not check_image_exists(source_image):
        logger.warning(f"{source_image} does not exist on remote. Skipping.")
        return

    # Step 2: 拉取镜像
    if not run_command(f"docker pull {source_image}"):
        logger.error(f"Failed to pull {source_image}. Skipping.")
        return

    # Step 3: 本地镜像确认
    if not local_image_exists(source_image):
        logger.error(f"{source_image} not found locally after pull. Skipping.")
        return

    # Step 4: 获取当前镜像 digest
    current_digest = get_digest(source_image)
    if not current_digest:
        logger.error(f"Cannot get digest for {source_image}. Skipping.")
        return

    # Step 5: 检查 digest 是否变化
    key = source_image
    prev_record = digest_records.get(key)
    if prev_record and prev_record["digest"] == current_digest:
        logger.info(f"{key} not changed since last sync. Skipping.")
        return

    # Step 6: 打标签
    if not run_command(f"docker tag {source_image} {target_image}"):
        logger.error(f"Failed to tag {source_image} as {target_image}")
        return

    # Step 7: 推送镜像
    if not run_command(f"docker push {target_image}"):
        logger.error(f"Failed to push {target_image}")
        return

    # Step 8: 成功记录
    logger.info(f"Successfully synced {source_image} to {target_image}")
    digest_records[key] = {
        "digest": current_digest,
        "last_sync_time": datetime.utcnow().isoformat()
    }

def send_wecom_notification(summary: dict):
    key = os.environ.get("WECOM_WEBHOOK_KEY")
    if not key:
        logger.warning("No WECOM_WEBHOOK_KEY found in env, skipping notification.")
        return

    webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    success = summary.get("success", 0)
    failed = summary.get("failed", 0)
    total = success + failed

    lines = [
        f"【Docker 镜像同步报告】",
        f"🕒 时间: {datetime.utcnow().isoformat()} UTC",
        f"📦 总任务数: {total}",
        f"✅ 成功: {success}   ❌ 失败: {failed}",
        "",
        "📄 明细："
    ]
    for item in summary.get("details", []):
        status_icon = "✅" if item["status"] == "success" else "❌"
        lines.append(f"{status_icon} {item['image']}:{item['tag']}")

    payload = {
        "msgtype": "text",
        "text": {
            "content": "\n".join(lines)
        }
    }
    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info("WeCom notification sent.")
        else:
            logger.warning(f"WeCom webhook failed: {res.status_code} - {res.text}")
    except Exception as e:
        logger.error(f"Failed to send WeCom notification: {e}")

def main():
    try:
        with open('images.json', 'r') as f:
            images = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load images.json: {e}")
        sys.exit(1)

    digest_records = load_digest_records()
    summary = {"success": 0, "failed": 0, "details": []}

    for image in images:
        name = image.get('name')
        versions = image.get('versions', [])
        one_time = image.get('sync-one-time', [])
        all_versions = set(versions + one_time)
        for version in all_versions:
            try:
                sync_image(image, version, digest_records)
                summary["success"] += 1
                summary["details"].append({
                    "image": name,
                    "tag": version,
                    "status": "success"
                })
            except Exception as e:
                logger.error(f"Unexpected error syncing {name}:{version}: {e}")
                summary["failed"] += 1
                summary["details"].append({
                    "image": name,
                    "tag": version,
                    "status": "failed"
                })
                continue

    save_digest_records(digest_records)
    send_wecom_notification(summary)

if __name__ == "__main__":
    main()
