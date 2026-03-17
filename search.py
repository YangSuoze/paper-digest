import time
import random
import os
import re
import requests
import pandas as pd
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from llm_tools import LLMClient


class AdvancedScholarScraper:
    def __init__(self, download_dir:str="downloads",user_requirement:str=""):
        self.download_dir = os.path.abspath(download_dir)
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
        
        self.driver = self._init_driver()
        self.results = []
        self.user_requirement = user_requirement
        self.unrelated_count = 0

    def _init_driver(self):
        options = Options()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        
        # --- 关键配置：设置自动下载 PDF ---
        prefs = {
            "download.default_directory": self.download_dir, # 下载路径
            "download.prompt_for_download": False,           # 不询问下载位置
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,      # 不在浏览器打开PDF，直接下载
            "safebrowsing.enabled": True
        }
        options.add_experimental_option("prefs", prefs)
        # ------------------------------------

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # 抹除指纹
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"""
        })
        return driver

    def random_sleep(self, min_time=3, max_time=6):
        """随机等待，避免被封"""
        time.sleep(random.uniform(min_time, max_time))

    def search_advanced(self, keyword, journal=None, year=None):
        """
        keyword: 搜索关键词
        journal: 指定期刊名称 (可选)
        year: 指定年份 (int) (可选)
        """
        # 1. 构造搜索关键词
        query = keyword
        if journal:
            # 使用 source:"Journal Name" 语法
            query += f' source:"{journal}"'
        
        # 2. 构造 URL (处理年份)
        base_url = "https://scholar.google.com/scholar"
        search_url = f"{base_url}?q={query}"
        
        if year:
            # as_ylo 是起始年份, as_yhi 是结束年份
            start_year = year
            end_year = year
            search_url += f"&as_ylo={start_year}&as_yhi={end_year}"
            
        print(f"正在访问搜索链接: {search_url}")
        self.driver.get(search_url)
        self.random_sleep(2, 4)

    def check_captcha(self):
        """检测验证码"""
        if "recaptcha" in self.driver.page_source.lower():
            print("\n!!! ⚠️ 遇到验证码 ⚠️ !!!")
            input("请手动在浏览器完成验证，然后按回车键继续...")

    def download_file_from_link(self, url, title):
        """尝试使用 requests 下载文件（针对直接链接）"""
        try:
            print(f"   -> 尝试下载: {title[:20]}...")
            headers = {'User-Agent': self.driver.execute_script("return navigator.userAgent;")}
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            
            if response.status_code == 200:
                # 清理文件名中的非法字符
                safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).strip()
                safe_title = safe_title[:50] # 截断过长文件名
                ext = ".pdf" if "pdf" in response.headers.get('Content-Type', '').lower() else ".html"
                filename = os.path.join(self.download_dir, f"{safe_title}{ext}")
                
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"   [成功] 文件已保存: {filename}")
                return "Downloaded"
            else:
                print(f"   [失败] 状态码: {response.status_code}")
                return "Download Failed"
        except Exception as e:
            print(f"   [错误] 下载异常: {e}")
            return "Error"

    def process_article(self, article_element):
        """处理单篇文献：提取信息 + 尝试下载"""
        try:
            # 1. 提取基础信息
            title_tag = article_element.find_element(By.CSS_SELECTOR, "h3.gs_rt a")
            title = title_tag.text
            # 使用大模型读取title是否和用户搜索意图强相关
            input_query = f"""请判断以下论文标题是否与用户输入相关：
当前论文标题{title}
用户需求: {self.user_requirement}
如果相关，返回1，如果不相关返回0。不需要多余的词汇。直接返回0/1即可"""
            is_related = LLMClient().query(input_query)
            print(f"   论文标题: {title}... 相关性判断: {is_related.strip()}")
            if is_related.strip() == "0":
                self.unrelated_count += 1
                print(f"   -> 不相关论文计数: {self.unrelated_count}")
                return None
            main_link = title_tag.get_attribute("href")
        except:
            return None # 如果没有链接或标题，跳过

        # 2. 查找是否有谷歌直接提供的 PDF 链接 (右侧的一栏)
        pdf_link = "N/A"
        download_status = "Not Attempted"
        
        try:
            # 查找右侧的 [PDF] 或 [HTML] 链接
            ggsm = article_element.find_element(By.CSS_SELECTOR, "div.gs_or_ggsm a")
            pdf_link = ggsm.get_attribute("href")
            link_text = ggsm.text
            
            if "PDF" in link_text:
                # 策略 A: 如果有直接 PDF 链接，直接下载
                download_status = self.download_file_from_link(pdf_link, title)
            else:
                # 如果是 HTML 链接，也可以保存，视情况而定
                download_status = "HTML Link Found"
        except NoSuchElementException:
            # 策略 B: 如果没有直接链接，尝试进入主链接 (出版商页面)
            # 注意：这里我们只模拟点击进入，不进行复杂的出版商页面解析，因为每个网站结构不同
            print(f"   -> 无直接PDF，点击进入出版商页面: {title[:20]}...")
            
            # 记录当前窗口句柄
            original_window = self.driver.current_window_handle
            try:
                #在新标签页打开
                self.driver.execute_script("window.open(arguments[0]);", main_link)
                self.random_sleep(2, 3)
                
                # 切换到新窗口
                new_window = [w for w in self.driver.window_handles if w != original_window][0]
                self.driver.switch_to.window(new_window)
                # === 核心修改：调用深度处理函数 ===
                download_status = self.deep_process_publisher_page(title)
            except Exception as e:
                print(f"   -> 出版商页面处理异常: {e}")
                download_status = "Publisher Page Error"
            finally:
                # 无论成功失败，确保关闭标签页并切回
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
                self.driver.switch_to.window(original_window)

        return {
            "Title": title,
            "Link": main_link,
            "Direct_PDF_Link": pdf_link,
            "Download_Status": download_status
        }


    def deep_process_publisher_page(self, title):
        """
        在出版商页面尝试寻找并下载 PDF
        增加逻辑：如果第一次未找到，刷新页面重试
        """
        self.random_sleep(3, 5) # 首次进入等待加载
        found_pdf_url = None
        
        # === 重试循环：最多尝试 2 次 (第1次正常，第2次刷新后) ===
        for attempt in range(5):
            current_url = self.driver.current_url
            print(f"   -> 分析出版商页面 (尝试 {attempt + 1}/2): {current_url[:40]}...")

            # 1. 尝试提取 PDF 链接
            # --- 针对 IEEE Xplore 的特定逻辑 ---
            if "ieeexplore.ieee.org" in current_url:
                found_pdf_url = self._extract_ieee_pdf()
            
            # --- 针对其他网站的通用逻辑 (如果特定逻辑没找到) ---
            if not found_pdf_url:
                found_pdf_url = self._extract_generic_pdf()

            # 2. 如果找到了，跳出循环
            if found_pdf_url:
                break
            
            # 3. 如果没找到，且是第一次尝试，则刷新页面
            print("   -> 未在页面上找到明显的PDF下载按钮，正在刷新页面重试...")
            try:
                self.driver.refresh()
                # 刷新后给予更充分的加载时间
                self.random_sleep(5, 8)
            except Exception as e:
                print(f"   -> 刷新页面失败: {e}")
                break # 刷新失败则停止重试

        # === 最终判断与下载 ===
        if found_pdf_url:
            print(f"   -> 捕获到潜在PDF链接: {found_pdf_url}")
            # 注意：必须传入 cookies，因为出版商页面通常需要权限
            cookies = self.driver.get_cookies()
            status = self.download_file_with_cookies(found_pdf_url, title, cookies)
            print(f"   -> 下载状态: {status}")
            return status
        else:
            print("   -> 重试后仍未在页面上找到明显的PDF下载按钮")
            return "PDF Button Not Found"
    
    def download_file_with_cookies(self, url, title, selenium_cookies):
        """
        使用 Selenium 的 Cookies 进行下载 (解决权限/Paywall问题)
        增加了针对 IEEE stamp 页面的解析逻辑
        """
        try:
            # 设置最大重试次数，防止 418 无限循环
            max_retries = 10
            retry_count = 0
            
            while retry_count < max_retries:
                session = requests.Session()
                # 设置一些伪装 Header，特别是 Referer 很重要
                headers = {
                    "User-Agent": self.driver.execute_script("return navigator.userAgent;"),
                    "Referer": self.driver.current_url
                }
                
                for cookie in selenium_cookies:
                    session.cookies.set(cookie['name'], cookie['value'])
                
                print(f"   -> 开始下载 (带Cookie): {title[:15]}...")
                
                # allow_redirects=True 是默认的，但显式写出来更好
                response = session.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True)
                
                if response.status_code == 200:
                    # 检查内容类型
                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    # === 核心修改：针对 IEEE 的特殊处理 ===
                    if "ieeexplore" in url and ("html" in content_type or "text" in content_type):
                        print("   -> 检测到 IEEE 包装页面，正在解析真实 PDF 链接...")
                        # 必须读取文本内容进行解析（注意：这会消耗 stream，所以如果不是 PDF，后面无法再 iter_content，但这里没关系）
                        html_content = response.text
                        
                        # 使用正则提取 iframe src
                        # 典型的 IEEE iframe: <iframe src="https://ieeexplore.ieee.org/ielx7/..." frameborder=0 ...>
                        match = re.search(r'<iframe\s+[^>]*src=["\']([^"\']+)["\']', html_content)
                        
                        if match:
                            real_pdf_url = match.group(1)
                            # 处理相对路径 (如果有)
                            if not real_pdf_url.startswith("http"):
                                # 有时候提取出来是 /ielx7/...
                                if real_pdf_url.startswith("/"):
                                    real_pdf_url = "https://ieeexplore.ieee.org" + real_pdf_url
                            
                            # 把 HTML 里的转义字符处理一下 (比如 &amp;)
                            real_pdf_url = real_pdf_url.replace("&amp;", "&")

                            print(f"   -> 解析成功，真实链接: {real_pdf_url[:40]}...")
                            
                            # 递归调用自己，去下载解析出来的真实链接
                            # 注意：这里直接 return 递归的结果
                            return self.download_file_with_cookies(real_pdf_url, title, selenium_cookies)
                        else:
                            return "Failed (Could not parse IEEE PDF link from HTML)"
                    
                    # === 正常的 PDF 下载逻辑 ===
                    if 'application/pdf' in content_type or 'octet-stream' in content_type:
                        # 保存文件
                        safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()[:100]
                        # 确保 self.download_dir 存在，如果你用 self.save_dir 请自行替换
                        save_dir = getattr(self, 'download_dir', '.') 
                        if not os.path.exists(save_dir):
                            os.makedirs(save_dir)
                            
                        filename = os.path.join(save_dir, f"{safe_title}.pdf")
                        
                        with open(filename, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        return "Success (Publisher)"
                    
                    else:
                        return f"Failed (Content-Type: {content_type})"

                elif response.status_code == 418:
                    print(f"   -> 服务器拒绝访问 (418)，等待后重试 ({retry_count+1}/{max_retries})...")
                    self.random_sleep(2, 4) # 稍微歇一会
                    retry_count += 1
                    continue
                else:
                    return f"Failed (Status: {response.status_code})"
            
            return "Failed (Max Retries Exceeded)"
                
        except Exception as e:
            return f"Download Error: {str(e)}"

    def _extract_ieee_pdf(self):
        """专门处理 IEEE 页面"""
        try:
            # IEEE 的 PDF 按钮通常包含 "stamp/stamp.jsp"
            # 寻找页面上所有 href 包含 stamp 的链接
            # IEEE 结构变化多端，常见的按钮是一个带图标的链接
            
            # 方法1: 寻找包含 stamp.jsp 的链接
            pdf_elements = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='stamp/stamp.jsp']")
            
            for elem in pdf_elements:
                link = elem.get_attribute("href")
                # 排除无效链接
                if link and "arnumber" in link:
                    # IEEE 的 stamp 链接其实是一个 HTML 包装器 (Viewer)
                    # 我们可以尝试将其转换为直接下载链接，或者直接下载这个 URL (requests 可能会得到 HTML)
                    # 更好的方式是：IEEE 的 stamp 链接通常可以直接用，但需要 Referer 头
                    return link
            return None
        except Exception as e:
            print(f"   (IEEE解析错误: {e})")
            return None

    def _extract_generic_pdf(self):
        """
        通用启发式搜索：寻找文本中包含 PDF 的按钮或 href 结尾是 .pdf 的链接
        """
        try:
            # 1. 优先搜索 href 结尾是 .pdf 的
            links = self.driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href")
                if href and href.lower().endswith(".pdf"):
                    return href
            
            # 2. 搜索按钮文本包含 "PDF" 或 "Download" 的
            # 使用 XPath 查找文本内容
            candidates = self.driver.find_elements(By.XPATH, "//a[contains(translate(text(), 'PDF', 'pdf'), 'pdf')]")
            for candidate in candidates:
                href = candidate.get_attribute("href")
                if href:
                    return href
            
            return None
        except:
            return None
        

    def run(self, keyword, journal=None, year=None, max_pages=1):
        # 搜索文章
        self.search_advanced(keyword, journal, year)
        # 逐页处理
        for page in range(max_pages):
            print(f"\n--- 正在处理第 {page + 1} 页 ---")
            self.check_captcha()
            
            # 获取当前页所有文章元素
            articles = self.driver.find_elements(By.CSS_SELECTOR, "div.gs_r.gs_or.gs_scl")
            
            for i, article in enumerate(articles):
                print(f"处理第 {i+1} 篇...")
                data = self.process_article(article)
                if self.unrelated_count >= 10:
                    print("已跳过10篇不相关论文，结束搜索。")
                    break
                if data:
                    self.results.append(data)
                self.random_sleep(2, 4) # 每篇之间休息一下，非常重要！
            else:
                # 翻页逻辑
                try:
                    next_btn = self.driver.find_element(By.XPATH, "//b[text()='下一页'] | //span[contains(text(),'Next')]/parent::b")
                    parent = next_btn.find_element(By.XPATH, "./parent::a")
                    self.driver.execute_script("arguments[0].click();", parent)
                    self.random_sleep(5, 8) # 翻页后长等待
                except:
                    print("没有下一页了或翻页失败。")
                    break
                continue
            break # 如果达到不相关论文数，跳出外层循环
        # 保存结果
        df = pd.DataFrame(self.results)
        df.to_csv("scholar_advanced_results.csv", index=False, encoding="utf-8-sig")
        print("\n抓取完成，结果已保存。")
        self.driver.quit()

if __name__ == "__main__":
    # 使用示例
    scraper = AdvancedScholarScraper(download_dir="my_papers", user_requirement="查询医学报告生成相关的文章，多模态医学AI方向")
    
    # 搜索：在 "Nature" 期刊中，搜索 "Machine Learning"，年份 2023
    # 常用期刊: Nature, Science, IEEE Transactions on Medical Imaging
    scraper.run(
        keyword="medical report generation", # 搜索关键词
        journal="IEEE Transactions on Medical Imaging", # 指定期刊
        year=2025, # 指定年份
        max_pages=10  # 建议测试时只跑1页
    )