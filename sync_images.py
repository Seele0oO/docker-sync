import json
import os
import subprocess
import sys
import requests
import logging
from datetime import datetime

# 设置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def run_command(command, capture_output=True):
    """运行命令并捕获输出，使用日志记录输出"""
    try:
        logger.info(f"Running command: {command}")
        result = subprocess.run(command, shell=True, check=True, capture_output=capture_output, text=True)
        if result.stdout:
            logger.info(f"Command output: {result.stdout.strip()}")
        if result.stderr:
            logger.error(f"Command error: {result.stderr.strip()}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Error executing command: {command}")
        logger.error(f"Error details: {e}")
        logger.error(f"Standard Output: {e.stdout}")
        logger.error(f"Standard Error: {e.stderr}")
        return None

def get_digest(image_name):
    """从镜像中获取digest"""
    inspect_cmd = f"docker inspect --format='{{{{.RepoDigests}}}}' {image_name}"
    digest = run_command(inspect_cmd)
    if digest:
        # RepoDigests 返回的格式是一个列表，获取第一个项即为digest
        return digest.split()[0].split('@')[1]  # 获取sha256:<digest>部分
    return None

def get_target_image_name(image, version):
    """生成目标镜像名称"""
    name = image.get('name')
    registry = image.get('registry', 'docker.io')
    
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
    
    return f"registry.cn-hangzhou.aliyuncs.com/{os.environ['ALIYUN_REGISTRY_NAMESPACE']}/{target_name}"

def save_sync_success(sync_data):
    """保存同步成功的信息到 sync_success.json"""
    sync_filename = "sync_success.json"
    try:
        # 如果文件存在，先读取现有数据
        if os.path.exists(sync_filename):
            with open(sync_filename, 'r') as f:
                existing_data = json.load(f)
        else:
            existing_data = []

        # 将新数据添加到现有数据
        existing_data.append(sync_data)

        # 写入文件
        with open(sync_filename, 'w') as f:
            json.dump(existing_data, f, indent=4)
        logger.info(f"Sync success data saved to {sync_filename}")
    except Exception as e:
        logger.error(f"Error saving sync success data: {e}")
        sys.exit(1)

def save_status(task_status):
    """保存任务执行状态到 status.json"""
    status_filename = "status.json"
    try:
        with open(status_filename, 'w') as f:
            json.dump(task_status, f, indent=4)
        logger.info(f"Task status saved to {status_filename}")
    except Exception as e:
        logger.error(f"Error saving task status data: {e}")
        sys.exit(1)

def load_sync_success():
    """加载同步成功的记录"""
    sync_filename = "sync_success.json"
    if os.path.exists(sync_filename):
        try:
            with open(sync_filename, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading sync success data: {e}")
            return []
    return []

def main():
    task_status = {"timestamp": str(datetime.utcnow()), "images": []}
    sync_success_data = load_sync_success()

    try:
        with open('images.json', 'r') as f:
            images = json.load(f)
    except FileNotFoundError:
        logger.error("Error: images.json file not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error("Error: images.json file is not a valid JSON.")
        sys.exit(1)

    for image in images:
        name = image.get('name')
        versions = image.get('versions', [])
        sync_one_time_versions = image.get('sync-one-time', [])
        registry = image.get('registry', 'docker.io')

        image_status = {"name": name, "versions": {}, "registry": registry}
        task_status["images"].append(image_status)

        # 同步 `sync-one-time` 中的标签（一次性同步）
        for version in sync_one_time_versions:
            # 检查该版本是否已同步
            synced = False
            for sync in sync_success_data:
                if sync["image"] == f"{registry}/{name}:{version}":
                    synced = True
                    logger.info(f"Image {registry}/{name}:{version} already synced, skipping.")
                    break

            if synced:
                continue

            logger.info(f"Processing one-time sync for image: {name}:{version}")
            source_image = f"{registry}/{name}:{version}"
            target_image = get_target_image_name(image, version)

            # 拉取源镜像
            logger.info(f"Pulling image {source_image}...")
            pull_cmd = f"docker pull {source_image}"
            run_command(pull_cmd)

            # 打标签后推送到阿里云仓库
            logger.info(f"Tagging image {source_image} as {target_image}...")
            tag_cmd = f"docker tag {source_image} {target_image}"
            run_command(tag_cmd)

            logger.info(f"Pushing image {target_image} to Aliyun...")
            push_cmd = f"docker push {target_image}"
            run_command(push_cmd)

            image_status["versions"][version] = "Successfully synced"
            logger.info(f"Successfully synced {source_image} to {target_image}")

            # 记录同步成功的信息
            sync_data = {
                "image": source_image,
                "digest": get_digest(source_image),
                "sync_time": str(datetime.utcnow())
            }
            save_sync_success(sync_data)

        # 同步 `versions` 中的标签（始终同步）
        for version in versions:
            logger.info(f"Processing always-sync for image: {name}:{version}")
            source_image = f"{registry}/{name}:{version}"
            target_image = get_target_image_name(image, version)

            # 拉取源镜像
            logger.info(f"Pulling image {source_image}...")
            pull_cmd = f"docker pull {source_image}"
            run_command(pull_cmd)

            # 打标签后推送到阿里云仓库
            logger.info(f"Tagging image {source_image} as {target_image}...")
            tag_cmd = f"docker tag {source_image} {target_image}"
            run_command(tag_cmd)

            logger.info(f"Pushing image {target_image} to Aliyun...")
            push_cmd = f"docker push {target_image}"
            run_command(push_cmd)

            image_status["versions"][version] = "Successfully synced"
            logger.info(f"Successfully synced {source_image} to {target_image}")

            # 记录同步成功的信息
            sync_data = {
                "image": source_image,
                "digest": get_digest(source_image),
                "sync_time": str(datetime.utcnow())
            }
            save_sync_success(sync_data)

    # 保存任务执行状态到 status.json
    save_status(task_status)

if __name__ == "__main__":
    main()
