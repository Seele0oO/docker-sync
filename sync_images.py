import os
import sys
import json
import subprocess
import logging
from datetime import datetime

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
    if os.path.exists(DIGEST_RECORD_FILE):
        with open(DIGEST_RECORD_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_digest_records(records):
    with open(DIGEST_RECORD_FILE, 'w') as f:
        json.dump(records, f, indent=4)

def get_target_image_name(image, version):
    name = image.get('name')
    registry = image.get('registry', 'docker.io')
    namespace = os.environ.get('ALIYUN_REGISTRY_NAMESPACE')
    if not namespace:
        logger.error("Environment variable ALIYUN_REGISTRY_NAMESPACE not set.")
        sys.exit(1)

    if registry == 'docker.io':
        if '/' in name:
            source_org, source_image = name.split('/', 1)
        else:
            source_org = 'library'
            source_image = name
        target_name = f"{source_org}-{source_image}:{version}"
    else:
        parts = name.split('/')
        if len(parts) == 1:
            source_repo = registry
            source_org = 'library'
            source_image = name
        elif len(parts) == 2:
            source_repo = registry
            source_org, source_image = parts
        elif len(parts) >= 3:
            source_repo, source_org, source_image = parts[:3]
        target_name = f"{source_repo}-{source_org}-{source_image}:{version}"
    return f"registry.cn-hangzhou.aliyuncs.com/{namespace}/{target_name}"

def sync_image(image, version, digest_records):
    registry = image.get('registry', 'docker.io')
    name = image['name']
    source_image = f"{registry}/{name}:{version}"
    target_image = get_target_image_name(image, version)

    logger.info(f"==== Syncing {source_image} ====")

    if not check_image_exists(source_image):
        logger.warning(f"{source_image} does not exist. Skipping.")
        return

    # 拉取镜像
    if not run_command(f"docker pull {source_image}"):
        logger.error(f"Failed to pull {source_image}. Skipping.")
        return

    current_digest = get_digest(source_image)
    if not current_digest:
        logger.error(f"Cannot get digest for {source_image}. Skipping.")
        return

    key = f"{registry}/{name}:{version}"
    prev_record = digest_records.get(key)

    if prev_record and prev_record["digest"] == current_digest:
        logger.info(f"{key} not changed since last sync. Skipping.")
        return

    # 打标签并推送
    if not run_command(f"docker tag {source_image} {target_image}"):
        logger.error(f"Failed to tag {source_image} as {target_image}")
        return

    if not run_command(f"docker push {target_image}"):
        logger.error(f"Failed to push {target_image}")
        return

    logger.info(f"Successfully synced {source_image} to {target_image}")
    digest_records[key] = {
        "digest": current_digest,
        "last_sync_time": str(datetime.utcnow())
    }

def main():
    try:
        with open('images.json', 'r') as f:
            images = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load images.json: {e}")
        sys.exit(1)

    digest_records = load_digest_records()

    for image in images:
        name = image.get('name')
        versions = image.get('versions', [])
        one_time = image.get('sync-one-time', [])
        all_versions = set(versions + one_time)

        for version in all_versions:
            try:
                sync_image(image, version, digest_records)
            except Exception as e:
                logger.error(f"Unexpected error syncing {name}:{version}: {e}")
                continue

    save_digest_records(digest_records)

if __name__ == '__main__':
    main()
