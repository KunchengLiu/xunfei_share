import requests
import os
import time

# --- 配置 ---

# 1. 目标网站的根 URL
BASE_URL = "https://share.feixu.site"

# 2. AList API v3 的端点
API_LIST_URL = f"{BASE_URL}/api/fs/list" # 用于列出目录
API_GET_URL = f"{BASE_URL}/api/fs/get"   # 用于获取单个文件的下载链接

# 3. 本地下载文件的根目录
DOWNLOAD_DIR = "." # 下载到当前文件夹

# 4. 如果根目录或某些目录需要密码，请填写在这里
PASSWORD = "" 

# 5. 下载文件时的请求头，模拟浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Referer": BASE_URL,
    "Origin": BASE_URL,
}

# 6. 全局会话
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# --- 核心功能 ---

def fetch_and_download_file(full_remote_path, local_save_dir, item_name):
    """
    第一步：调用 /api/fs/get 获取文件的实际元数据 (包括 raw_url 和 size)。
    第二步：执行下载和断点续传。
    """
    
    # --- 第 1 步: 获取文件元数据 ---
    payload = {"path": full_remote_path, "password": PASSWORD}
    
    try:
        # 为此文件发起新的 API 请求
        response = SESSION.post(API_GET_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data['code'] != 200:
            print(f"  [错误] 无法获取 {item_name} 的元数据: {data['message']}")
            return
            
        file_item = data['data']
        
        # 检查 'raw_url'
        if 'raw_url' not in file_item or not file_item['raw_url']:
            print(f"  [跳过] {item_name} 成功获取元数据，但仍无 'raw_url'。")
            return
            
        raw_url = file_item['raw_url']
        file_size = file_item['size']
        local_file_path = os.path.join(local_save_dir, item_name)

        # --- 第 2 步: 下载与断点续传逻辑 ---

        local_file_size = 0
        if os.path.exists(local_file_path):
            local_file_size = os.path.getsize(local_file_path)

        if local_file_size == file_size:
            print(f"  [跳过] 文件已存在且大小一致: {local_file_path}")
            return

        print(f"  [下载] 正在下载: {local_file_path} ({file_size / (1024*1024):.2f} MB)")

        # 如果本地有部分文件，尝试断点续传
        headers = HEADERS.copy()
        if local_file_size > 0:
            headers['Range'] = f'bytes={local_file_size}-'
            mode = 'ab' # 追加模式
        else:
            mode = 'wb' # 覆盖写入

        response_dl = SESSION.get(raw_url, stream=True, headers=headers, timeout=30)
        
        if response_dl.status_code not in (200, 206):
            response_dl.raise_for_status()

        with open(local_file_path, mode) as f:
            for chunk in response_dl.iter_content(chunk_size=81920): # 80KB 块
                f.write(chunk)
        
        final_size = os.path.getsize(local_file_path)
        if final_size != file_size:
             print(f"  [警告] 下载完成，但大小不匹配: {local_file_path}. (预期: {file_size}, 实际: {final_size})")

    except requests.exceptions.RequestException as e:
        print(f"  [错误] 处理文件 {item_name} 时出错: {e}")
    except Exception as e:
        print(f"  [严重错误] 处理 {item_name} 时发生未知错误: {e}")


def crawl_directory(remote_path, local_path):
    """
    递归地爬取一个目录 (使用 /api/fs/list)
    """
    
    print(f"\n--- 正在进入目录: {remote_path} ---")
    os.makedirs(local_path, exist_ok=True) # 确保本地目录存在

    payload = {
        "path": remote_path,
        "password": PASSWORD,
        "page": 1,
        "per_page": 0, # 0 表示获取该目录下的所有文件
        "refresh": False
    }

    try:
        # 3. 发送 POST 请求获取文件列表
        response = SESSION.post(API_LIST_URL, json=payload, timeout=10) # 使用 LIST API
        response.raise_for_status() 
        data = response.json()
    
    except requests.exceptions.Timeout:
        print(f"  [错误] 连接超时: {remote_path}")
        return
    except requests.exceptions.RequestException as e:
        print(f"  [错误] 访问 API 失败: {remote_path}。错误: {e}")
        return
    except Exception as e:
        print(f"  [严重错误] 获取目录列表时发生未知错误: {e}")
        return

    # 4. 检查 API 响应
    if data['code'] != 200:
        print(f"  [错误] 访问 API 失败: {data['message']}。")
        if "password" in data['message']:
            print("  [提示] 这可能是一个受密码保护的文件夹，请检查脚本中的 PASSWORD 设置。")
        return

    content = data['data']['content']
    if not content:
        print("  (空目录)")
        return

    # 5. 遍历目录内容
    for item in content:
        try:
            item_name = item['name']
            
            # (A) 如果是文件夹，递归调用
            if item['is_dir']:
                new_remote_path = f"{remote_path.rstrip('/')}/{item_name}"
                new_local_path = os.path.join(local_path, item_name)
                crawl_directory(new_remote_path, new_local_path)
            
            # (B) 如果是文件，调用新的下载函数
            else:
                full_remote_path = f"{remote_path.rstrip('/')}/{item_name}"
                # 'local_path' 是当前文件的保存目录 (例如 . 或 ./数学类)
                fetch_and_download_file(full_remote_path, local_path, item_name)
                
                # 下载间歇性暂停，防止过于频繁
                time.sleep(0.1) # 100毫秒

        except Exception as e:
            print(f"  [严重错误] 处理 {item.get('name', '未知项')} 时发生未知错误: {e}")


# --- 启动脚本 ---
if __name__ == "__main__":
    print(f"*** AList 爬取工具 ***")
    print(f"目标: {BASE_URL}")
    print(f"本地目录: {DOWNLOAD_DIR} (即当前文件夹)")
    print("------------------------")
    
    # 从根目录 (/) 开始爬取
    crawl_directory("/", DOWNLOAD_DIR)
    
    print("\n*** 爬取完成 ***")